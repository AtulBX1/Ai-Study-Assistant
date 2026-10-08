"""Fine-tune DistilBERT on CoNLL-2003 token-level NER labels."""

import argparse
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from datasets import load_dataset
from huggingface_hub import hf_hub_download
from seqeval.metrics import (
    classification_report,
    f1_score,
    precision_score,
    recall_score,
)
from transformers import (
    AutoModelForTokenClassification,
    AutoTokenizer,
    DataCollatorForTokenClassification,
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
from ml.transformers.ner.data import tokenize_and_align_labels


def _sequence_labels(
    logits: np.ndarray, label_ids: np.ndarray, labels: list[str]
) -> tuple[list[list[str]], list[list[str]]]:
    predictions = np.argmax(logits, axis=2)
    true_predictions: list[list[str]] = []
    true_labels: list[list[str]] = []
    for predicted_row, label_row in zip(predictions, label_ids, strict=True):
        row_predictions: list[str] = []
        row_labels: list[str] = []
        for predicted, actual in zip(predicted_row, label_row, strict=True):
            if actual == -100:
                continue
            row_predictions.append(labels[int(predicted)])
            row_labels.append(labels[int(actual)])
        true_predictions.append(row_predictions)
        true_labels.append(row_labels)
    return true_predictions, true_labels


def _load_conll(dataset_id: str) -> tuple[Any, list[str]]:
    """Load the qualified TNER files without executing the legacy dataset script."""
    if dataset_id != "tner/conll2003":
        dataset = load_dataset(dataset_id)
        label_names = list(dataset["train"].features["ner_tags"].feature.names)
        return dataset, label_names
    file_names = {
        "train": "dataset/train.json",
        "validation": "dataset/valid.json",
        "test": "dataset/test.json",
    }
    files = {
        split: hf_hub_download(
            repo_id=dataset_id,
            filename=filename,
            repo_type="dataset",
        )
        for split, filename in file_names.items()
    }
    label_path = hf_hub_download(
        repo_id=dataset_id,
        filename="dataset/label.json",
        repo_type="dataset",
    )
    label_to_id = json.loads(Path(label_path).read_text(encoding="utf-8"))
    label_names = [
        label for label, _ in sorted(label_to_id.items(), key=lambda item: item[1])
    ]
    dataset = load_dataset("json", data_files=files)
    dataset = dataset.rename_column("tags", "ner_tags")
    return dataset, label_names


def run(config_path: Path) -> dict[str, Any]:
    """Train, evaluate the best validation-loss checkpoint, and save artifacts."""
    device = runtime_device()
    settings = load_config(config_path)["ner"]
    if device.type != "cuda":
        raise RuntimeError(
            "This Step 10 training run requires the configured CUDA GPU."
        )
    torch.cuda.reset_peak_memory_stats()
    dataset_id = str(settings.get("dataset_id", "tner/conll2003"))
    model_id = str(settings.get("model_id", "distilbert/distilbert-base-uncased"))
    raw, label_names = _load_conll(dataset_id)
    sample_sizes = {
        "train": int(settings.get("train_samples", len(raw["train"]))),
        "validation": int(settings.get("validation_samples", len(raw["validation"]))),
        "test": int(settings.get("test_samples", len(raw["test"]))),
    }
    subsets = {
        split: raw[split].select(range(min(count, len(raw[split]))))
        for split, count in sample_sizes.items()
    }
    tokenizer = AutoTokenizer.from_pretrained(model_id, use_fast=True)
    tokenized = {
        split: dataset.map(
            lambda examples: tokenize_and_align_labels(
                examples, tokenizer, int(settings["max_seq_len"])
            ),
            batched=True,
            remove_columns=dataset.column_names,
        )
        for split, dataset in subsets.items()
    }
    model = AutoModelForTokenClassification.from_pretrained(
        model_id,
        num_labels=len(label_names),
        id2label=dict(enumerate(label_names)),
        label2id={label: index for index, label in enumerate(label_names)},
    )
    model.gradient_checkpointing_enable()

    def compute_metrics(prediction: Any) -> dict[str, float]:
        predicted, actual = _sequence_labels(
            prediction.predictions, prediction.label_ids, label_names
        )
        return {
            "precision": float(precision_score(actual, predicted, zero_division=0)),
            "recall": float(recall_score(actual, predicted, zero_division=0)),
            "f1": float(f1_score(actual, predicted, zero_division=0)),
        }

    output_dir = ROOT / "models" / "transformers" / "checkpoints" / "ner"
    args = trainer_arguments(
        output_dir,
        learning_rate=float(settings["learning_rate"]),
        batch_size=int(settings["batch_size"]),
        grad_accumulation_steps=int(settings["grad_accumulation_steps"]),
        epochs=float(settings["epochs"]),
        eval_steps=int(settings.get("eval_steps", 250)),
        fp16=True,
        seed=int(settings["seed"]),
    )
    vram_callback = VRAMCallback()
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=tokenized["train"],
        eval_dataset=tokenized["validation"],
        data_collator=DataCollatorForTokenClassification(tokenizer=tokenizer),
        compute_metrics=compute_metrics,
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
        prediction = trainer.predict(tokenized["test"])
    except RuntimeError as error:
        raise oom_message(error) from error
    predicted_labels, actual_labels = _sequence_labels(
        prediction.predictions, prediction.label_ids, label_names
    )
    per_entity = classification_report(
        actual_labels, predicted_labels, output_dict=True, zero_division=0
    )
    best_eval_loss = best_validation_loss(trainer)
    final_dir = MODEL_ROOT / "ner"
    trainer.save_model(final_dir)
    tokenizer.save_pretrained(final_dir)
    save_loss_curve(trainer.state.log_history, MODEL_ROOT / "loss_curves" / "ner.png")
    result = {
        "dataset_id": dataset_id,
        "model_id": model_id,
        "subset_sizes": {split: len(dataset) for split, dataset in subsets.items()},
        "entity_metrics": {
            "overall": {
                "precision": float(
                    precision_score(actual_labels, predicted_labels, zero_division=0)
                ),
                "recall": float(
                    recall_score(actual_labels, predicted_labels, zero_division=0)
                ),
                "f1": float(f1_score(actual_labels, predicted_labels, zero_division=0)),
            },
            "per_entity_type": {
                name: metrics
                for name, metrics in per_entity.items()
                if isinstance(metrics, dict) and name in {"PER", "ORG", "LOC", "MISC"}
            },
        },
        "best_validation_loss": best_eval_loss,
        "best_checkpoint": trainer.state.best_model_checkpoint,
        "scored_checkpoint": "best validation-loss checkpoint (load_best_model_at_end)",
        "training_seconds": round(time.monotonic() - training_started, 1),
        "peak_vram_gib": max([peak_vram_gib(), *vram_callback.epoch_peaks_gib]),
        "peak_vram_per_epoch_gib": vram_callback.epoch_peaks_gib,
        "device": str(device),
    }
    save_result("ner", result)
    log_mlflow("ner", result, bool(load_config(config_path).get("mlflow", False)))
    print(f"NER result: {result}", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", type=Path, default=ROOT / "configs" / "local_4gb.yaml"
    )
    run(parser.parse_args().config)
