"""Ranking metrics for document retrieval evaluations."""

import math
from collections.abc import Sequence
from typing import TypeVar

Item = TypeVar("Item")


def precision_at_k(retrieved: Sequence[Item], relevant: set[Item], k: int) -> float:
    """Return the fraction of the first k ranked items that are relevant."""
    _validate_k(k)
    return sum(item in relevant for item in retrieved[:k]) / k


def recall_at_k(retrieved: Sequence[Item], relevant: set[Item], k: int) -> float:
    """Return the fraction of all known relevant items found in the first k."""
    _validate_k(k)
    if not relevant:
        return 0.0
    return sum(item in relevant for item in retrieved[:k]) / len(relevant)


def mean_reciprocal_rank(retrieved: Sequence[Item], relevant: set[Item]) -> float:
    """Return the reciprocal rank of the first relevant retrieved item."""
    for rank, item in enumerate(retrieved, start=1):
        if item in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved: Sequence[Item], relevant: set[Item], k: int) -> float:
    """Return normalized discounted cumulative gain for binary relevance."""
    _validate_k(k)
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, item in enumerate(retrieved[:k], start=1)
        if item in relevant
    )
    ideal_count = min(len(relevant), k)
    if ideal_count == 0:
        return 0.0
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    return dcg / ideal_dcg


def _validate_k(k: int) -> None:
    if k < 1:
        raise ValueError("k must be at least 1.")
