"""Evidence-first, deterministic question batches from syllabus-mapped notes."""

import re
from collections import Counter
from hashlib import sha256
from threading import RLock
from typing import Any

_cache: dict[str, dict] = {}
_cache_lock = RLock()


def _sentences(text: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", text)
        if len(part.strip()) >= 35
    ]


def _difficulty(kind: str) -> str:
    if kind == "short":
        return "easy"
    if kind == "long":
        return "medium"
    return "hard"


def important_questions(
    topic: Any, mapped_chunks: list[tuple[Any, Any]], *, suggest_likely: bool = False
) -> dict:
    """Return a single deterministic batch; every note item carries a verbatim quote."""
    chunks = [
        (mapping, chunk) for mapping, chunk in mapped_chunks if chunk.text.strip()
    ]
    if not chunks:
        if suggest_likely:
            prompts = [
                "Define the central idea",
                "Describe its key components",
                "State its main purpose",
                "Explain how the main process works",
                "Discuss its benefits and limitations",
                "Apply the concept to a practical example",
            ]
            kinds = ["short", "short", "short", "long", "long", "application"]
            return {
                "topic_id": topic.id,
                "topic": topic.title,
                "status": "unverified",
                "generation": "local topic-based suggestions",
                "items": [
                    {
                        "type": kind,
                        "question": f"{prompt} in {topic.title}?",
                        "model_answer_outline": [],
                        "evidence_quote": None,
                        "label": "Not from your notes (unverified)",
                        "page": None,
                        "difficulty": _difficulty(kind),
                        "importance_rank": index + 1,
                        "importance_score": 0,
                    }
                    for index, (prompt, kind) in enumerate(
                        zip(prompts, kinds, strict=True)
                    )
                ],
            }
        return {
            "topic_id": topic.id,
            "topic": topic.title,
            "status": "no_notes",
            "message": "No notes for this topic",
            "items": [],
        }
    terms = re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", topic.title.casefold())
    ranked: list[tuple[float, int, str, Any, Any]] = []
    counts: Counter[str] = Counter()
    for _mapping, chunk in chunks:
        for term in re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", chunk.text.casefold()):
            counts[term] += 1
    for mapping, chunk in chunks:
        for sentence in _sentences(chunk.text):
            tokens = set(re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", sentence.casefold()))
            heading = bool(
                chunk.section
                and any(word in chunk.section.casefold() for word in terms)
            )
            overlap = sum(word in tokens for word in terms)
            repetition = sum(counts[word] for word in tokens)
            ranked.append(
                (
                    overlap * 3 + int(heading) * 2 + repetition / max(len(tokens), 1),
                    chunk.id,
                    sentence,
                    mapping,
                    chunk,
                )
            )
    ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
    if not ranked:
        return {
            "topic_id": topic.id,
            "topic": topic.title,
            "status": "no_notes",
            "message": "No notes for this topic",
            "items": [],
        }
    # Repeat supported evidence when fewer than six passages are available.
    chosen = [ranked[index % len(ranked)] for index in range(6)]
    kinds = ["short"] * 3 + ["long"] * 2 + ["application"]
    labels = {
        "short": "What key point do the notes make about",
        "long": "Explain in detail what the notes state about",
        "application": "How would you apply the notes' explanation of",
    }
    items = []
    for index, (kind, row) in enumerate(zip(kinds, chosen, strict=True)):
        score, _chunk_id, quote, mapping, chunk = row
        page = mapping.page_start or chunk.page_start or chunk.page
        terms_in_quote = [w for w in terms if w in quote.casefold()]
        focus = " and ".join(terms_in_quote[:2]) or topic.title
        items.append(
            {
                "type": kind,
                "question": f"{labels[kind]} {focus}?",
                "model_answer_outline": [quote],
                "evidence_quote": quote,
                "label": f"From your notes (p.{page})",
                "page": page,
                "difficulty": _difficulty(kind),
                "importance_rank": index + 1,
                "importance_score": round(score, 3),
            }
        )
    version = sha256(
        "|".join(f"{c.id}:{c.text}" for _, c in chunks).encode()
    ).hexdigest()[:16]
    key = f"{topic.id}:{version}"
    with _cache_lock:
        cached = _cache.get(key)
        if cached:
            return {**cached, "cached": True}
        result = {
            "topic_id": topic.id,
            "topic": topic.title,
            "status": "grounded",
            "batch_key": version,
            "generation": "local extractive",
            "cached": False,
            "items": items,
        }
        _cache[key] = result
    return result
