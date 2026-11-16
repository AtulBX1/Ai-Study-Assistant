"""Opt-in, bounded web search. Search receives only a short topic query."""

from datetime import date
from threading import Lock
from urllib.parse import urlparse

import httpx

from app.core.config import Settings, get_settings

_lock = Lock()
_cache: dict[str, list[dict[str, str]]] = {}
_count_day = date.today()
_count = 0


def topic_query(query: str) -> str:
    """Keep only a short question topic; never accept retrieved/document text here."""
    words = query.replace("\n", " ").split()
    return " ".join(words[:8])[:120]


def search_web(
    query: str, settings: Settings | None = None
) -> tuple[list[dict[str, str]], str | None]:
    global _count, _count_day
    settings = settings or get_settings()
    topic = topic_query(query)
    if not settings.web_search_api_key or settings.web_search_max_per_day <= 0:
        return [], "Web search is not configured; continuing with your notes only."
    with _lock:
        if topic in _cache:
            return list(_cache[topic]), None
        today = date.today()
        if today != _count_day:
            _count_day, _count = today, 0
        if _count >= settings.web_search_max_per_day:
            return (
                [],
                "Web search daily limit reached; continuing with your notes only.",
            )
        _count += 1
    try:
        if settings.web_search_provider != "tavily":
            return (
                [],
                "Web search provider unavailable; continuing with your notes only.",
            )
        response = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": settings.web_search_api_key,
                "query": topic,
                "max_results": 5,
            },
            timeout=5.0,
        )
        response.raise_for_status()
        rows = response.json().get("results", [])
        results = []
        for row in rows[:5]:
            url = str(row.get("url", ""))
            domain = urlparse(url).hostname or ""
            snippet = " ".join(str(row.get("content", "")).split())[:300]
            if url.startswith("https://") and domain and snippet:
                results.append(
                    {
                        "title": str(row.get("title", ""))[:200],
                        "url": url,
                        "domain": domain,
                        "snippet": snippet,
                    }
                )
        with _lock:
            _cache[topic] = results
        return results, None
    except Exception:
        return [], "Web search failed; continuing with your notes only."
