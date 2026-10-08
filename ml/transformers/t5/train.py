"""Fine-tune and evaluate T5-small summarization and question generation."""

import argparse
import time
from pathlib import Path
from typing import Any

import evaluate
import torch
from datasets import load_dataset
from transformers import (
    AutoModelForSeq2SeqLM,
    AutoTokenizer,
    DataCollatorForSeq2Seq,
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
from ml.transformers.t5.data import load_summary_subsets, qg_text


def _score_generated(
    model: Any,
    tokenizer: Any,
    inputs: list[str],
    references: list[str],
    *,
    source_max_length: int,
    max_target_length: int,
    batch_size: int,
    decoding: str,
) -> tuple[dict[str, float], list[str]]:
    """Generate a deterministic prefix subset and compute ROUGE/BLEU."""
    rouge = evaluate.load("rouge")
    bleu = evaluate.load("sacrebleu")
    predictions: list[str] = []
    model.eval()
    device = next(model.parameters()).device
    for start in range(0, len(inputs), batch_size):
        batch = tokenizer(
            inputs[start : start + batch_size],
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=source_max_length,
        ).to(device)
        try:
            with torch.inference_mode(), torch.autocast(
                device_type="cuda",
                dtype=torch.float16,
                enabled=device.type == "cuda",
            ):
                generated = model.generate(
                    **batch,
                    max_new_tokens=max_target_length,
                    num_beams=3 if decoding == "beam" else 1,
                    do_sample=False,
                    early_stopping=decoding == "beam",
                )
        except RuntimeError as error:
            raise oom_message(error) from error
        predictions.extend(tokenizer.batch_decode(generated, skip_special_tokens=True))
    reference_subset = references[: len(predictions)]
    rouge_scores = rouge.compute(
        predictions=predictions,
        references=reference_subset,
        use_stemmer=True,
    )
    bleu_score = bleu.compute(
        predictions=predictions,
        references=[[item] for item in reference_subset],
    )["score"]
    return {
        "rouge1": float(rouge_scores["rouge1"]),
        "rouge2": float(rouge_scores["rouge2"]),
        "rougeL": float(rouge_scores["rougeL"]),
        "bleu": float(bleu_score) / 100.0,
        "sample_size": len(predictions),
    }, predictions


def _prepare_summary(
    dataset: Any, tokenizer: Any, source_max: int, target_max: int
) -> Any:
    def preprocess(batch: dict[str, list[str]]) -> dict[str, Any]:
        inputs = ["summarize: " + text for text in batch["article"]]
        encoded = tokenizer(
            inputs,
            max_length=source_max,
            truncation=True,
        )
        encoded["labels"] = tokenizer(
            text_target=batch["highlights"],
            max_length=target_max,
            truncation=True,
        )["input_ids"]
        return encoded

    return dataset.map(preprocess, batched=True, remove_columns=dataset.column_names)


def _prepare_qg(dataset: Any, tokenizer: Any, source_max: int, target_max: int) -> Any:
    def preprocess(batch: dict[str, Any]) -> dict[str, Any]:
        inputs = [
            qg_text(context, answer)
            for context, answer in zip(
                batch["context"],
                [
                    answers["text"][0] if answers["text"] else ""
                    for answers in batch["answers"]
                ],
                strict=True,
            )
        ]
        encoded = tokenizer(inputs, max_length=source_max, truncation=True)
        encoded["labels"] = tokenizer(
            text_target=batch["question"],
            max_length=target_max,
            truncation=True,
        )["input_ids"]
        return encoded

    return dataset.map(preprocess, batched=True, remove_columns=dataset.column_names)


def _train(
    tokenizer: Any,
    model: Any,
    train_data: Any,
    validation_data: Any,
    settings: dict[str, Any],
    output_dir: Path,
) -> tuple[Trainer, float]:
    """Run bounded Trainer fine-tuning with evaluation-loss checkpointing."""
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
    training_started = time.monotonic()
    vram_callback = VRAMCallback()
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train_data,
        eval_dataset=validation_data,
        data_collator=DataCollatorForSeq2Seq(tokenizer=tokenizer, model=model),
        callbacks=[
            EarlyStoppingCallback(
                early_stopping_patience=int(settings["early_stopping_patience"])
            ),
            TimeLimitCallback(training_time_limit(settings)),
            vram_callback,
        ],
    )
    try:
        trainer.train()
    except RuntimeError as error:
        raise oom_message(error) from error
    best_loss = best_validation_loss(trainer)
    trainer._step10_training_seconds = time.monotonic() - training_started
    trainer._step10_vram_callback = vram_callback
    return trainer, best_loss


def _summarize(config: dict[str, Any], device: torch.device) -> dict[str, Any]:
    settings = config["summarization"]
    data = load_summary_subsets(
        dataset_id=str(settings.get("dataset_id", "abisee/cnn_dailymail")),
        dataset_config=str(settings.get("dataset_config", "3.0.0")),
        train_count=int(settings.get("train_samples", 10_000)),
        validation_count=int(settings.get("validation_samples", 1_000)),
        test_count=int(settings.get("test_samples", 1_000)),
    )
    tokenizer = AutoTokenizer.from_pretrained(
        str(settings.get("model_id", "google-t5/t5-small"))
    )
    model = AutoModelForSeq2SeqLM.from_pretrained(
        str(settings.get("model_id", "google-t5/t5-small"))
    ).to(device)
    model.gradient_checkpointing_enable()
    model.config.use_cache = False
    encoded = {
        split: _prepare_summary(
            subset,
            tokenizer,
            int(settings["max_seq_len"]),
            int(settings["target_max_len"]),
        )
        for split, subset in data.items()
    }
    trainer, best_loss = _train(
        tokenizer,
        model,
        encoded["train"],
        encoded["validation"],
        settings,
        ROOT / "models" / "transformers" / "checkpoints" / "t5-summarization",
    )
    model = trainer.model
    model.config.use_cache = True
    test = data["test"]
    greedy_count = min(int(settings.get("greedy_eval_samples", 500)), len(test))
    beam_count = min(int(settings.get("beam_eval_samples", 200)), len(test))
    articles = list(test["article"])
    references = list(test["highlights"])
    train_seconds = round(float(trainer._step10_training_seconds), 1)
    records: dict[str, Any] = {}
    for strategy, count in (("greedy", greedy_count), ("beam", beam_count)):
        metrics, generated = _score_generated(
            model,
            tokenizer,
            ["summarize: " + article for article in articles[:count]],
            references[:count],
            source_max_length=int(settings["max_seq_len"]),
            max_target_length=int(settings["target_max_len"]),
            batch_size=int(settings.get("eval_batch_size", 2)),
            decoding=strategy,
        )
        records[strategy] = {
            **metrics,
            "test_indices": f"first {count} examples",
            "examples": [
                {
                    "prediction": generated[index],
                    "reference": references[index],
                }
                for index in range(min(5, len(generated)))
            ],
        }
    final_dir = MODEL_ROOT / "t5-summarization"
    trainer.save_model(final_dir)
    tokenizer.save_pretrained(final_dir)
    save_loss_curve(
        trainer.state.log_history,
        MODEL_ROOT / "loss_curves" / "t5-summarization.png",
    )
    result = {
        "dataset_id": str(settings.get("dataset_id", "abisee/cnn_dailymail")),
        "model_id": str(settings.get("model_id", "google-t5/t5-small")),
        "subset_sizes": {split: len(subset) for split, subset in data.items()},
        "metrics": records,
        "best_validation_loss": best_loss,
        "best_checkpoint": trainer.state.best_model_checkpoint,
        "scored_checkpoint": "best validation-loss checkpoint (load_best_model_at_end)",
        "training_seconds": train_seconds,
        "peak_vram_gib": max(
            [peak_vram_gib(), *trainer._step10_vram_callback.epoch_peaks_gib]
        ),
        "peak_vram_per_epoch_gib": (trainer._step10_vram_callback.epoch_peaks_gib),
        "device": str(device),
        "seq2seq_comparison_note": (
            "Step 9 reports 1,000 test examples for each decoder; these metrics "
            "use the first 500 greedy and first 200 beam examples, so are not "
            "strictly comparable unless Step 9 predictions are recomputed on "
            "these same subsets."
        ),
    }
    save_result("t5_summarization", result)
    log_mlflow("t5_summarization", result, bool(config.get("mlflow", False)))
    print(f"T5 summarization result: {result}", flush=True)
    return result


def _question_generation(
    config: dict[str, Any], device: torch.device
) -> dict[str, Any]:
    settings = config["question_generation"]
    dataset_id = str(settings.get("dataset_id", "rajpurkar/squad"))
    train_raw = load_dataset(
        dataset_id, split=f"train[:{int(settings.get('train_samples', 20_000))}]"
    )
    validation_raw = load_dataset(
        dataset_id, split=f"validation[:{int(settings.get('validation_samples', 500))}]"
    )
    model_id = str(settings.get("model_id", "google-t5/t5-small"))
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    tokenizer.add_special_tokens({"additional_special_tokens": ["<hl>"]})
    model = AutoModelForSeq2SeqLM.from_pretrained(model_id).to(device)
    model.resize_token_embeddings(len(tokenizer))
    model.gradient_checkpointing_enable()
    model.config.use_cache = False
    train_encoded = _prepare_qg(
        train_raw,
        tokenizer,
        int(settings["max_seq_len"]),
        int(settings["target_max_len"]),
    )
    validation_encoded = _prepare_qg(
        validation_raw,
        tokenizer,
        int(settings["max_seq_len"]),
        int(settings["target_max_len"]),
    )
    trainer, best_loss = _train(
        tokenizer,
        model,
        train_encoded,
        validation_encoded,
        settings,
        ROOT / "models" / "transformers" / "checkpoints" / "t5-question-generation",
    )
    model = trainer.model
    model.config.use_cache = True
    count = min(int(settings.get("eval_samples", 200)), len(validation_raw))
    subset = validation_raw.select(range(count))
    inputs = [
        qg_text(context, answers["text"][0] if answers["text"] else "")
        for context, answers in zip(subset["context"], subset["answers"], strict=True)
    ]
    references = list(subset["question"])
    metrics, predictions = _score_generated(
        model,
        tokenizer,
        inputs,
        references,
        source_max_length=int(settings["max_seq_len"]),
        max_target_length=int(settings["target_max_len"]),
        batch_size=int(settings.get("eval_batch_size", 2)),
        decoding="greedy",
    )
    final_dir = MODEL_ROOT / "t5-question-generation"
    trainer.save_model(final_dir)
    tokenizer.save_pretrained(final_dir)
    save_loss_curve(
        trainer.state.log_history,
        MODEL_ROOT / "loss_curves" / "t5-question-generation.png",
    )
    examples = [
        {
            "context": subset[index]["context"],
            "answer": subset[index]["answers"]["text"][0],
            "generated_question": predictions[index],
            "reference_question": subset[index]["question"],
        }
        for index in range(min(10, len(predictions)))
    ]
    result = {
        "dataset_id": dataset_id,
        "model_id": model_id,
        "subset_sizes": {
            "train": len(train_raw),
            "validation": len(validation_raw),
            "evaluated": len(predictions),
        },
        "metrics": metrics,
        "examples": examples,
        "best_validation_loss": best_loss,
        "best_checkpoint": trainer.state.best_model_checkpoint,
        "scored_checkpoint": "best validation-loss checkpoint (load_best_model_at_end)",
        "training_seconds": round(float(trainer._step10_training_seconds), 1),
        "peak_vram_gib": max(
            [peak_vram_gib(), *trainer._step10_vram_callback.epoch_peaks_gib]
        ),
        "peak_vram_per_epoch_gib": (trainer._step10_vram_callback.epoch_peaks_gib),
        "device": str(device),
    }
    save_result("t5_question_generation", result)
    log_mlflow(
        "t5_question_generation",
        result,
        bool(config.get("mlflow", False)),
    )
    print(f"T5 question-generation result: {result}", flush=True)
    return result


def run(mode: str, config_path: Path) -> dict[str, Any]:
    """Run one T5 task, ensuring each job uses the required GPU identity banner."""
    device = runtime_device()
    if device.type != "cuda":
        raise RuntimeError(
            "This Step 10 training run requires the configured CUDA GPU."
        )
    torch.cuda.reset_peak_memory_stats()
    config = load_config(config_path)
    if mode == "summarization":
        return _summarize(config, device)
    return _question_generation(config, device)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("summarization", "question_generation"))
    parser.add_argument(
        "--config", type=Path, default=ROOT / "configs" / "local_4gb.yaml"
    )
    args = parser.parse_args()
    run(args.mode, args.config)
