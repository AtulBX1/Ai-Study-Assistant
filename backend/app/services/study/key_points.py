"""Section based, source grounded key points for a document."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, DocumentPage
from app.services.study.summaries import (
    DocumentSection,
    extract_sections,
    normalize_whitespace,
    split_sentences,
    summarize_t5,
)


def validate_items(
    items: list[dict[str, Any]], section: DocumentSection
) -> list[dict[str, Any]]:
    """Keep only items with verbatim evidence, deriving page from that evidence."""
    valid = []
    for item in items:
        evidence = normalize_whitespace(
            str(item.get("evidence_sentence", ""))
        ).casefold()
        page = next(
            (
                n
                for n, text in section.pages
                if evidence and evidence in normalize_whitespace(text).casefold()
            ),
            None,
        )
        if page is not None:
            valid.append({**item, "page": page})
    return valid


def generate_key_points(
    db: Session, document: Document, engine: str, provider: Any
) -> dict[str, Any]:
    pages = list(
        db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == document.id)
            .order_by(DocumentPage.page_number)
        )
    )
    sections = extract_sections(pages)
    result = []
    crux = []
    fallback = None
    engines_used: set[str] = set()
    for section in sections:
        text = section.text
        llm_items = []
        if engine == "llm" and not (
            document.is_private and getattr(provider, "is_external", False)
        ):
            prompt = "\n".join(
                [
                    "Return JSON with crux and items (kind, text, evidence_sentence).",
                    "Cover definitions and important points.",
                    "Include formulas, algorithms, and common mistakes when present.",
                    "Every evidence_sentence must be copied exactly from the source.",
                    f"SECTION: {section.title}",
                    text[:10000],
                ]
            )
            try:
                import json

                raw = json.loads(provider.generate(prompt))
                llm_items = validate_items(raw.get("items", []), section)
                crux.extend(
                    validate_items(
                        [
                            {"text": line, "evidence_sentence": line}
                            for line in raw.get("crux", [])
                        ],
                        section,
                    )
                )
            except Exception as exc:
                fallback = str(exc)[:240]
        elif engine == "llm":
            fallback = "Private document cannot be sent to an external provider."
        t5_text = None
        if engine == "t5" or (engine == "llm" and not llm_items):
            t5_text, t5_message = summarize_t5(text)
            if t5_message:
                fallback = f"{fallback}; {t5_message}" if fallback else t5_message
        if not llm_items:
            candidates = []
            for page, page_text in section.pages:
                for sentence in split_sentences(page_text):
                    if len(sentence.split()) >= 7:
                        candidates.append(
                            {
                                "kind": "important_point",
                                "text": sentence,
                                "evidence_sentence": sentence,
                                "page": page,
                            }
                        )
            if t5_text and candidates:
                summary_terms = set(re.findall(r"\w+", t5_text.casefold()))
                candidates.sort(
                    key=lambda item: len(
                        summary_terms & set(re.findall(r"\w+", item["text"].casefold()))
                    ),
                    reverse=True,
                )
                engines_used.add("t5")
            elif candidates:
                engines_used.add("extractive")
            llm_items = candidates[:3]
            if not llm_items:
                fallback = fallback or "Extractive fallback used."
        else:
            engines_used.add("llm")
        result.append(
            {
                "title": section.title,
                "page_start": section.page_start,
                "page_end": section.page_end,
                "items": llm_items,
            }
        )
    if not crux:
        crux = [item for section in result for item in section["items"][:1]][:5]
    return {
        "crux": crux[:5],
        "sections": result,
        "engine_requested": engine,
        "engine_used": (
            next(iter(engines_used)) if len(engines_used) == 1 else "hybrid"
        ),
        "fallback_reason": fallback,
    }
