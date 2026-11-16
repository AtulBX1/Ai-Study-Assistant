"""Opt-in, bounded web search. Search receives only a short topic query."""

from datetime import date
from threading import Lock
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from app.core.config import Settings, get_settings

_lock = Lock()
_cache: dict[str, list[dict[str, str]]] = {}
_count_day = date.today()
_count = 0


class SearchAdapter(Protocol):
    """Slot for providers returning a title, URL and text snippet."""

    def search(
        self, query: str, api_key: str, timeout: float
    ) -> list[dict[str, Any]]: ...


class TavilyAdapter:
    def search(self, query: str, api_key: str, timeout: float) -> list[dict[str, Any]]:
        response = httpx.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": 5},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json().get("results", [])


def topic_query(query: str) -> str:
    """Keep only a short question topic; never accept retrieved/document text here."""
    words = query.replace("\n", " ").split()
    return " ".join(words[:8])[:120]


def search_web(
    query: str, settings: Settings | None = None, adapter: SearchAdapter | None = None
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
        if settings.web_search_provider != "tavily" and adapter is None:
            return (
                [],
                "Web search provider unavailable; continuing with your notes only.",
            )
        rows = (adapter or TavilyAdapter()).search(
            topic, settings.web_search_api_key, 5.0
        )
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


def valid_web_evidence(item: dict[str, Any], sources: list[dict[str, str]]) -> bool:
    """Require a returned URL and a verbatim quote from its fetched snippet."""
    url, quote = item.get("url"), item.get("quote")
    if not isinstance(url, str) or not isinstance(quote, str) or not quote.strip():
        return False
    return any(
        source.get("url") == url and quote.strip() in source.get("snippet", "")
        for source in sources
    )


def web_study_items(sources: list[dict[str, str]]) -> list[dict[str, str]]:
    """Build safe supplemental items whose quote is copied from its cited result."""
    items = []
    for source in sources:
        evidence = {"url": source.get("url"), "quote": source.get("snippet")}
        if not valid_web_evidence(evidence, [source]):
            continue
        items.append(
            {
                "text": (
                    "Based on web (not in your notes): "
                    f"{source['snippet']} [web: {source['domain']}]"
                ),
                "url": source["url"],
                "quote": source["snippet"],
                "title": source["title"],
                "domain": source["domain"],
            }
        )
    return items


def web_quiz_items(sources: list[dict[str, str]]) -> list[dict[str, str]]:
    """Create bounded short-answer items whose answer is the exact source quote."""
    items = []
    for source in sources:
        quote = source.get("snippet", "")
        if len(quote.split()) < 5 or not valid_web_evidence(
            {"url": source.get("url"), "quote": quote}, [source]
        ):
            continue
        items.append(
            {
                "question": (
                    f"According to {source['domain']}, what statement is reported?"
                ),
                "answer": quote,
                "url": source["url"],
                "quote": quote,
                "title": source["title"],
                "domain": source["domain"],
            }
        )
    return items
