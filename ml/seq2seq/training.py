"""Mixed-precision training, checkpointing, and loss-curve output."""

import copy
import json
import logging
import time
from pathlib import Path
from typing import Any

import torch
from torch import nn
from torch.utils.data import DataLoader

from ml.seq2seq.data import SummaryDataset, collate_summaries
from ml.seq2seq.models import Seq2SeqConfig, SequenceToSequence
from ml.seq2seq.vocabulary import PAD_ID, Seq2SeqVocabulary

logger = logging.getLogger(__name__)


def _loss_for_batches(
    model: SequenceToSequence,
    loader: DataLoader,
    device: torch.device,
    *,
    amp: bool,
) -> float:
    model.eval()
    total_loss = 0.0
    total_tokens = 0
    with torch.inference_mode():
        for source, lengths, decoder_input, labels in loader:
            source, decoder_input, labels = (
                source.to(device),
                decoder_input.to(device),
                labels.to(device),
            )
            with torch.autocast(
                device_type=device.type, dtype=torch.float16, enabled=amp
            ):
                logits, _ = model(source, lengths, decoder_input)
                loss = nn.functional.cross_entropy(
                    logits.reshape(-1, logits.shape[-1]),
                    labels.reshape(-1),
                    ignore_index=PAD_ID,
                    reduction="sum",
                )
            token_count = int(labels.ne(PAD_ID).sum())
            total_loss += float(loss)
            total_tokens += token_count
    return total_loss / max(1, total_tokens)


def _write_loss_curve(history: list[dict[str, float]], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(7, 4))
    axis.plot(
        [row["epoch"] for row in history],
        [row["train_loss"] for row in history],
        label="train",
    )
    axis.plot(
        [row["epoch"] for row in history],
        [row["validation_loss"] for row in history],
        label="validation",
    )
    axis.set(xlabel="Epoch", ylabel="Token cross-entropy", title="Seq2seq loss")
    axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=140)
    plt.close(figure)


def train_variant(
    variant: str,
    train_examples: list[dict[str, str]],
    validation_examples: list[dict[str, str]],
    vocabulary: Seq2SeqVocabulary,
    settings: dict[str, Any],
    output_dir: Path,
    device: torch.device,
) -> tuple[SequenceToSequence, list[dict[str, float]]]:
    """Train one configured architecture under an elapsed-time budget."""
    torch.manual_seed(int(settings["seed"]))
    if device.type == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats(device)
    model_config = Seq2SeqConfig(
        vocab_size=len(vocabulary),
        embedding_dim=int(settings["embedding_dim"]),
        hidden_size=int(settings["hidden_size"]),
        num_layers=int(settings["num_layers"]),
        dropout=float(settings["dropout"]),
        bidirectional=bool(settings["bidirectional"]),
        attention=variant,  # type: ignore[arg-type]
        luong_score=str(settings["luong_score"]),
        max_source_length=int(settings["source_max_length"]),
        max_target_length=int(settings["target_max_length"]),
        coverage=bool(settings["coverage"]),
    )
    model = SequenceToSequence(model_config).to(device)
    train_data = SummaryDataset(
        train_examples,
        vocabulary,
        model_config.max_source_length,
        model_config.max_target_length,
    )
    validation_data = SummaryDataset(
        validation_examples,
        vocabulary,
        model_config.max_source_length,
        model_config.max_target_length,
    )
    batch_size = int(settings["batch_size"])
    train_loader = DataLoader(
        train_data,
        batch_size=batch_size,
        shuffle=True,
        collate_fn=collate_summaries,
        generator=torch.Generator().manual_seed(int(settings["seed"])),
    )
    validation_loader = DataLoader(
        validation_data,
        batch_size=int(settings["eval_batch_size"]),
        shuffle=False,
        collate_fn=collate_summaries,
    )
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(settings["learning_rate"]),
        weight_decay=float(settings["weight_decay"]),
    )
    amp = device.type == "cuda" and bool(settings["mixed_precision"])
    scaler = torch.amp.GradScaler("cuda", enabled=amp)
    output_dir.mkdir(parents=True, exist_ok=True)
    latest_path = output_dir / f"{variant}.latest.pt"
    best_path = output_dir / f"{variant}.pt"
    resume = bool(settings["resume"]) and latest_path.exists()
    start_epoch = 1
    best_loss = float("inf")
    stale_epochs = 0
    history: list[dict[str, float]] = []
    best_state: dict[str, torch.Tensor] | None = None
    if resume:
        checkpoint = torch.load(latest_path, map_location=device, weights_only=False)
        model.load_state_dict(checkpoint["model"])
        optimizer.load_state_dict(checkpoint["optimizer"])
        scaler.load_state_dict(checkpoint["scaler"])
        start_epoch = int(checkpoint["epoch"]) + 1
        best_loss = float(checkpoint["best_loss"])
        stale_epochs = int(checkpoint["stale_epochs"])
        history = checkpoint["history"]
        best_state = checkpoint["best_model"]
        logger.info("%s: resumed at epoch %d", variant, start_epoch)

    accumulation = max(1, int(settings["grad_accumulation_steps"]))
    max_seconds = float(settings["max_seconds_per_variant"])
    started = time.monotonic()
    for epoch in range(start_epoch, int(settings["epochs"]) + 1):
        if time.monotonic() - started >= max_seconds:
            logger.info("%s: time budget reached before epoch %d", variant, epoch)
            break
        model.train()
        optimizer.zero_grad(set_to_none=True)
        epoch_loss = 0.0
        epoch_tokens = 0
        epoch_steps = 0
        time_budget_reached = False
        epoch_started = time.monotonic()
        for step, (source, lengths, decoder_input, labels) in enumerate(
            train_loader, start=1
        ):
            if time.monotonic() - started >= max_seconds:
                time_budget_reached = True
                break
            source, decoder_input, labels = (
                source.to(device),
                decoder_input.to(device),
                labels.to(device),
            )
            ratio = float(settings["teacher_forcing_ratio"])
            if bool(settings["scheduled_sampling"]):
                ratio = max(0.5, ratio - 0.05 * (epoch - 1))
            try:
                with torch.autocast(
                    device_type=device.type, dtype=torch.float16, enabled=amp
                ):
                    logits, _ = model(
                        source,
                        lengths,
                        decoder_input,
                        teacher_forcing_ratio=ratio,
                        scheduled_sampling=bool(settings["scheduled_sampling"]),
                    )
                    loss_sum = nn.functional.cross_entropy(
                        logits.reshape(-1, logits.shape[-1]),
                        labels.reshape(-1),
                        ignore_index=PAD_ID,
                        reduction="sum",
                    )
                    token_count = int(labels.ne(PAD_ID).sum())
                    loss = loss_sum / max(1, token_count)
                scaler.scale(loss / accumulation).backward()
                epoch_loss += float(loss_sum.detach())
                epoch_tokens += token_count
                epoch_steps += 1
                if step % accumulation == 0 or step == len(train_loader):
                    scaler.unscale_(optimizer)
                    nn.utils.clip_grad_norm_(
                        model.parameters(), float(settings["gradient_clip_norm"])
                    )
                    scaler.step(optimizer)
                    scaler.update()
                    optimizer.zero_grad(set_to_none=True)
            except RuntimeError as error:
                if "out of memory" in str(error).lower():
                    if device.type == "cuda":
                        torch.cuda.empty_cache()
                    raise RuntimeError(
                        f"{variant} ran out of GPU memory; reduce batch_size or "
                        "source_max_length/target_max_length."
                    ) from error
                raise
        train_loss = epoch_loss / max(1, epoch_tokens)
        validation_loss = _loss_for_batches(model, validation_loader, device, amp=amp)
        elapsed = time.monotonic() - epoch_started
        tokens_per_second = epoch_tokens / max(elapsed, 1e-6)
        peak_vram = (
            torch.cuda.max_memory_allocated(device) / (1024**3)
            if device.type == "cuda"
            else 0.0
        )
        row = {
            "epoch": float(epoch),
            "train_loss": train_loss,
            "validation_loss": validation_loss,
            "tokens_per_second": tokens_per_second,
            "peak_vram_gb": peak_vram,
        }
        history.append(row)
        logger.info(
            "%s epoch=%d train_loss=%.4f val_loss=%.4f tokens/s=%.1f "
            "peak_vram=%.2f GiB device=%s",
            variant,
            epoch,
            train_loss,
            validation_loss,
            tokens_per_second,
            peak_vram,
            device,
        )
        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(device)
        if validation_loss < best_loss:
            best_loss = validation_loss
            stale_epochs = 0
            best_state = copy.deepcopy(
                {
                    name: value.detach().cpu()
                    for name, value in model.state_dict().items()
                }
            )
        else:
            stale_epochs += 1
        torch.save(
            {
                "model": model.state_dict(),
                "best_model": best_state,
                "optimizer": optimizer.state_dict(),
                "scaler": scaler.state_dict(),
                "epoch": epoch,
                "best_loss": best_loss,
                "stale_epochs": stale_epochs,
                "history": history,
                "config": model_config.to_dict(),
                "vocabulary": vocabulary.to_dict(),
                "settings": settings,
            },
            latest_path,
        )
        if bool(settings["mlflow"]):
            import mlflow

            with mlflow.start_run(run_name=f"seq2seq-{variant}", nested=True):
                mlflow.log_params({"attention": variant, **model_config.to_dict()})
                mlflow.log_metrics(row, step=epoch)
        if stale_epochs >= int(settings["early_stopping_patience"]):
            logger.info("%s: early stopping at epoch %d", variant, epoch)
            break
        if time.monotonic() - started >= max_seconds:
            logger.info("%s: time budget reached after epoch %d", variant, epoch)
            break
        if time_budget_reached:
            logger.info("%s: time budget reached during epoch %d", variant, epoch)
            break

    if best_state is not None:
        model.load_state_dict(best_state)
        torch.save(
            {
                "model": best_state,
                "config": model_config.to_dict(),
                "vocabulary": vocabulary.to_dict(),
                "settings": settings,
                "best_validation_loss": best_loss,
                "history": history,
            },
            best_path,
        )
    _write_loss_curve(history, output_dir / f"{variant}_loss.png")
    (output_dir / f"{variant}_history.json").write_text(
        json.dumps(history, indent=2), encoding="utf-8"
    )
    if device.type == "cuda":
        torch.cuda.empty_cache()
    return model, history
