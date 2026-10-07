"""Reproducible training, validation, checkpointing, and OOM handling."""

import gc
import random
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset

from ml.sequence_models.vocabulary import Vocabulary, pad_sequences


def query_gpu_telemetry(device_index: int = 0) -> dict[str, int]:
    """Read utilization and memory from the NVIDIA driver without extra packages."""
    result = subprocess.run(
        [
            "nvidia-smi",
            f"--id={device_index}",
            "--query-gpu=utilization.gpu,memory.used,memory.total",
            "--format=csv,noheader,nounits",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    values = [int(value.strip()) for value in result.stdout.strip().split(",")]
    if len(values) != 3:
        raise RuntimeError(f"Unexpected nvidia-smi telemetry output: {result.stdout!r}")
    utilization, memory_used, memory_total = values
    return {
        "utilization_percent": utilization,
        "memory_used_mib": memory_used,
        "memory_total_mib": memory_total,
    }


def set_seed(seed: int) -> None:
    """Seed Python, NumPy, and Torch and disable nondeterministic cuDNN search."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True


class SequenceDataset(Dataset[tuple[list[int], int]]):
    """Encoded text examples and integer class labels."""

    def __init__(
        self,
        texts: Sequence[str],
        labels: Sequence[int],
        vocabulary: Vocabulary,
        max_seq_len: int,
    ) -> None:
        if len(texts) != len(labels):
            raise ValueError("Texts and labels must have the same length.")
        self.examples = [
            (vocabulary.encode(text, max_seq_len), int(label))
            for text, label in zip(texts, labels, strict=True)
        ]

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, index: int) -> tuple[list[int], int]:
        return self.examples[index]


def sequence_collate(
    batch: Sequence[tuple[list[int], int]],
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Pad text IDs and return labels and CPU lengths."""
    ids, labels = zip(*batch, strict=True)
    padded, lengths = pad_sequences(ids)
    return padded, lengths, torch.tensor(labels, dtype=torch.long)


class Trainer:
    """Train a packed-sequence classifier with fp16, clipping, and early stopping."""

    def __init__(
        self,
        model: nn.Module,
        config: dict[str, Any],
        checkpoint_path: Path,
        device: torch.device | None = None,
    ) -> None:
        self.model = model
        self.config = config
        self.checkpoint_path = checkpoint_path
        self.best_checkpoint_path = checkpoint_path.with_name(
            f"{checkpoint_path.stem}.best{checkpoint_path.suffix}"
        )
        self.device = device or torch.device(
            "cuda" if torch.cuda.is_available() else "cpu"
        )
        self.use_amp = bool(config.get("mixed_precision", True)) and (
            self.device.type == "cuda"
        )
        self.model.to(self.device)
        self.optimizer = torch.optim.AdamW(
            self.model.parameters(),
            lr=float(config.get("learning_rate", 0.001)),
            weight_decay=float(config.get("weight_decay", 0.0)),
        )
        self.scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            self.optimizer,
            mode="min",
            factor=float(config.get("lr_factor", 0.5)),
            patience=int(config.get("lr_patience", 1)),
        )
        self.criterion = nn.CrossEntropyLoss()
        self.scaler = torch.amp.GradScaler("cuda", enabled=self.use_amp)
        self.best_validation_loss = float("inf")
        self.bad_epochs = 0
        self.start_epoch = 0

    def resume(self, path: Path | None = None) -> None:
        """Restore model, optimizer, scaler, scheduler, and early-stop state."""
        checkpoint = torch.load(
            path or self.checkpoint_path,
            map_location=self.device,
            weights_only=True,
        )
        self.model.load_state_dict(checkpoint["model"])
        self.optimizer.load_state_dict(checkpoint["optimizer"])
        self.scheduler.load_state_dict(checkpoint["scheduler"])
        self.scaler.load_state_dict(checkpoint["scaler"])
        self.start_epoch = int(checkpoint["epoch"]) + 1
        self.best_validation_loss = float(checkpoint["best_validation_loss"])
        self.bad_epochs = int(checkpoint["bad_epochs"])

    def fit(
        self,
        train_loader: DataLoader[tuple[torch.Tensor, torch.Tensor, torch.Tensor]],
        validation_loader: DataLoader[tuple[torch.Tensor, torch.Tensor, torch.Tensor]],
        epochs: int,
        resume: bool = False,
    ) -> list[dict[str, float]]:
        """Train until epochs are exhausted or validation loss stops improving."""
        if epochs < 1:
            raise ValueError("epochs must be positive.")
        if resume and self.checkpoint_path.exists():
            self.resume()
        history: list[dict[str, float]] = []
        for epoch in range(self.start_epoch, epochs):
            if self.device.type == "cuda":
                torch.cuda.reset_peak_memory_stats(self.device)
            started = time.perf_counter()
            try:
                train_loss = self._run_epoch(train_loader, training=True)
                validation_loss = self._run_epoch(validation_loader, training=False)
            except torch.cuda.OutOfMemoryError as error:
                self.optimizer.zero_grad(set_to_none=True)
                if self.device.type == "cuda":
                    torch.cuda.empty_cache()
                gc.collect()
                raise RuntimeError(
                    "CUDA ran out of memory. Reduce batch_size or max_seq_len, "
                    "or increase grad_accumulation_steps."
                ) from error
            self.scheduler.step(validation_loss)
            improved = validation_loss < self.best_validation_loss
            if improved:
                self.best_validation_loss = validation_loss
                self.bad_epochs = 0
            else:
                self.bad_epochs += 1
            peak_memory_gib = (
                torch.cuda.max_memory_allocated(self.device) / (1024**3)
                if self.device.type == "cuda"
                else 0.0
            )
            telemetry = (
                query_gpu_telemetry(self.device.index or 0)
                if self.device.type == "cuda"
                else {
                    "utilization_percent": 0,
                    "memory_used_mib": 0,
                    "memory_total_mib": 0,
                }
            )
            record = {
                "epoch": float(epoch + 1),
                "train_loss": train_loss,
                "validation_loss": validation_loss,
                "training_seconds": time.perf_counter() - started,
                "peak_vram_gib": peak_memory_gib,
                "gpu_utilization_percent": float(telemetry["utilization_percent"]),
            }
            history.append(record)
            print(
                f"epoch={epoch + 1} train_loss={train_loss:.4f} "
                f"val_loss={validation_loss:.4f} "
                f"gpu_utilization_percent={telemetry['utilization_percent']} "
                f"gpu_memory_mib={telemetry['memory_used_mib']}/"
                f"{telemetry['memory_total_mib']} "
                f"peak_vram_gib={peak_memory_gib:.3f}",
                flush=True,
            )
            self._save_checkpoint(epoch, improved)
            if self.bad_epochs >= int(self.config.get("early_stopping_patience", 2)):
                break
        return history

    def _run_epoch(
        self,
        loader: DataLoader[tuple[torch.Tensor, torch.Tensor, torch.Tensor]],
        training: bool,
    ) -> float:
        self.model.train(training)
        self.optimizer.zero_grad(set_to_none=True)
        total_loss = 0.0
        total_examples = 0
        accumulation_steps = int(self.config.get("grad_accumulation_steps", 1))
        for batch_index, (input_ids, lengths, labels) in enumerate(loader):
            input_ids = input_ids.to(self.device, non_blocking=True)
            labels = labels.to(self.device, non_blocking=True)
            is_last_batch = batch_index + 1 == len(loader)
            group_start = (batch_index // accumulation_steps) * accumulation_steps
            group_size = min(accumulation_steps, len(loader) - group_start)
            with torch.set_grad_enabled(training):
                with torch.autocast(
                    device_type=self.device.type,
                    dtype=torch.float16,
                    enabled=self.use_amp,
                ):
                    logits = self.model(input_ids, lengths)
                    loss = self.criterion(logits, labels)
                if training:
                    self.scaler.scale(loss / group_size).backward()
                    if (batch_index + 1) % accumulation_steps == 0 or is_last_batch:
                        self.scaler.unscale_(self.optimizer)
                        nn.utils.clip_grad_norm_(
                            self.model.parameters(),
                            float(self.config.get("gradient_clip_norm", 1.0)),
                        )
                        self.scaler.step(self.optimizer)
                        self.scaler.update()
                        self.optimizer.zero_grad(set_to_none=True)
            total_loss += float(loss.detach()) * len(labels)
            total_examples += len(labels)
        return total_loss / max(total_examples, 1)

    def _save_checkpoint(self, epoch: int, improved: bool) -> None:
        """Persist enough state to resume and a safe inference-only best checkpoint."""
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint = {
            "model": self.model.state_dict(),
            "optimizer": self.optimizer.state_dict(),
            "scheduler": self.scheduler.state_dict(),
            "scaler": self.scaler.state_dict(),
            "epoch": epoch,
            "best_validation_loss": self.best_validation_loss,
            "bad_epochs": self.bad_epochs,
        }
        torch.save(checkpoint, self.checkpoint_path)
        if improved:
            torch.save(checkpoint, self.best_checkpoint_path)


def train_truncated_bptt_batch(
    model: nn.Module,
    inputs: torch.Tensor,
    targets: torch.Tensor,
    optimizer: torch.optim.Optimizer,
    criterion: Callable[[torch.Tensor, torch.Tensor], torch.Tensor],
    chunk_length: int,
    gradient_clip_norm: float = 1.0,
    mixed_precision: bool = True,
    scaler: torch.amp.GradScaler | None = None,
) -> float:
    """Train a next-token model in detached chunks to bound recurrent activations.

    Truncated BPTT carries the LSTM hidden state into the next chunk but detaches
    it at each boundary. Memory is therefore bounded by ``chunk_length``; gradients
    do not flow across those boundaries, so very long-range dependencies are lost.
    """
    if chunk_length < 1 or inputs.shape[1] != targets.shape[1]:
        raise ValueError(
            "chunk_length must be positive and input/target lengths equal."
        )
    device = inputs.device
    if scaler is None:
        scaler = torch.amp.GradScaler(
            "cuda", enabled=mixed_precision and device.type == "cuda"
        )
    hidden: Any = None
    total_loss = 0.0
    token_count = 0
    optimizer.zero_grad(set_to_none=True)
    for start in range(0, inputs.shape[1], chunk_length):
        end = min(start + chunk_length, inputs.shape[1])
        chunk = inputs[:, start:end]
        expected = targets[:, start:end]
        with torch.autocast(
            device_type=device.type,
            dtype=torch.float16,
            enabled=mixed_precision and device.type == "cuda",
        ):
            logits, hidden = model(chunk, hidden)
            loss = criterion(logits.reshape(-1, logits.shape[-1]), expected.reshape(-1))
        scaler.scale(loss).backward()
        if hidden is not None:
            hidden = tuple(item.detach() for item in hidden)
        total_loss += float(loss.detach()) * expected.numel()
        token_count += expected.numel()
    scaler.unscale_(optimizer)
    nn.utils.clip_grad_norm_(model.parameters(), gradient_clip_norm)
    scaler.step(optimizer)
    scaler.update()
    optimizer.zero_grad(set_to_none=True)
    return total_loss / max(token_count, 1)
