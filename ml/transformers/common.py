"""Shared configuration, device, timeout, and reporting helpers."""

import json
import math
import os
import time
from pathlib import Path
from typing import Any

import torch
import yaml
from transformers import TrainerCallback

ROOT = Path(__file__).resolve().parents[2]
MODEL_ROOT = ROOT / "models" / "transformers"

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


def runtime_device() -> torch.device:
    """Print the required runtime and GPU identity before work begins."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    gpu_name = torch.cuda.get_device_name(0) if device.type == "cuda" else "CPU"
    print(f"device: {device.type}", flush=True)
    print(f"GPU: {gpu_name}", flush=True)
    return device


def load_config(path: Path) -> dict[str, Any]:
    """Load transformer settings from the selected YAML configuration."""
    with path.open(encoding="utf-8") as stream:
        config = yaml.safe_load(stream)
    section = config.get("transformers")
    if not isinstance(section, dict):
        raise TypeError(f"{path} must define a transformers mapping.")
    return section


class TimeLimitCallback(TrainerCallback):
    """Stop Trainer at a wall-clock limit while allowing checkpoint saves."""

    def __init__(self, max_seconds: int) -> None:
        self.max_seconds = max_seconds
        self.started_at = time.monotonic()

    def on_step_end(self, args, state, control, **kwargs):
        if time.monotonic() - self.started_at >= self.max_seconds:
            control.should_training_stop = True
        return control


def training_time_limit(settings: dict[str, Any]) -> int:
    """Reserve the configured finalization window inside each hard job limit."""
    maximum = int(settings["max_seconds"])
    reserve = int(settings.get("finalization_seconds", 120))
    if maximum <= reserve:
        raise ValueError("max_seconds must exceed finalization_seconds.")
    return maximum - reserve


class VRAMCallback(TrainerCallback):
    """Print and retain each epoch's peak allocated GPU memory."""

    def __init__(self) -> None:
        self.epoch_peaks_gib: list[float] = []

    def on_epoch_end(self, args, state, control, **kwargs):
        if torch.cuda.is_available():
            peak = round(torch.cuda.max_memory_allocated() / (1024**3), 3)
            self.epoch_peaks_gib.append(peak)
            print(
                f"peak_vram_gib_epoch_{len(self.epoch_peaks_gib)}={peak}",
                flush=True,
            )
            torch.cuda.reset_peak_memory_stats()
        return control


def trainer_arguments(
    output_dir: Path,
    *,
    learning_rate: float,
    batch_size: int,
    grad_accumulation_steps: int,
    epochs: float,
    eval_steps: int,
    fp16: bool,
    seed: int,
) -> Any:
    """Construct version-compatible Trainer arguments."""
    from transformers import TrainingArguments

    options: dict[str, Any] = {
        "output_dir": str(output_dir),
        "learning_rate": learning_rate,
        "per_device_train_batch_size": batch_size,
        "per_device_eval_batch_size": max(1, min(batch_size, 8)),
        "gradient_accumulation_steps": grad_accumulation_steps,
        "num_train_epochs": epochs,
        "eval_steps": eval_steps,
        "save_steps": eval_steps,
        "logging_steps": max(1, eval_steps // 4),
        "save_total_limit": 2,
        "load_best_model_at_end": True,
        "metric_for_best_model": "eval_loss",
        "greater_is_better": False,
        "fp16": fp16,
        "bf16": False,
        "gradient_checkpointing": True,
        "report_to": [],
        "seed": seed,
        "data_seed": seed,
        "dataloader_num_workers": 0,
        "disable_tqdm": False,
    }
    import inspect

    signature = inspect.signature(TrainingArguments)
    if "eval_strategy" in signature.parameters:
        options["eval_strategy"] = "steps"
    else:
        options["evaluation_strategy"] = "steps"
    supported_options = {
        name: value for name, value in options.items() if name in signature.parameters
    }
    return TrainingArguments(**supported_options)


def best_validation_loss(trainer: Any) -> float:
    """Ensure a run has a scored, saved checkpoint selected by validation loss."""
    losses = [
        float(entry["eval_loss"])
        for entry in trainer.state.log_history
        if "eval_loss" in entry and math.isfinite(float(entry["eval_loss"]))
    ]
    if trainer.state.best_model_checkpoint is not None and losses:
        return min(losses)
    metrics = trainer.evaluate()
    validation_loss = float(metrics["eval_loss"])
    if not math.isfinite(validation_loss):
        raise RuntimeError("Validation did not produce a finite eval_loss.")
    checkpoint = Path(trainer.args.output_dir) / "checkpoint-time-limited-eval"
    trainer.save_model(checkpoint)
    trainer.state.best_model_checkpoint = str(checkpoint)
    trainer.state.best_metric = validation_loss
    return validation_loss


def save_loss_curve(log_history: list[dict[str, Any]], path: Path) -> None:
    """Persist training and validation loss points as a compact PNG."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    train_points = [
        (entry["step"], entry["loss"])
        for entry in log_history
        if "loss" in entry and "step" in entry
    ]
    eval_points = [
        (entry["step"], entry["eval_loss"])
        for entry in log_history
        if "eval_loss" in entry and "step" in entry
    ]
    figure, axis = plt.subplots(figsize=(7, 4))
    if train_points:
        axis.plot(*zip(*train_points, strict=True), label="training loss")
    if eval_points:
        axis.plot(*zip(*eval_points, strict=True), label="validation loss")
    axis.set(xlabel="Trainer step", ylabel="Loss", title=path.stem)
    if train_points or eval_points:
        axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=130)
    plt.close(figure)

def _json_default(value):
    import numpy as np

    if isinstance(value, np.integer):
       return int(value)
    if isinstance(value, np.floating):
       return float(value)
    if isinstance(value, np.ndarray):
       return value.tolist()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

def save_result(name: str, result: dict[str, Any]) -> None:
    """Persist a mode result alongside existing transformer evaluation tables."""
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    path = MODEL_ROOT / "evaluation.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    previous[name] = result
    path.write_text(json.dumps(previous, indent=2, default=_json_default), encoding="utf-8")

def log_mlflow(name: str, result: dict[str, Any], enabled: bool) -> None:
    """Log scalar evaluation values only when MLflow is enabled in YAML."""
    if not enabled:
        return
    import mlflow

    metrics: dict[str, float] = {}

    def collect(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                collect(f"{prefix}.{key}" if prefix else key, child)
        elif isinstance(value, (int, float)) and math.isfinite(value):
            metrics[prefix.replace("/", "_")[:250]] = float(value)

    collect("", result)
    with mlflow.start_run(run_name=f"step10-{name}"):
        mlflow.log_metrics(metrics)
        mlflow.set_tag("model", name)


def peak_vram_gib() -> float:
    """Return this run's maximum PyTorch-allocated CUDA memory in GiB."""
    if not torch.cuda.is_available():
        return 0.0
    return round(torch.cuda.max_memory_allocated() / (1024**3), 3)


def oom_message(error: RuntimeError) -> RuntimeError:
    """Attach the project-specific mitigation when CUDA runs out of memory."""
    if "out of memory" not in str(error).lower():
        return error
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return RuntimeError(
        "CUDA out of memory; reduce batch_size or max_seq_len and retry."
    )
