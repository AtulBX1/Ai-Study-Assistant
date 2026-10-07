"""Train an IMDB sentiment classifier on the verified local CUDA device."""

import argparse
import gc
import sys
from pathlib import Path
from typing import Any

import torch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for directory in (PROJECT_ROOT, PROJECT_ROOT / "backend"):
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

from ml.sequence_models.classification import train_classifier
from ml.sequence_models.data import load_imdb, read_config
from ml.sequence_models.models import Architecture
from ml.sequence_models.trainer import set_seed
from ml.sequence_models.vocabulary import Vocabulary

DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "local_4gb.yaml"


def train_sentiment_model(
    architecture: Architecture,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Download/cache the configured IMDB subset once and train one architecture."""
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is unavailable; refusing to train on CPU.")
    set_seed(int(config["seed"]))
    train, validation, test = load_imdb(config)
    vocabulary = Vocabulary.build(
        train[0],
        min_frequency=int(config["min_frequency"]),
        max_size=int(config["vocab_size"]),
    )
    return train_classifier(
        "sentiment",
        architecture,
        train,
        validation,
        test,
        vocabulary,
        config,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--architecture",
        choices=("rnn", "lstm", "gru", "bilstm"),
        default="lstm",
    )
    args = parser.parse_args()
    result = train_sentiment_model(args.architecture, read_config(args.config))
    print(
        f"{result['architecture']} accuracy={result['metrics']['accuracy']:.4f} "
        f"macro_f1={result['metrics']['macro_f1']:.4f} "
        f"peak_vram_gib={result['peak_vram_gib']:.3f}",
        flush=True,
    )
    del result
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
