"""Deterministic glossary extraction grounded in stored document pages."""

import re
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import DocumentKeyTerm, DocumentPage, GlossaryTerm

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_DEFINITION_WORDS = re.compile(r"\b(?:is|are|refers\s+to|means)\b", re.IGNORECASE)
_SOURCE_WEIGHTS = {"stored": 1.0, "ner": 0.95, "keyphrase": 0.9}


def normalize_term(term: str) -> str:
    """Normalize whitespace and case for stable term identity."""
    return " ".join(term.split()).casefold()


def split_sentences(text: str) -> list[str]:
    """Split page text while preserving the original sentence text."""
    return [
        sentence.strip() for sentence in _SENTENCE_SPLIT.split(text) if sentence.strip()
    ]


def find_evidence_sentence(
    text: str, term: str, preferred: str | None = None
) -> str | None:
    """Choose a defining sentence or the strongest exact sentence containing term."""
    sentences = split_sentences(text)
    normalized_preferred = normalize_term(preferred or "")
    escaped_term = re.escape(" ".join(term.split())).replace(r"\ ", r"\s+")
    term_pattern = re.compile(rf"(?<!\w){escaped_term}(?!\w)", re.IGNORECASE)
    containing = [sentence for sentence in sentences if term_pattern.search(sentence)]
    if normalized_preferred:
        for sentence in containing:
            if normalize_term(sentence) == normalized_preferred:
                return sentence
        for sentence in containing:
            if normalized_preferred in normalize_term(sentence):
                return sentence
    if not containing:
        return None

    def score(sentence: str) -> tuple[int, int, int]:
        is_definition = any(
            _DEFINITION_WORDS.match(sentence[match.end() :].lstrip(" \t\r\n•:-"))
            for match in term_pattern.finditer(sentence)
        )
        return (
            int(is_definition),
            min(len(sentence), 400),
            -abs(len(sentence) - 180),
        )

    return max(containing, key=score)


def regenerate_glossary(
    db: Session,
    *,
    owner_id: int,
    document_id: int,
) -> list[GlossaryTerm]:
    """Replace generated terms from stored key terms; preserve custom terms."""
    pages = list(
        db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_number)
        )
    )
    page_text = {page.page_number: page.text for page in pages}
    stored_terms = list(
        db.scalars(
            select(DocumentKeyTerm).where(DocumentKeyTerm.document_id == document_id)
        )
    )

    grouped: dict[str, list[DocumentKeyTerm]] = defaultdict(list)
    for candidate in stored_terms:
        normalized = normalize_term(candidate.term)
        if normalized and candidate.page in page_text:
            grouped[normalized].append(candidate)

    custom_keys = set(
        db.scalars(
            select(GlossaryTerm.term_key).where(
                GlossaryTerm.document_id == document_id,
                GlossaryTerm.owner_id == owner_id,
                GlossaryTerm.source == "custom",
            )
        )
    )
    db.execute(
        delete(GlossaryTerm).where(
            GlossaryTerm.document_id == document_id,
            GlossaryTerm.owner_id == owner_id,
            GlossaryTerm.source != "custom",
        )
    )

    generated: list[GlossaryTerm] = []
    for term_key, candidates in grouped.items():
        if term_key in custom_keys:
            continue
        representative = max(
            candidates,
            key=lambda candidate: (
                _SOURCE_WEIGHTS.get(candidate.source.casefold(), 0.8),
                candidate.start_offset is not None,
            ),
        )
        evidence = find_evidence_sentence(
            page_text[representative.page], representative.term
        )
        if evidence is None:
            continue

        pages_count = len({candidate.page for candidate in candidates})
        source = representative.source.casefold()
        weight = _SOURCE_WEIGHTS.get(source, 0.8)
        generated.append(
            GlossaryTerm(
                owner_id=owner_id,
                document_id=document_id,
                term=representative.term.strip(),
                term_key=term_key,
                definition=evidence,
                page=representative.page,
                evidence_sentence=evidence,
                source=source if source in _SOURCE_WEIGHTS else "stored",
                importance=weight + min(pages_count - 1, 5) * 0.05,
            )
        )

    generated.sort(key=lambda item: (-item.importance, item.term_key))
    db.add_all(generated)
    db.flush()
    return generated


def grounded_custom_term(
    *,
    term: str,
    pages: Sequence[DocumentPage],
    preferred_page: int | None = None,
) -> tuple[int, str] | None:
    """Find a source page and sentence that supports a custom term."""
    normalized_term = normalize_term(term.strip())
    ordered_pages = sorted(
        pages,
        key=lambda page: (
            page.page_number != preferred_page if preferred_page is not None else False,
            page.page_number,
        ),
    )
    for page in ordered_pages:
        sentence = find_evidence_sentence(page.text, term.strip())
        if sentence is not None:
            return page.page_number, sentence
    if not normalized_term:
        return None
    return None
