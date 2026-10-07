"""Hand-computed checks for the ranking evaluation metrics."""

import math

import pytest
from ml.eval.metrics import (
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


def test_ranking_metrics_match_hand_computed_values() -> None:
    retrieved = ["irrelevant", "relevant-a", "relevant-b"]
    relevant = {"relevant-a", "relevant-b"}

    assert precision_at_k(retrieved, relevant, 2) == 0.5
    assert recall_at_k(retrieved, relevant, 2) == 0.5
    assert mean_reciprocal_rank(retrieved, relevant) == 0.5
    assert ndcg_at_k(retrieved, relevant, 2) == pytest.approx(1 / (math.log2(3) + 1))


def test_ranking_metrics_handle_empty_relevance_and_validate_k() -> None:
    assert precision_at_k(["x"], set(), 2) == 0
    assert recall_at_k(["x"], set(), 2) == 0
    assert mean_reciprocal_rank(["x"], set()) == 0
    assert ndcg_at_k(["x"], set(), 2) == 0
    with pytest.raises(ValueError):
        precision_at_k(["x"], {"x"}, 0)
