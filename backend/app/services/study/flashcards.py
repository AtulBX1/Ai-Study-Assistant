"""Grounded document flashcards from glossaries, cloze facts, and optional AI."""

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    AttemptAnswer,
    Chunk,
    Document,
    DocumentPage,
    Flashcard,
    GlossaryTerm,
    Question,
    Quiz,
    QuizAttempt,
)
from app.services.quiz.generation import clean_chunk_text, extract_json_value
from app.services.quiz.validation import has_symbols_or_clutter, is_short_noun_phrase
from app.services.rag.providers import (
    ProviderError,
    ProviderUnavailableError,
    RateLimitError,
)
from app.services.study.glossary import (
    find_evidence_sentence,
    normalize_term,
    split_sentences,
)

_CLOZE_TOKEN = "_____"
_MAX_CARDS = 40


@dataclass(frozen=True)
class _Candidate:
    front: str
    back: str
    source_type: str
    page: int
    evidence: str
    chunk_id: int | None = None


def _fact_key(front: str, back: str, evidence: str) -> str:
    material = "\x1f".join(normalize_term(value) for value in (front, back, evidence))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _in_scope(page: int, *, page_start: int | None, page_end: int | None) -> bool:
    return (page_start is None or page >= page_start) and (
        page_end is None or page <= page_end
    )


def _ai_candidates(
    *,
    provider: Any,
    text: str,
    page_text: str,
    page: int,
    chunk_id: int,
    count: int,
) -> tuple[list[_Candidate], str | None]:
    source = clean_chunk_text(text)
    prompt = (
        "Create up to "
        f"{count} concise document flashcards as a JSON array. Each object must "
        'contain "question", "answer", and "evidence". Use only this source. '
        "Evidence must be an exact complete sentence from the source; answers "
        "must be a term or noun phrase of 1-5 words. Return JSON only.\n"
        f"Source:\n{source}"
    )
    try:
        raw = provider.generate(
            prompt,
            system_prompt=(
                "Use only the supplied document text and quote evidence exactly."
            ),
        )
        values = extract_json_value(str(raw))
        if isinstance(values, dict):
            values = [values]
        if not isinstance(values, list):
            return [], "ai_invalid_response"
    except (ValueError, TypeError, KeyError):
        return [], "ai_invalid_response"

    sentences = {" ".join(sentence.split()) for sentence in split_sentences(source)}
    page_sentences = {
        " ".join(clean_chunk_text(sentence).split()): sentence
        for sentence in split_sentences(page_text)
    }
    candidates: list[_Candidate] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        question = str(value.get("question", "")).strip()
        answer = str(value.get("answer", "")).strip()
        evidence = str(value.get("evidence", "")).strip()
        if (
            not question
            or not answer
            or " ".join(evidence.split()) not in sentences
            or " ".join(evidence.split()) not in page_sentences
            or not is_short_noun_phrase(answer)
            or has_symbols_or_clutter(question)
            or has_symbols_or_clutter(answer)
        ):
            continue
        candidates.append(
            _Candidate(
                front=question,
                back=answer,
                source_type="ai",
                page=page,
                evidence=page_sentences[" ".join(evidence.split())],
                chunk_id=chunk_id,
            )
        )
        if len(candidates) >= count:
            break
    return candidates, None if candidates else "ai_no_supported_cards"


def generate_document_flashcards(
    db: Session,
    *,
    document: Document,
    owner_id: int,
    count: int = _MAX_CARDS,
    page_start: int | None = None,
    page_end: int | None = None,
    also_add_wrong_answers: bool = False,
    provider: Any | None = None,
    now: datetime | None = None,
) -> tuple[list[Flashcard], dict[str, Any]]:
    """Create unique, page-grounded cards without requiring a quiz."""
    count = min(count, _MAX_CARDS)
    if page_start is not None and page_end is not None and page_end < page_start:
        raise ValueError("page_end must be at least page_start.")

    pages = list(
        db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == document.id)
            .order_by(DocumentPage.page_number)
        )
    )
    scoped_pages = [
        page
        for page in pages
        if _in_scope(page.page_number, page_start=page_start, page_end=page_end)
    ]
    page_text = {page.page_number: page.text for page in scoped_pages}
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
    if not glossary_terms:
        from app.services.study.glossary import regenerate_glossary

        regenerate_glossary(db, owner_id=owner_id, document_id=document.id)
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
    scoped_terms = [
        term
        for term in glossary_terms
        if term.page in page_text
        and _in_scope(term.page, page_start=page_start, page_end=page_end)
    ]

    candidates: list[_Candidate] = []
    for term in scoped_terms:
        if has_symbols_or_clutter(term.term) or has_symbols_or_clutter(term.definition):
            continue
        evidence = find_evidence_sentence(
            page_text[term.page], term.term, preferred=term.evidence_sentence
        )
        if evidence is None:
            continue
        candidates.append(
            _Candidate(
                front=term.term,
                back=term.definition or evidence,
                source_type="glossary",
                page=term.page,
                evidence=evidence,
            )
        )

    for term in scoped_terms:
        if has_symbols_or_clutter(term.term):
            continue
        evidence = find_evidence_sentence(
            page_text[term.page], term.term, preferred=term.evidence_sentence
        )
        if evidence is None or not re.search(
            rf"(?<!\w){re.escape(term.term)}(?!\w)", evidence, re.IGNORECASE
        ):
            continue
        cloze = re.sub(
            rf"(?<!\w){re.escape(term.term)}(?!\w)",
            _CLOZE_TOKEN,
            clean_chunk_text(evidence),
            count=1,
            flags=re.IGNORECASE,
        )
        candidates.append(
            _Candidate(
                front=cloze,
                back=term.term,
                source_type="cloze",
                page=term.page,
                evidence=evidence,
            )
        )

    shortfall_reasons: Counter[str] = Counter()
    if document.is_private:
        shortfall_reasons["private_document_ai_skipped"] += 1
    elif provider is None:
        shortfall_reasons["ai_provider_unavailable"] += 1
    else:
        chunks = list(
            db.scalars(
                select(Chunk)
                .where(Chunk.doc_id == document.id)
                .order_by(Chunk.chunk_index)
            )
        )
        ai_remaining = max(0, count - len(candidates))
        for chunk in chunks:
            if ai_remaining <= 0:
                break
            if (
                page_start is not None
                and chunk.page_end < page_start
                or page_end is not None
                and chunk.page_start > page_end
            ):
                continue
            page = min(
                max(chunk.page, page_start or chunk.page),
                page_end or chunk.page,
            )
            try:
                generated, reason = _ai_candidates(
                    provider=provider,
                    text=chunk.text,
                    page_text=page_text.get(page, ""),
                    page=page,
                    chunk_id=chunk.id,
                    count=ai_remaining,
                )
            except (
                ProviderError,
                ProviderUnavailableError,
                RateLimitError,
                OSError,
                RuntimeError,
                TypeError,
                ValueError,
            ):
                shortfall_reasons["ai_generation_failed"] += 1
                continue
            candidates.extend(generated)
            ai_remaining -= len(generated)
            if reason:
                shortfall_reasons[reason] += 1

    if also_add_wrong_answers and count > len(candidates):
        wrong_answers = db.execute(
            select(Question, Quiz, Chunk)
            .join(Quiz, Question.quiz_id == Quiz.id)
            .join(QuizAttempt, QuizAttempt.quiz_id == Quiz.id)
            .join(AttemptAnswer, AttemptAnswer.attempt_id == QuizAttempt.id)
            .outerjoin(Chunk, Question.source_chunk_id == Chunk.id)
            .where(
                Quiz.owner_id == owner_id,
                QuizAttempt.user_id == owner_id,
                AttemptAnswer.question_id == Question.id,
                AttemptAnswer.is_correct.is_(False),
                or_(
                    Quiz.source_document_id == document.id,
                    Chunk.doc_id == document.id,
                ),
            )
        )
        for question, quiz, chunk in wrong_answers:
            source_document_id = (
                chunk.doc_id if chunk is not None else None
            ) or quiz.source_document_id
            if source_document_id != document.id or question.page not in page_text:
                continue
            evidence = find_evidence_sentence(
                page_text[question.page],
                question.answer,
                preferred=(
                    question.options.get("evidence")
                    if isinstance(question.options, dict)
                    else None
                ),
            )
            if evidence:
                candidates.append(
                    _Candidate(
                        front=question.prompt,
                        back=question.answer,
                        source_type="wrong_answer",
                        page=question.page,
                        evidence=evidence,
                        chunk_id=question.source_chunk_id,
                    )
                )

    unique_candidates: list[_Candidate] = []
    candidate_keys: set[str] = set()
    for candidate in candidates:
        key = _fact_key(candidate.front, candidate.back, candidate.evidence)
        if key in candidate_keys:
            shortfall_reasons["duplicate_candidates"] += 1
            continue
        candidate_keys.add(key)
        unique_candidates.append(candidate)

    existing_cards = list(
        db.scalars(
            select(Flashcard).where(
                Flashcard.owner_id == owner_id,
                Flashcard.document_id == document.id,
            )
        )
    )
    existing_keys = {card.fact_key for card in existing_cards if card.fact_key}
    existing_keys.update(
        _fact_key(card.front, card.back, card.evidence_sentence or "")
        for card in existing_cards
    )
    created: list[Flashcard] = []
    source_counts: Counter[str] = Counter()
    review_time = now or datetime.now(UTC)
    for candidate in unique_candidates:
        key = _fact_key(candidate.front, candidate.back, candidate.evidence)
        if key in existing_keys:
            shortfall_reasons["already_exists"] += 1
            continue
        if len(created) >= count:
            break
        card = Flashcard(
            owner_id=owner_id,
            document_id=document.id,
            front=candidate.front,
            back=candidate.back,
            source_type=candidate.source_type,
            source_page=candidate.page,
            evidence_sentence=candidate.evidence,
            source_chunk_id=candidate.chunk_id,
            fact_key=key,
            due_at=review_time,
        )
        db.add(card)
        created.append(card)
        source_counts[candidate.source_type] += 1
        existing_keys.add(key)
    db.flush()

    if not scoped_pages:
        shortfall_reasons["scope_has_no_pages"] += 1
    if len(created) < count:
        shortfall_reasons["insufficient_grounded_facts"] += count - len(created)
    report = {
        "requested": count,
        "created": len(created),
        "created_by_source": {
            source: source_counts[source]
            for source in ("glossary", "cloze", "ai", "wrong_answer")
        },
        "shortfall_reasons": dict(shortfall_reasons.most_common(5)),
    }
    return created, report
