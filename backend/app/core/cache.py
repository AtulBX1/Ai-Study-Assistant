"""Cache interface and development/production rate-limit adapters."""

from threading import Lock
from time import monotonic
from typing import Protocol

from redis import Redis

from app.core.config import Settings, get_settings


class Cache(Protocol):
    """Shared counter and string-value cache used by throttling and embeddings."""

    def increment(self, key: str, window_seconds: int) -> int:
        """Increment a counter that expires after the given window."""

    def get(self, key: str) -> str | None:
        """Return a cached string value when it has not expired."""

    def set(self, key: str, value: str, expires_seconds: int | None = None) -> None:
        """Store a string value, optionally with an expiry."""


class MemoryCache:
    """Thread-safe counters and values for local development."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[str, tuple[int, float]] = {}
        self._values: dict[str, tuple[str, float | None]] = {}

    def increment(self, key: str, window_seconds: int) -> int:
        deadline = monotonic() + window_seconds
        with self._lock:
            count, expires_at = self._counters.get(key, (0, 0.0))
            if expires_at <= monotonic():
                count = 0
            count += 1
            self._counters[key] = (count, deadline if count == 1 else expires_at)
            return count

    def get(self, key: str) -> str | None:
        with self._lock:
            cached = self._values.get(key)
            if cached is None:
                return None
            value, expires_at = cached
            if expires_at is not None and expires_at <= monotonic():
                del self._values[key]
                return None
            return value

    def set(self, key: str, value: str, expires_seconds: int | None = None) -> None:
        expires_at = (
            monotonic() + expires_seconds if expires_seconds is not None else None
        )
        with self._lock:
            self._values[key] = (value, expires_at)


class RedisCache:
    """Redis-backed atomic fixed-window counters for production."""

    def __init__(self, redis_url: str) -> None:
        self._client: Redis = Redis.from_url(redis_url, decode_responses=True)

    def increment(self, key: str, window_seconds: int) -> int:
        script = """
        local count = redis.call('INCR', KEYS[1])
        if count == 1 then
            redis.call('EXPIRE', KEYS[1], ARGV[1])
        end
        return count
        """
        return int(self._client.eval(script, 1, key, window_seconds))

    def get(self, key: str) -> str | None:
        value = self._client.get(key)
        return str(value) if value is not None else None

    def set(self, key: str, value: str, expires_seconds: int | None = None) -> None:
        self._client.set(key, value, ex=expires_seconds)


def create_cache(settings: Settings | None = None) -> Cache:
    """Choose an in-memory cache locally and Redis in production."""
    config = settings or get_settings()
    if config.backend == "prod":
        return RedisCache(config.redis_url)
    return MemoryCache()
