"""Fine-tune DistilBERT on a bounded SQuAD v1 subset."""

import argparse
import time
from pathlib import Path
from typing import Any

import evaluate
import torch
from datasets import load_dataset
from transformers import (
    AutoModelForQuestionAnswering,
    AutoTokenizer,
    DefaultDataCollator,
    EarlyStoppingCallback,
    Trainer,
)

from ml.transformers.common import (
    MODEL_ROOT,
    ROOT,
    TimeLimitCallback,
    VRAMCallback,
    best_validation_loss,
    load_config,
    log_mlflow,
    oom_message,
    peak_vram_gib,
    runtime_device,
    save_loss_curve,
    save_result,
    training_time_limit,
    trainer_arguments,
)
from ml.transformers.qa.data import prepare_qa_features


def _extract_predictions(
    raw_examples: Any,
    feature_metadata: dict[str, list[Any]],
    start_logits: Any,
    end_logits: Any,
) -> list[dict[str, Any]]:
    """Choose the best valid context span across overflow features."""
    import numpy as np

    example_by_id = {example["id"]: example for example in raw_examples}
    best: dict[str, tuple[float, str, float]] = {}
    for index, (example_id, offsets) in enumerate(
        zip(
            feature_metadata["example_id"],
            feature_metadata["offset_mapping"],
            strict=True,
        )
    ):
        starts = np.asarray(start_logits[index])
        ends = np.asarray(end_logits[index])
        start_probabilities = torch.softmax(
            torch.tensor(starts, dtype=torch.float32), dim=0
        ).numpy()
        end_probabilities = torch.softmax(
            torch.tensor(ends, dtype=torch.float32), dim=0
        ).numpy()
        start_candidates = np.argsort(starts)[-20:][::-1]
        end_candidates = np.argsort(ends)[-20:][::-1]
        context = example_by_id[example_id]["context"]
        for start_index in start_candidates:
            if offsets[start_index] is None:
                continue
            for end_index in end_candidates:
                if (
                    end_index < start_index
                    or end_index - start_index + 1 > 30
                    or offsets[end_index] is None
                ):
                    continue
                score = float(starts[start_index] + ends[end_index])
                answer = context[offsets[start_index][0] : offsets[end_index][1]]
                confidence = float(
                    start_probabilities[start_index] * end_probabilities[end_index]
                )
                if example_id not in best or score > best[example_id][0]:
                    best[example_id] = (score, answer, confidence)
    return [
        {
            "id": example["id"],
            "prediction_text": best.get(example["id"], (0.0, "", 0.0))[1],
        }
        for example in raw_examples
    ]


def _score(
    raw_examples: Any,
    feature_metadata: dict[str, list[Any]],
    logits: tuple[Any, Any],
    metric: Any,
) -> dict[str, float]:
    predictions = _extract_predictions(
        raw_examples, feature_metadata, logits[0], logits[1]
    )
    references = [
        {"id": example["id"], "answers": example["answers"]} for example in raw_examples
    ]
    return {
        key: float(value)
        for key, value in metric.compute(
            predictions=predictions, references=references
        ).items()
    }


def run(config_path: Path) -> dict[str, Any]:
    """Train, score the best validation-loss checkpoint, and save artifacts."""
    device = runtime_device()
    settings = load_config(config_path)["qa"]
    if device.type != "cuda":
        raise RuntimeError(
            "This Step 10 training run requires the configured CUDA GPU."
        )
    torch.cuda.reset_peak_memory_stats()
    dataset_id = str(settings.get("dataset_id", "rajpurkar/squad"))
    model_id = str(settings.get("model_id", "distilbert/distilbert-base-uncased"))
    train_count = int(settings.get("train_samples", 20_000))
    validation_count = int(settings.get("validation_samples", 2_000))
    baseline_count = min(int(settings.get("baseline_samples", 200)), validation_count)
    train_raw = load_dataset(dataset_id, split=f"train[:{train_count}]")
    validation_raw = load_dataset(dataset_id, split=f"validation[:{validation_count}]")
    tokenizer = AutoTokenizer.from_pretrained(model_id, use_fast=True)
    train_features = train_raw.map(
        lambda examples: prepare_qa_features(
            examples,
            tokenizer,
            max_length=int(settings["max_seq_len"]),
            doc_stride=int(settings["doc_stride"]),
            training=True,
        ),
        batched=True,
        remove_columns=train_raw.column_names,
    )
    train_features = train_features.remove_columns(["offset_mapping"])
    validation_features_with_meta = validation_raw.map(
        lambda examples: prepare_qa_features(
            examples,
            tokenizer,
            max_length=int(settings["max_seq_len"]),
            doc_stride=int(settings["doc_stride"]),
            training=False,
        ),
        batched=True,
        remove_columns=validation_raw.column_names,
    )
    feature_metadata = {
        "example_id": list(validation_features_with_meta["example_id"]),
        "offset_mapping": list(validation_features_with_meta["offset_mapping"]),
    }
    validation_features = validation_features_with_meta.remove_columns(
        ["example_id", "offset_mapping"]
    )
    model = AutoModelForQuestionAnswering.from_pretrained(model_id)
    model.gradient_checkpointing_enable()
    metric = evaluate.load("squad")
    baseline_metrics = None
    if baseline_count:
        baseline_raw = validation_raw.select(range(baseline_count))
        baseline_ids = set(baseline_raw["id"])
        baseline_indices = [
            index
            for index, example_id in enumerate(feature_metadata["example_id"])
            if example_id in baseline_ids
        ]
        baseline_features = validation_features.select(baseline_indices)
        baseline_meta = {
            "example_id": [
                feature_metadata["example_id"][index] for index in baseline_indices
            ],
            "offset_mapping": [
                feature_metadata["offset_mapping"][index] for index in baseline_indices
            ],
        }
        baseline_output = Trainer(
            model=model,
            data_collator=DefaultDataCollator(),
        ).predict(baseline_features)
        baseline_metrics = _score(
            baseline_raw, baseline_meta, baseline_output.predictions, metric
        )

    output_dir = ROOT / "models" / "transformers" / "checkpoints" / "qa"
    args = trainer_arguments(
        output_dir,
        learning_rate=float(settings["learning_rate"]),
        batch_size=int(settings["batch_size"]),
        grad_accumulation_steps=int(settings["grad_accumulation_steps"]),
        epochs=float(settings["epochs"]),
        eval_steps=int(settings.get("eval_steps", 500)),
        fp16=True,
        seed=int(settings["seed"]),
    )
    vram_callback = VRAMCallback()
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train_features,
        eval_dataset=validation_features,
        data_collator=DefaultDataCollator(),
        callbacks=[
            EarlyStoppingCallback(
                early_stopping_patience=int(settings["early_stopping_patience"])
            ),
            TimeLimitCallback(training_time_limit(settings)),
            vram_callback,
        ],
    )
    training_started = time.monotonic()
    try:
        trainer.train()
        prediction = trainer.predict(validation_features)
    except RuntimeError as error:
        raise oom_message(error) from error
    scores = _score(validation_raw, feature_metadata, prediction.predictions, metric)
    best_eval_loss = best_validation_loss(trainer)
    final_dir = MODEL_ROOT / "qa"
    trainer.save_model(final_dir)
    tokenizer.save_pretrained(final_dir)
    save_loss_curve(trainer.state.log_history, MODEL_ROOT / "loss_curves" / "qa.png")
    result = {
        "dataset_id": dataset_id,
        "model_id": model_id,
        "subset_sizes": {
            "train": len(train_raw),
            "validation": len(validation_raw),
            "baseline": baseline_count,
        },
        "validation_metrics": scores,
        "unfinetuned_baseline_metrics": baseline_metrics,
        "best_validation_loss": best_eval_loss,
        "best_checkpoint": trainer.state.best_model_checkpoint,
        "scored_checkpoint": "best validation-loss checkpoint (load_best_model_at_end)",
        "training_seconds": round(time.monotonic() - training_started, 1),
        "peak_vram_gib": max([peak_vram_gib(), *vram_callback.epoch_peaks_gib]),
        "peak_vram_per_epoch_gib": vram_callback.epoch_peaks_gib,
        "device": str(device),
    }
    save_result("qa", result)
    log_mlflow("qa", result, bool(load_config(config_path).get("mlflow", False)))
    print(f"QA result: {result}", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", type=Path, default=ROOT / "configs" / "local_4gb.yaml"
    )
    run(parser.parse_args().config)
