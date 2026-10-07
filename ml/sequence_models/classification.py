"""Shared classifier setup, evaluation, and artifact persistence."""

import sys
import time
from pathlib import Path
from typing import Any

import torch
from torch.utils.data import DataLoader

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for path in (PROJECT_ROOT, BACKEND_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from ml.sequence_models.data import (
    CLASS_NAMES,
    MODEL_ROOT,
    save_inference_artifact,
)
from ml.sequence_models.metrics import classification_metrics
from ml.sequence_models.models import Architecture, build_classifier
from ml.sequence_models.pretrained import (
    load_local_vectors,
    make_embedding_matrix,
)
from ml.sequence_models.trainer import (
    SequenceDataset,
    Trainer,
    query_gpu_telemetry,
    sequence_collate,
)
from ml.sequence_models.vocabulary import Vocabulary


def train_classifier(
    task: str,
    architecture: Architecture,
    train_data: tuple[list[str], list[int]],
    validation_data: tuple[list[str], list[int]],
    test_data: tuple[list[str], list[int]],
    vocabulary: Vocabulary,
    config: dict[str, Any],
    model_root: Path = MODEL_ROOT,
) -> dict[str, Any]:
    """Train one model, restore its best checkpoint, evaluate and save inference weights."""
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; refusing to train on CPU.")
    device_index = torch.cuda.current_device()
    telemetry = query_gpu_telemetry(device_index)
    print("device: cuda", flush=True)
    print(
        f"GPU: {torch.cuda.get_device_name(device_index)} "
        f"utilization_percent={telemetry['utilization_percent']} "
        f"memory_mib={telemetry['memory_used_mib']}/"
        f"{telemetry['memory_total_mib']}",
        flush=True,
    )
    classes = CLASS_NAMES[task]
    train_set = SequenceDataset(*train_data, vocabulary, int(config["max_seq_len"]))
    validation_set = SequenceDataset(
        *validation_data, vocabulary, int(config["max_seq_len"])
    )
    test_set = SequenceDataset(*test_data, vocabulary, int(config["max_seq_len"]))
    loader_kwargs = {
        "batch_size": int(config["batch_size"]),
        "collate_fn": sequence_collate,
        "num_workers": 0,
        "pin_memory": True,
    }
    train_loader = DataLoader(train_set, shuffle=True, **loader_kwargs)
    validation_loader = DataLoader(validation_set, shuffle=False, **loader_kwargs)
    test_loader = DataLoader(
        test_set,
        batch_size=int(config.get("eval_batch_size", min(config["batch_size"], 4))),
        shuffle=False,
        **{key: value for key, value in loader_kwargs.items() if key != "batch_size"},
    )
    embedding_weights = None
    embedding_source = config.get("embedding_source")
    if embedding_source:
        vectors = load_local_vectors(str(embedding_source), PROJECT_ROOT)
        if vectors is not None:
            config = {**config, "embedding_dim": vectors.vector_size}
            embedding_weights = make_embedding_matrix(vocabulary, vectors)
            del vectors
            embedding_init = str(embedding_source)
        else:
            embedding_init = "scratch"
            print(
                f"Embedding source {embedding_source!r} is not already cached; "
                "initializing embeddings from scratch.",
                flush=True,
            )
    else:
        embedding_init = "scratch"
        print("Initializing embeddings from scratch.", flush=True)
    model = build_classifier(
        len(vocabulary),
        len(classes),
        architecture,
        config,
        embedding_weights,
    )
    output_dir = model_root / task
    checkpoint_path = output_dir / f"{architecture}.last.pt"
    if not config.get("resume", False):
        checkpoint_path.unlink(missing_ok=True)
        checkpoint_path.with_name(
            f"{checkpoint_path.stem}.best{checkpoint_path.suffix}"
        ).unlink(missing_ok=True)
    trainer = Trainer(model, config, checkpoint_path)
    started = time.perf_counter()
    history = trainer.fit(
        train_loader,
        validation_loader,
        int(config["epochs"]),
        resume=bool(config.get("resume", False)),
    )
    training_seconds = time.perf_counter() - started
    best_checkpoint = torch.load(
        trainer.best_checkpoint_path,
        map_location=trainer.device,
        weights_only=True,
    )
    model.load_state_dict(best_checkpoint["model"])
    model.eval()
    targets: list[int] = []
    predictions: list[int] = []
    try:
        if trainer.device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(trainer.device)
        with torch.inference_mode():
            for input_ids, lengths, labels in test_loader:
                with torch.autocast(
                    device_type=trainer.device.type,
                    dtype=torch.float16,
                    enabled=trainer.use_amp,
                ):
                    logits = model(input_ids.to(trainer.device), lengths)
                predictions.extend(logits.argmax(dim=1).cpu().tolist())
                targets.extend(labels.tolist())
    except torch.cuda.OutOfMemoryError as error:
        if trainer.device.type == "cuda":
            torch.cuda.empty_cache()
        raise RuntimeError(
            "CUDA ran out of memory during evaluation. Reduce eval_batch_size "
            "or max_seq_len."
        ) from error
    metrics = classification_metrics(targets, predictions, len(classes))
    artifact_path = output_dir / f"{architecture}.pt"
    save_inference_artifact(
        artifact_path,
        model,
        architecture,
        vocabulary.to_dict(),
        classes,
        config,
        int(config["max_seq_len"]),
    )
    return {
        "architecture": architecture,
        "task": task,
        "metrics": metrics,
        "training_seconds": training_seconds,
        "parameter_count": sum(parameter.numel() for parameter in model.parameters()),
        "peak_vram_gib": max(
            max((record["peak_vram_gib"] for record in history), default=0.0),
            (
                torch.cuda.max_memory_allocated(trainer.device) / (1024**3)
                if trainer.device.type == "cuda"
                else 0.0
            ),
        ),
        "gpu_utilization_peak_percent": max(
            (record["gpu_utilization_percent"] for record in history),
            default=float(telemetry["utilization_percent"]),
        ),
        "batch_size": int(config["batch_size"]),
        "eval_batch_size": int(
            config.get("eval_batch_size", min(config["batch_size"], 4))
        ),
        "embedding_init": embedding_init,
        "history": history,
        "artifact": str(artifact_path),
        "vocabulary": vocabulary,
    }
