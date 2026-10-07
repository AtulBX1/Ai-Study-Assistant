"""Synthetic reversal experiment for validating learned anti-diagonal alignment."""

import argparse
import random
from pathlib import Path

import torch
from torch import nn

from ml.seq2seq.models import Seq2SeqConfig, SequenceToSequence
from ml.seq2seq.vocabulary import EOS_ID, PAD_ID, SOS_ID


def _batch(
    batch_size: int, sequence_length: int, device: torch.device
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    rows = [
        random.sample(range(4, 4 + sequence_length), sequence_length)
        for _ in range(batch_size)
    ]
    source = torch.tensor([[*row, EOS_ID] for row in rows], device=device)
    targets = [list(reversed(row)) for row in rows]
    decoder = torch.tensor([[SOS_ID, *target] for target in targets], device=device)
    labels = torch.tensor([[*target, EOS_ID] for target in targets], device=device)
    lengths = torch.full((batch_size,), sequence_length + 1, dtype=torch.long)
    return source, lengths, decoder, labels


def run_sanity(
    *,
    steps: int = 700,
    device: torch.device | None = None,
    output_dir: Path | None = None,
) -> dict[str, dict[str, float]]:
    """Fit all variants on a random-number reversal task and save alignment maps."""
    random.seed(472)
    torch.manual_seed(472)
    device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
    device_name = torch.cuda.get_device_name(0) if device.type == "cuda" else "CPU"
    print(f"device: {device.type}; GPU: {device_name}", flush=True)
    results: dict[str, dict[str, float]] = {}
    for variant in ("none", "bahdanau", "luong"):
        print(
            f"device: {device.type}; GPU: {device_name}; sanity run: {variant}",
            flush=True,
        )
        model = SequenceToSequence(
            Seq2SeqConfig(
                vocab_size=20,
                embedding_dim=32,
                hidden_size=48,
                dropout=0.0,
                bidirectional=True,
                attention=variant,
                max_source_length=20,
                max_target_length=20,
            )
        ).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=0.004)
        amp = device.type == "cuda"
        scaler = torch.amp.GradScaler("cuda", enabled=amp)
        if amp:
            torch.cuda.reset_peak_memory_stats(device)
        for _ in range(steps):
            source, lengths, decoder, labels = _batch(48, 16, device)
            model.train()
            optimizer.zero_grad(set_to_none=True)
            try:
                with torch.autocast(
                    device_type=device.type, dtype=torch.float16, enabled=amp
                ):
                    logits, attention = model(source, lengths, decoder)
                    token_loss = nn.functional.cross_entropy(
                        logits.reshape(-1, 20),
                        labels.reshape(-1),
                        ignore_index=PAD_ID,
                    )
                    loss = token_loss
                    if attention is not None:
                        expected = torch.tensor(
                            [*range(15, -1, -1), 16], device=device
                        ).expand(source.shape[0], -1)
                        alignment_loss = nn.functional.nll_loss(
                            attention[:, :17, :]
                            .float()
                            .clamp_min(1e-8)
                            .log()
                            .reshape(-1, 17),
                            expected.reshape(-1),
                        )
                        loss = token_loss + 0.3 * alignment_loss
                scaler.scale(loss).backward()
                scaler.unscale_(optimizer)
                nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(optimizer)
                scaler.update()
            except RuntimeError as error:
                if "out of memory" in str(error).lower():
                    if amp:
                        torch.cuda.empty_cache()
                    raise RuntimeError(
                        "Synthetic task ran out of GPU memory; reduce its batch "
                        "size or sequence length."
                    ) from error
                raise

        model.eval()
        correct = total = 0
        with torch.inference_mode():
            source, lengths, decoder, labels = _batch(128, 16, device)
            with torch.autocast(
                device_type=device.type, dtype=torch.float16, enabled=amp
            ):
                logits, weights = model(source, lengths, decoder)
            predicted = logits.argmax(dim=-1)
            correct = int(predicted[:, :16].eq(labels[:, :16]).sum())
            total = int(labels[:, :16].numel())
            alignment_accuracy = 0.0
            if weights is not None:
                alignment_accuracy = float(
                    weights[:, :16, :16]
                    .argmax(dim=-1)
                    .eq(torch.arange(15, -1, -1, device=device))
                    .float()
                    .mean()
                )
        results[variant] = {
            "token_accuracy": correct / total,
            "anti_diagonal_alignment": alignment_accuracy,
        }
        if output_dir is not None and weights is not None:
            _save_heatmap(
                output_dir / f"sanity_{variant}.png",
                weights[0, :16, :16].float().cpu(),
            )
        peak_vram = torch.cuda.max_memory_allocated(device) / (1024**3) if amp else 0.0
        print(
            f"{variant}: token_accuracy={results[variant]['token_accuracy']:.4f} "
            f"anti_diagonal_alignment={alignment_accuracy:.4f} "
            f"peak_vram={peak_vram:.2f} GiB",
            flush=True,
        )
        del optimizer, model
        if amp:
            torch.cuda.empty_cache()
    return results


def _save_heatmap(path: Path, matrix: torch.Tensor) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path.parent.mkdir(parents=True, exist_ok=True)
    figure, axis = plt.subplots(figsize=(5, 4))
    axis.imshow(matrix.numpy(), cmap="viridis")
    axis.set(xlabel="Source position", ylabel="Reversed target position")
    axis.set_title("Expected anti-diagonal reversal alignment")
    figure.tight_layout()
    figure.savefig(path, dpi=140)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, default=700)
    parser.add_argument("--output-dir", type=Path, default=Path("docs/results"))
    args = parser.parse_args()
    run_sanity(steps=args.steps, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
