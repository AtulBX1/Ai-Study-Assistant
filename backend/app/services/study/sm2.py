"""Deterministic SM-2 scheduling."""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class SM2Result:
    """Updated review state after one quality rating."""

    ease: float
    interval: int
    repetitions: int
    due_at: datetime


def schedule_review(
    *,
    ease: float,
    interval: int,
    repetitions: int,
    quality: int,
    now: datetime,
) -> SM2Result:
    """Apply the SM-2 ease and interval rules for a quality from zero to five."""
    if not 0 <= quality <= 5:
        raise ValueError("quality must be between 0 and 5.")

    next_ease = max(
        1.3,
        ease + 0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02),
    )
    if quality < 3:
        next_repetitions = 0
        next_interval = 1
    elif repetitions == 0:
        next_repetitions = 1
        next_interval = 1
    elif repetitions == 1:
        next_repetitions = 2
        next_interval = 6
    else:
        next_repetitions = repetitions + 1
        next_interval = max(1, round(interval * next_ease))

    return SM2Result(
        ease=next_ease,
        interval=next_interval,
        repetitions=next_repetitions,
        due_at=now + timedelta(days=next_interval),
    )
