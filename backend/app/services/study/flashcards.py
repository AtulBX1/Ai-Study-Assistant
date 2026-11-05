"""Idempotent flashcard generation from accepted quizzes and grounded glossary."""

import hashlib
import re
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    Chunk,
    Document,
    DocumentPage,
    Flashcard,
    GlossaryTerm,
    Question,
    Quiz,
)
from app.services.study.glossary import find_evidence_sentence, normalize_term

_WH_QUESTION_START = re.compile(r"^\s*what\b", re.IGNORECASE)


def _fact_key(target: str, evidence: str) -> str:
    material = f"{normalize_term(target)}\x1f{normalize_term(evidence)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _question_evidence(
    page_text: str,
    *,
    preferred: str | None,
    answer: str,
) -> str | None:
    preferred_sentences = [preferred] if preferred else []
    if preferred:
        preferred_sentences.extend(
            sentence
            for sentence in re.split(r"(?<=[.!?])\s+", preferred)
            if sentence.strip()
        )
    for candidate in preferred_sentences:
        evidence = find_evidence_sentence(page_text, answer, candidate)
        if evidence is not None and normalize_term(candidate) in normalize_term(
            evidence
        ):
            return evidence
    return find_evidence_sentence(page_text, answer)


def generate_document_flashcards(
    db: Session,
    *,
    document: Document,
    owner_id: int,
    now: datetime | None = None,
) -> list[Flashcard]:
    """Create missing, page-grounded cards without duplicating an existing fact."""
    review_time = now or datetime.now(UTC)
    pages = list(
        db.scalars(select(DocumentPage).where(DocumentPage.document_id == document.id))
    )
    page_text = {page.page_number: page.text for page in pages}
    glossary_terms = list(
        db.scalars(
            select(GlossaryTerm)
            .where(
                GlossaryTerm.document_id == document.id,
                GlossaryTerm.owner_id == owner_id,
            )
            .order_by(GlossaryTerm.importance.desc(), GlossaryTerm.id)
        )
    )
    glossary_keys = {normalize_term(item.term) for item in glossary_terms}

    candidates: list[dict[str, object]] = []
    questions = db.execute(
        select(Question, Quiz, Chunk)
        .join(Quiz, Question.quiz_id == Quiz.id)
        .outerjoin(Chunk, Question.source_chunk_id == Chunk.id)
        .where(
            Quiz.owner_id == owner_id,
            or_(Quiz.source_document_id == document.id, Chunk.doc_id == document.id),
        )
    )
    for question, quiz, chunk in questions:
        options = question.options if isinstance(question.options, dict) else {}
        source_document_id = (
            options.get("document_id")
            or (chunk.doc_id if chunk is not None else None)
            or quiz.source_document_id
        )
        if source_document_id != document.id:
            continue
        prompt = question.prompt.strip()
        if question.type != "fill_in_the_blank" and not _WH_QUESTION_START.match(
            prompt
        ):
            continue
        text = page_text.get(question.page)
        answer = question.answer.strip()
        if not text or not answer:
            continue
        evidence = _question_evidence(
            text,
            preferred=options.get("evidence"),
            answer=answer,
        )
        if evidence is None:
            continue
        target = next(
            (term for term in glossary_keys if term == normalize_term(answer)),
            answer,
        )
        candidates.append(
            {
                "front": prompt,
                "back": answer,
                "source_page": question.page,
                "evidence_sentence": evidence,
                "source_chunk_id": question.source_chunk_id,
                "fact_key": _fact_key(target, evidence),
            }
        )

    for term in glossary_terms:
        text = page_text.get(term.page)
        if not text:
            continue
        evidence = find_evidence_sentence(
            text, term.term, preferred=term.evidence_sentence
        )
        if evidence is None:
            continue
        candidates.append(
            {
                "front": term.term,
                "back": evidence,
                "source_page": term.page,
                "evidence_sentence": evidence,
                "source_chunk_id": None,
                "fact_key": _fact_key(term.term, evidence),
            }
        )

    candidate_keys = {str(candidate["fact_key"]) for candidate in candidates}
    existing_keys = (
        set(
            db.scalars(
                select(Flashcard.fact_key).where(
                    Flashcard.owner_id == owner_id,
                    Flashcard.document_id == document.id,
                    Flashcard.fact_key.in_(candidate_keys),
                )
            )
        )
        if candidate_keys
        else set()
    )
    created: list[Flashcard] = []
    for candidate in candidates:
        fact_key = str(candidate["fact_key"])
        if fact_key in existing_keys:
            continue
        card = Flashcard(
            owner_id=owner_id,
            document_id=document.id,
            front=str(candidate["front"]),
            back=str(candidate["back"]),
            source_page=int(candidate["source_page"]),
            evidence_sentence=str(candidate["evidence_sentence"]),
            source_chunk_id=candidate["source_chunk_id"],
            fact_key=fact_key,
            due_at=review_time,
        )
        db.add(card)
        created.append(card)
        existing_keys.add(fact_key)
    db.flush()
    return created
