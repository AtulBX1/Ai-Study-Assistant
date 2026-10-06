"""Cache interface and development/production rate-limit adapters."""

from threading import Lock
from time import monotonic
from typing import Protocol

from redis import Redis

from app.core.config import Settings, get_settings


class Cache(Protocol):
    """Minimal atomic counter interface used by request throttling."""

    def increment(self, key: str, window_seconds: int) -> int:
        """Increment a counter that expires after the given window."""


class MemoryCache:
    """Thread-safe fixed-window cache for local development."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[str, tuple[int, float]] = {}

    def increment(self, key: str, window_seconds: int) -> int:
        deadline = monotonic() + window_seconds
        with self._lock:
            count, expires_at = self._counters.get(key, (0, 0.0))
            if expires_at <= monotonic():
                count = 0
            count += 1
            self._counters[key] = (count, deadline if count == 1 else expires_at)
            return count


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


def create_cache(settings: Settings | None = None) -> Cache:
    """Choose an in-memory cache locally and Redis in production."""
    config = settings or get_settings()
    if config.backend == "prod":
        return RedisCache(config.redis_url)
    return MemoryCache()
