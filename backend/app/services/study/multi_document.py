"""Cross-document grounded Q&A and evidence-based document comparisons."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    ChatSession,
    Document,
    DocumentKeyTerm,
    DocumentPage,
    GlossaryTerm,
)
from app.services.embeddings import EmbeddingService, get_embedding_service
from app.services.rag.pipeline import RAGChatPipeline
from app.services.study.glossary import normalize_term
from app.services.study.summaries import DocumentSection, extract_sections

MAX_COMPARISON_SECTIONS = 100
MIN_SECTION_SIMILARITY = 0.6


def answer_across_documents(
    db: Session,
    *,
    pipeline: RAGChatPipeline,
    user_id: int,
    document_ids: Sequence[int],
    question: str,
    language: str = "English",
) -> dict[str, Any]:
    """Run a bounded question through the existing grounded chat pipeline."""
    session = ChatSession(owner_id=user_id, title="Cross-document question")
    db.add(session)
    db.flush()

    answer_parts: list[str] = []
    final_payload: dict[str, Any] = {}
    try:
        for event in pipeline.stream_chat(
            db=db,
            user_id=user_id,
            session_id=session.id,
            query=question,
            language=language,
            doc_ids=list(document_ids),
        ):
            if not event.startswith("data: "):
                continue
            payload = json.loads(event[6:].strip())
            token = payload.get("token")
            if isinstance(token, str):
                answer_parts.append(token)
            if payload.get("done") is True:
                final_payload = payload
    finally:
        db.delete(session)
        db.commit()

    answer = "".join(answer_parts).strip()
    if not final_payload:
        raise RuntimeError("The chat pipeline ended without a final response.")
    if answer.casefold() == "not found in the document":
        answer = "not found in the selected documents"
    if not answer:
        raise RuntimeError("The chat pipeline returned an empty answer.")

    explanation = final_payload.get("explanation", {})
    context_chunks = (
        explanation.get("chunks", []) if isinstance(explanation, dict) else []
    )
    citations_by_source: dict[tuple[str, int], dict[str, Any]] = {}
    for chunk in context_chunks:
        title = chunk.get("document_title")
        page = chunk.get("page")
        if isinstance(title, str) and isinstance(page, int):
            citations_by_source.setdefault(
                (title.casefold(), page),
                {
                    "document_title": title,
                    "page": page,
                    "chunk_id": chunk.get("chunk_id"),
                },
            )

    citations = [
        citation
        for citation in final_payload.get("citations", [])
        if isinstance(citation, dict)
        and isinstance(citation.get("document_title"), str)
        and isinstance(citation.get("page"), int)
        and (
            citation["document_title"].casefold(),
            citation["page"],
        )
        in citations_by_source
    ]
    if answer.casefold() != "not found in the selected documents" and not citations:
        citations = list(citations_by_source.values())

    allowed_sources = {
        (citation["document_title"].casefold(), citation["page"])
        for citation in citations
    }

    def retain_owned_source(match: re.Match[str]) -> str:
        title, page = match.groups()
        return (
            match.group()
            if (title.strip().casefold(), int(page)) in allowed_sources
            else ""
        )

    answer = re.sub(
        r"\[([^\]]+),\s*p\.?\s*(\d+)\]",
        retain_owned_source,
        answer,
        flags=re.IGNORECASE,
    ).strip()
    for citation in citations:
        title = citation.get("document_title")
        page = citation.get("page")
        if not isinstance(title, str) or not isinstance(page, int):
            continue
        if not has_inline_citation(answer, title, page):
            inline_citation = f"[{title}, p.{page}]"
            answer = f"{answer} {inline_citation}".strip()

    return {
        "answer": answer,
        "citations": citations,
        "grounding_score": final_payload.get("grounding_score"),
        "provider": final_payload.get("provider"),
    }


def _document_terms(db: Session, document: Document) -> dict[str, dict[str, Any]]:
    terms: dict[str, dict[str, Any]] = {}
    stored_terms = list(
        db.scalars(
            select(DocumentKeyTerm)
            .where(DocumentKeyTerm.document_id == document.id)
            .order_by(DocumentKeyTerm.page, DocumentKeyTerm.id)
        )
    )
    glossary_terms = list(
        db.scalars(
            select(GlossaryTerm)
            .where(
                GlossaryTerm.document_id == document.id,
                GlossaryTerm.owner_id == document.owner_id,
            )
            .order_by(GlossaryTerm.page, GlossaryTerm.id)
        )
    )
    for item in [*stored_terms, *glossary_terms]:
        label = " ".join(item.term.split())
        key = normalize_term(label)
        if not key:
            continue
        entry = terms.setdefault(key, {"term": label, "pages": set()})
        entry["pages"].add(item.page)
    return terms


def _sections(db: Session, document: Document) -> list[DocumentSection]:
    pages = list(
        db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == document.id)
            .order_by(DocumentPage.page_number)
        )
    )
    return extract_sections(pages)[:MAX_COMPARISON_SECTIONS]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or len(left) != len(right):
        raise ValueError("Section embeddings have incompatible dimensions.")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sum(value * value for value in left) ** 0.5
    right_norm = sum(value * value for value in right) ** 0.5
    if not left_norm or not right_norm:
        raise ValueError("Section embeddings must not be zero vectors.")
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


def _match_sections(
    sections_a: list[DocumentSection],
    sections_b: list[DocumentSection],
    embedding_service: EmbeddingService,
) -> list[dict[str, Any]]:
    if not sections_a or not sections_b:
        return []
    vectors = embedding_service.embed_texts(
        [section.text for section in [*sections_a, *sections_b]]
    )
    vectors_a = vectors[: len(sections_a)]
    vectors_b = vectors[len(sections_a) :]
    candidates = sorted(
        (
            (_cosine(vector_a, vector_b), index_a, index_b)
            for index_a, vector_a in enumerate(vectors_a)
            for index_b, vector_b in enumerate(vectors_b)
        ),
        key=lambda item: (-item[0], item[1], item[2]),
    )

    matches: list[dict[str, Any]] = []
    used_a: set[int] = set()
    used_b: set[int] = set()
    for score, index_a, index_b in candidates:
        if score < MIN_SECTION_SIMILARITY:
            break
        if index_a in used_a or index_b in used_b:
            continue
        section_a = sections_a[index_a]
        section_b = sections_b[index_b]
        matches.append(
            {
                "section_a": section_a.title,
                "page_start_a": section_a.page_start,
                "page_end_a": section_a.page_end,
                "section_b": section_b.title,
                "page_start_b": section_b.page_start,
                "page_end_b": section_b.page_end,
                "similarity": round(score, 4),
            }
        )
        used_a.add(index_a)
        used_b.add(index_b)
    return matches


def compare_documents(
    db: Session,
    *,
    document_a: Document,
    document_b: Document,
    embedding_service: EmbeddingService | None = None,
) -> dict[str, Any]:
    """Compare stored terms and section embeddings without calling an LLM."""
    terms_a = _document_terms(db, document_a)
    terms_b = _document_terms(db, document_b)
    shared_keys = sorted(terms_a.keys() & terms_b.keys())
    unique_a_keys = sorted(terms_a.keys() - terms_b.keys())
    unique_b_keys = sorted(terms_b.keys() - terms_a.keys())

    shared_terms = [
        {
            "term": terms_a[key]["term"],
            "pages_a": sorted(terms_a[key]["pages"]),
            "pages_b": sorted(terms_b[key]["pages"]),
        }
        for key in shared_keys
    ]
    unique_to_a = [
        {"term": terms_a[key]["term"], "pages": sorted(terms_a[key]["pages"])}
        for key in unique_a_keys
    ]
    unique_to_b = [
        {"term": terms_b[key]["term"], "pages": sorted(terms_b[key]["pages"])}
        for key in unique_b_keys
    ]

    if document_a.id == document_b.id:
        matched_sections: list[dict[str, Any]] = []
    else:
        matched_sections = _match_sections(
            _sections(db, document_a),
            _sections(db, document_b),
            embedding_service or get_embedding_service(),
        )

    bullets = [
        (
            f"Both cover {item['term']} "
            f"[{document_a.title}, p.{item['pages_a'][0]}; "
            f"{document_b.title}, p.{item['pages_b'][0]}]"
        )
        for item in shared_terms
        if item["pages_a"] and item["pages_b"]
    ]
    bullets.extend(
        f"Only A covers {item['term']} [{document_a.title}, p.{item['pages'][0]}]"
        for item in unique_to_a
        if item["pages"]
    )
    bullets.extend(
        f"Only B covers {item['term']} [{document_b.title}, p.{item['pages'][0]}]"
        for item in unique_to_b
        if item["pages"]
    )
    for match in matched_sections:
        bullets.append(
            f"Both cover similar sections: {match['section_a']} and "
            f"{match['section_b']} (similarity {match['similarity']:.2f}) "
            f"[{document_a.title}, pp.{match['page_start_a']}-"
            f"{match['page_end_a']}; {document_b.title}, "
            f"pp.{match['page_start_b']}-{match['page_end_b']}]"
        )

    return {
        "document_a": {"id": document_a.id, "title": document_a.title},
        "document_b": {"id": document_b.id, "title": document_b.title},
        "shared_terms": shared_terms,
        "unique_to_a": unique_to_a,
        "unique_to_b": unique_to_b,
        "matched_sections": matched_sections,
        "bullets": bullets,
    }


def has_inline_citation(answer: str, title: str, page: int) -> bool:
    """Check for a source citation while allowing spaces and an optional period."""
    pattern = re.compile(rf"\[{re.escape(title)},\s*p\.?\s*{page}\]", re.IGNORECASE)
    return pattern.search(answer) is not None
