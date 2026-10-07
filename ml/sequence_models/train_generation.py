"""Train a compact document character-LSTM with truncated BPTT and compare decoding."""

import argparse
import gc
import random
import sys
from pathlib import Path

import pymupdf
import torch
from torch import nn

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for directory in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from ml.sequence_models.data import read_config
from ml.sequence_models.generation import (
    CharacterLanguageModel,
    decode_autoregressive,
    decode_teacher_forced,
    free_running_loss,
    teacher_forced_loss,
)
from ml.sequence_models.trainer import (
    set_seed,
    train_truncated_bptt_batch,
)

DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "local_4gb.yaml"
DEFAULT_PDF = PROJECT_ROOT / "data" / "real_docs" / "nlp_notes.pdf"


def _read_pdf(path: Path) -> str:
    with pymupdf.open(path) as document:
        return "\n".join(page.get_text("text") for page in document)


def train_generation(config: dict[str, object], pdf_path: Path) -> dict[str, float]:
    """Train and report teacher-forced and free-running character decoding."""
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; refusing to train on CPU.")
    if not pdf_path.is_file():
        raise FileNotFoundError(f"Document text is unavailable: {pdf_path}")
    set_seed(int(config["seed"]))
    text = _read_pdf(pdf_path)
    characters = sorted(set(text))
    if len(text) < 512 or len(characters) < 2:
        raise ValueError(
            "The PDF contains too little extracted text for language modeling."
        )
    char_to_id = {character: index for index, character in enumerate(characters)}
    encoded = torch.tensor(
        [char_to_id[character] for character in text], dtype=torch.long
    )
    device = torch.device("cuda")
    model = CharacterLanguageModel(
        len(characters),
        embedding_dim=64,
        hidden_size=int(config["generation_hidden_size"]),
    ).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.002)
    criterion = nn.CrossEntropyLoss()
    scaler = torch.amp.GradScaler("cuda", enabled=bool(config["mixed_precision"]))
    sequence_length = int(config["generation_max_seq_len"])
    batch_size = int(config["generation_batch_size"])
    chunk_length = min(32, sequence_length - 1)
    windows = [
        (encoded[start : start + sequence_length + 1])
        for start in range(0, len(encoded) - sequence_length - 1, sequence_length)
    ]
    if not windows:
        raise ValueError("No training sequences fit generation_max_seq_len.")
    last_loss = 0.0
    for epoch in range(int(config["generation_epochs"])):
        random.shuffle(windows)
        losses: list[float] = []
        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(device)
        for start in range(0, len(windows), batch_size):
            batch = torch.stack(windows[start : start + batch_size]).to(device)
            inputs, targets = batch[:, :-1], batch[:, 1:]
            try:
                loss = train_truncated_bptt_batch(
                    model,
                    inputs,
                    targets,
                    optimizer,
                    criterion,
                    chunk_length=chunk_length,
                    gradient_clip_norm=float(config["gradient_clip_norm"]),
                    mixed_precision=bool(config["mixed_precision"]),
                    scaler=scaler,
                )
            except torch.cuda.OutOfMemoryError as error:
                optimizer.zero_grad(set_to_none=True)
                torch.cuda.empty_cache()
                gc.collect()
                raise RuntimeError(
                    "CUDA ran out of memory. Reduce generation_batch_size or "
                    "generation_max_seq_len."
                ) from error
            losses.append(loss)
        last_loss = sum(losses) / len(losses)
        peak = torch.cuda.max_memory_allocated(device) / 1024**3
        print(
            f"epoch={epoch + 1} teacher_forcing_loss={last_loss:.4f} "
            f"peak_vram_gib={peak:.3f}",
            flush=True,
        )
    held_out = encoded[-min(1024, len(encoded)) :].unsqueeze(0).to(device)
    if held_out.shape[1] < 3:
        raise ValueError("Not enough held-out text for decoding comparison.")
    prefix_length = min(32, held_out.shape[1] - 1)
    tf_loss = teacher_forced_loss(model, held_out, criterion)
    free_loss = free_running_loss(model, held_out, prefix_length, criterion)
    id_to_char = characters
    prefix = text[-512:-480]
    true_continuation = text[-480:-448]
    print("Teacher-forced sample:")
    print(
        decode_teacher_forced(model, prefix, true_continuation, char_to_id, id_to_char)
    )
    print("Free-running sample:")
    print(decode_autoregressive(model, prefix, char_to_id, id_to_char, 32))
    print(f"Teacher-forcing loss: {tf_loss:.4f}")
    print(f"Free-running loss: {free_loss:.4f}")
    output_path = PROJECT_ROOT / "models" / "sequence" / "generation" / "char_lstm.pt"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state_dict": model.state_dict(),
            "char_to_id": char_to_id,
            "hidden_size": int(config["generation_hidden_size"]),
        },
        output_path,
    )
    return {"teacher_forcing_loss": tf_loss, "free_running_loss": free_loss}


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    args = parser.parse_args()
    train_generation(read_config(args.config), args.pdf)


if __name__ == "__main__":
    main()
