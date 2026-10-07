"""Configuration, IMDB subsets, and reproducible inference artifact helpers."""

import json
import os
from pathlib import Path
from typing import Any

import torch
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HF_CACHE = PROJECT_ROOT / "data" / "hf_cache"
MODEL_ROOT = PROJECT_ROOT / "models" / "sequence"
HF_CACHE.mkdir(parents=True, exist_ok=True)
os.environ["HF_HOME"] = str(HF_CACHE)
os.environ["HF_HUB_CACHE"] = str(HF_CACHE / "hub")
os.environ["HF_DATASETS_CACHE"] = str(HF_CACHE / "datasets")

CLASS_NAMES = {
    "sentiment": ["negative", "positive"],
    "difficulty": ["easy", "medium", "hard"],
}


def read_config(path: Path) -> dict[str, Any]:
    """Load a YAML config and require a mapping at its root."""
    with path.open(encoding="utf-8") as stream:
        value = yaml.safe_load(stream)
    if not isinstance(value, dict):
        raise TypeError(f"Configuration at {path} must contain a YAML mapping.")
    return value


def load_imdb(
    config: dict[str, Any],
) -> tuple[
    tuple[list[str], list[int]],
    tuple[list[str], list[int]],
    tuple[list[str], list[int]],
]:
    """Load fixed, deterministic IMDB train/validation/test subsets from HF cache."""
    HF_CACHE.mkdir(parents=True, exist_ok=True)
    from datasets import load_dataset

    dataset = load_dataset("stanfordnlp/imdb", cache_dir=str(HF_CACHE / "datasets"))
    train_count = int(config["train_samples"])
    validation_count = int(config["validation_samples"])
    test_count = int(config["test_samples"])
    if train_count < 1 or validation_count < 1 or test_count < 1:
        raise ValueError("IMDB subset sizes must be positive.")
    train_split = dataset["train"].shuffle(seed=int(config["seed"]))
    test_split = dataset["test"].shuffle(seed=int(config["seed"]))
    if train_count + validation_count > len(train_split) or test_count > len(
        test_split
    ):
        raise ValueError("Requested IMDB subset exceeds the available dataset split.")
    validation = train_split.select(range(validation_count))
    training = train_split.select(
        range(validation_count, validation_count + train_count)
    )
    testing = test_split.select(range(test_count))

    def convert(split: Any) -> tuple[list[str], list[int]]:
        return list(split["text"]), [int(label) for label in split["label"]]

    return convert(training), convert(validation), convert(testing)


def save_inference_artifact(
    path: Path,
    model: torch.nn.Module,
    architecture: str,
    vocabulary: dict[str, object],
    classes: list[str],
    model_config: dict[str, Any],
    max_seq_len: int,
) -> None:
    """Save only tensor weights and primitive metadata for safe lazy inference."""
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state_dict": model.state_dict(),
            "architecture": architecture,
            "vocabulary": vocabulary,
            "classes": classes,
            "model_config": model_config,
            "max_seq_len": max_seq_len,
        },
        path,
    )


def write_json(path: Path, value: object) -> None:
    """Write stable, human-readable JSON with UTF-8 text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
