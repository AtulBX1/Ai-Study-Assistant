"""In-memory rate limiting, answer caching, and safe logging for free-tier RAG."""

import re
import threading
import time
from collections import defaultdict
from typing import Any


def normalize_question(question: str) -> str:
    """Normalize a question for cache keying: lowercased, whitespace collapsed."""
    cleaned = re.sub(r"[^\w\s]", "", question.lower())
    return " ".join(cleaned.split())


class RateLimiter:
    """Thread-safe, Redis-free sliding-window rate limiter and daily budget tracker."""

    def __init__(
        self, requests_per_minute: int = 15, requests_per_day: int = 1000
    ) -> None:
        self.requests_per_minute = requests_per_minute
        self.requests_per_day = requests_per_day
        self._minute_buckets: dict[int, list[float]] = defaultdict(list)
        self._day_buckets: dict[int, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def check_and_consume(self, user_id: int) -> tuple[bool, str | None]:
        """Check limits and record request timestamp if allowed."""
        now = time.monotonic()
        with self._lock:
            minute_window = now - 60.0
            day_window = now - 86400.0

            recent_min = [t for t in self._minute_buckets[user_id] if t > minute_window]
            self._minute_buckets[user_id] = recent_min

            recent_day = [t for t in self._day_buckets[user_id] if t > day_window]
            self._day_buckets[user_id] = recent_day

            if len(recent_min) >= self.requests_per_minute:
                return False, f"rate limit exceeded ({self.requests_per_minute}/min)"
            if len(recent_day) >= self.requests_per_day:
                return False, f"daily budget exceeded ({self.requests_per_day}/day)"

            self._minute_buckets[user_id].append(now)
            self._day_buckets[user_id].append(now)
            return True, None

    def reset(self) -> None:
        """Clear all in-memory usage records for testing."""
        with self._lock:
            self._minute_buckets.clear()
            self._day_buckets.clear()


class AnswerCache:
    """Thread-safe in-memory cache keyed by (normalized question, chunk ids, mode)."""

    def __init__(self, ttl_seconds: float = 3600.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._cache: dict[
            tuple[str, tuple[int, ...], str], tuple[dict[str, Any], float]
        ] = {}
        self._lock = threading.Lock()

    def get(
        self, question: str, chunk_ids: list[int], mode: str
    ) -> dict[str, Any] | None:
        key = (normalize_question(question), tuple(sorted(chunk_ids)), mode.lower())
        now = time.monotonic()
        with self._lock:
            item = self._cache.get(key)
            if item is None:
                return None
            data, timestamp = item
            if now - timestamp > self.ttl_seconds:
                del self._cache[key]
                return None
            return dict(data)

    def set(
        self,
        question: str,
        chunk_ids: list[int],
        mode: str,
        answer: str,
        citations: list[dict[str, Any]],
        provider: str,
        *,
        grounding_score: float | None = None,
        unsupported_sentences: list[str] | None = None,
    ) -> None:
        key = (normalize_question(question), tuple(sorted(chunk_ids)), mode.lower())
        now = time.monotonic()
        data = {
            "answer": answer,
            "citations": citations,
            "provider": provider,
            "cached": True,
            "grounding_score": grounding_score,
            "unsupported_sentences": unsupported_sentences or [],
        }
        with self._lock:
            self._cache[key] = (data, now)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


def redact_secrets(message: str, secrets: list[str | None]) -> str:
    """Scrub raw API keys or sensitive fragments from output text or log messages."""
    redacted = message
    for secret in secrets:
        if secret and len(secret) >= 4:
            redacted = redacted.replace(secret, "[REDACTED_SECRET]")
    return redacted
