"""CNN/DailyMail subset loading and padded seq2seq batches."""

import os
from collections.abc import Sequence
from pathlib import Path

import torch
from torch.utils.data import Dataset

from ml.seq2seq.vocabulary import EOS_ID, PAD_ID, Seq2SeqVocabulary


def load_cnn_dailymail(
    cache_dir: Path,
    *,
    train_samples: int = 20_000,
    validation_samples: int = 1_000,
    test_samples: int = 1_000,
    dataset_id: str = "abisee/cnn_dailymail",
    dataset_config: str = "3.0.0",
) -> dict[str, list[dict[str, str]]]:
    """Load one bounded split subset from the explicitly qualified Hub dataset."""
    cache_dir = cache_dir.resolve()
    os.environ["HF_HOME"] = str(cache_dir)
    os.environ["HF_HUB_CACHE"] = str(cache_dir / "hub")
    os.environ["HF_DATASETS_CACHE"] = str(cache_dir / "datasets")
    from datasets import load_dataset

    if min(train_samples, validation_samples, test_samples) < 1:
        raise ValueError("Every dataset subset size must be positive.")
    cache_dir.mkdir(parents=True, exist_ok=True)
    loaded = load_dataset(dataset_id, dataset_config, cache_dir=str(cache_dir))
    requested = {
        "train": train_samples,
        "validation": validation_samples,
        "test": test_samples,
    }
    subsets: dict[str, list[dict[str, str]]] = {}
    for split, count in requested.items():
        dataset = loaded[split]
        subsets[split] = [
            {"article": row["article"], "highlights": row["highlights"]}
            for row in dataset.select(range(min(count, len(dataset))))
        ]
    return subsets


class SummaryDataset(Dataset[tuple[list[int], list[int]]]):
    """Pre-encoded article/summary pairs with EOS and teacher-forcing boundaries."""

    def __init__(
        self,
        examples: Sequence[dict[str, str]],
        vocabulary: Seq2SeqVocabulary,
        source_max_length: int,
        target_max_length: int,
    ) -> None:
        if source_max_length < 2 or target_max_length < 3:
            raise ValueError(
                "Source/target limits leave no room for EOS and boundaries."
            )
        self.pairs: list[tuple[list[int], list[int]]] = []
        for example in examples:
            source = vocabulary.encode(example["article"], source_max_length - 1)[
                : source_max_length - 1
            ]
            source.append(EOS_ID)
            target = vocabulary.encode(
                example["highlights"],
                target_max_length - 2,
                add_boundaries=True,
            )
            self.pairs.append((source, target))

    def __len__(self) -> int:
        return len(self.pairs)

    def __getitem__(self, index: int) -> tuple[list[int], list[int]]:
        return self.pairs[index]


def collate_summaries(
    examples: Sequence[tuple[list[int], list[int]]],
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
    if not examples:
        raise ValueError("Cannot collate an empty batch.")
    source_sequences, target_sequences = zip(*examples, strict=True)
    source_lengths = torch.tensor(
        [len(item) for item in source_sequences], dtype=torch.long
    )
    source = torch.nn.utils.rnn.pad_sequence(
        [torch.tensor(item, dtype=torch.long) for item in source_sequences],
        batch_first=True,
        padding_value=PAD_ID,
    )
    target = torch.nn.utils.rnn.pad_sequence(
        [torch.tensor(item, dtype=torch.long) for item in target_sequences],
        batch_first=True,
        padding_value=PAD_ID,
    )
    return source, source_lengths, target[:, :-1], target[:, 1:]
