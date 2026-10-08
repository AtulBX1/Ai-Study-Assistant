"""Bounded CNN/DailyMail and SQuAD question-generation examples."""

from typing import Any

from datasets import load_dataset


def load_summary_subsets(
    *,
    dataset_id: str,
    dataset_config: str,
    train_count: int,
    validation_count: int,
    test_count: int,
) -> dict[str, Any]:
    """Select deterministic leading examples from the Step 9 dataset splits."""
    loaded = load_dataset(dataset_id, dataset_config)
    counts = {
        "train": train_count,
        "validation": validation_count,
        "test": test_count,
    }
    return {
        split: loaded[split].select(range(min(count, len(loaded[split]))))
        for split, count in counts.items()
    }


def qg_text(context: str, answer: str) -> str:
    """Format SQuAD context with the highlighted answer markers."""
    if not context.strip() or not answer.strip():
        raise ValueError("Question generation requires non-empty context and answer.")
    return f"generate question: {context} <hl> {answer} <hl>"
