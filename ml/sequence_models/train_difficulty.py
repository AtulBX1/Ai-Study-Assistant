"""Weak-label PDF chunks, train their difficulty classifier, and print examples."""

import argparse
import gc
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import torch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for directory in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from ml.sequence_models.classification import train_classifier
from ml.sequence_models.data import read_config, write_json
from ml.sequence_models.models import Architecture
from ml.sequence_models.trainer import set_seed
from ml.sequence_models.vocabulary import Vocabulary
from ml.sequence_models.weak_labels import (
    extract_pdf_chunks,
    save_weak_labels,
)

DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "local_4gb.yaml"
DEFAULT_PDF = PROJECT_ROOT / "data" / "real_docs" / "nlp_notes.pdf"
LABEL_IDS = {"easy": 0, "medium": 1, "hard": 2}
ARCHITECTURE: Architecture = "lstm"


def _split(
    chunks: list[dict[str, Any]], seed: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    randomizer = random.Random(seed)
    by_label = {
        label: [chunk for chunk in chunks if chunk["label"] == label]
        for label in LABEL_IDS
    }
    training: list[dict[str, Any]] = []
    validation: list[dict[str, Any]] = []
    testing: list[dict[str, Any]] = []
    for label, members in by_label.items():
        randomizer.shuffle(members)
        if len(members) < 3:
            raise ValueError(
                f"Need at least three {label!r} weak-labeled chunks to split data."
            )
        n_test = max(1, round(len(members) * 0.15))
        n_validation = max(1, round(len(members) * 0.15))
        testing.extend(members[:n_test])
        validation.extend(members[n_test : n_test + n_validation])
        training.extend(members[n_test + n_validation :])
    randomizer.shuffle(training)
    randomizer.shuffle(validation)
    randomizer.shuffle(testing)
    return training, validation, testing


def train_pdf_difficulty(
    config: dict[str, Any],
    pdf_path: Path,
    architecture: Architecture = ARCHITECTURE,
) -> dict[str, Any]:
    """Create heuristic labels from a real PDF, fit, and persist model predictions."""
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; refusing to train on CPU.")
    if not pdf_path.is_file():
        raise FileNotFoundError(f"Document PDF is unavailable: {pdf_path}")
    set_seed(int(config["seed"]))
    chunks = extract_pdf_chunks(pdf_path)
    chunks = save_weak_labels(chunks)
    if len(chunks) > int(config["difficulty_max_chunks"]):
        chunks = chunks[: int(config["difficulty_max_chunks"])]
        chunks = save_weak_labels(chunks)
    counts = Counter(chunk["label"] for chunk in chunks)
    print(f"Created {len(chunks)} weak labels: {dict(counts)}", flush=True)
    train_chunks, validation_chunks, test_chunks = _split(chunks, int(config["seed"]))
    vocabulary = Vocabulary.build(
        [chunk["text"] for chunk in train_chunks],
        min_frequency=int(config["min_frequency"]),
        max_size=int(config["vocab_size"]),
    )

    def as_dataset(items: list[dict[str, Any]]) -> tuple[list[str], list[int]]:
        return (
            [str(item["text"]) for item in items],
            [LABEL_IDS[str(item["label"])] for item in items],
        )

    result = train_classifier(
        "difficulty",
        architecture,
        as_dataset(train_chunks),
        as_dataset(validation_chunks),
        as_dataset(test_chunks),
        vocabulary,
        config,
    )
    from ml.sequence_models.inference import get_predictor

    predictor = get_predictor("difficulty", architecture)
    predictions = [predictor.predict(str(chunk["text"])) for chunk in chunks]
    for chunk, prediction in zip(chunks, predictions, strict=True):
        chunk["predicted_label"] = prediction["label"]
        chunk["predicted_confidence"] = prediction["confidence"]
    write_json(
        PROJECT_ROOT / "data" / "labels" / "difficulty_weak.json",
        {
            "source": "weak_heuristic",
            "labels_are_weak": True,
            "predictions_from": f"models/sequence/difficulty/{architecture}.pt",
            "heuristics": [
                "Flesch reading ease",
                "inverse document-frequency term rarity",
                "average sentence length",
                "technical-term suffix density",
            ],
            "chunks": chunks,
        },
    )
    print(
        f"Difficulty test accuracy={result['metrics']['accuracy']:.4f} "
        f"macro_f1={result['metrics']['macro_f1']:.4f}",
        flush=True,
    )
    for chunk in chunks[:5]:
        preview = " ".join(str(chunk["text"]).split())[:180]
        print(f"[{chunk['predicted_label']}] {preview}")
    del predictor
    gc.collect()
    torch.cuda.empty_cache()
    return result


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    args = parser.parse_args()
    train_pdf_difficulty(read_config(args.config), args.pdf)


if __name__ == "__main__":
    main()
