"""Rate-limit middleware tests using isolated cache instances."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.cache import MemoryCache
from app.core.config import Settings
from app.middleware import RateLimitMiddleware


def test_memory_cache_clear_and_rate_limit_reset() -> None:
    cache = MemoryCache()
    cache.set("cached-value", "value")
    cache.increment("rate:ip:testclient", 60)
    cache.clear()
    assert cache.get("cached-value") is None

    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        cache=cache,
        settings=Settings(
            _env_file=None,
            rate_limit_ip_per_minute=1,
            rate_limit_user_per_minute=1,
        ),
    )

    @app.get("/")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/").status_code == 429
        cache.clear()
        assert client.get("/").status_code == 200
