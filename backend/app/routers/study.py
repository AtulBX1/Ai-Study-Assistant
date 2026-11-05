"""Authenticated, owner-scoped flashcard and grounded glossary endpoints."""

from datetime import UTC, datetime, time, timedelta
from enum import StrEnum
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.dependencies.auth import DatabaseSession, get_current_user
from app.models import (
    Document,
    DocumentPage,
    Flashcard,
    FlashcardReviewLog,
    GlossaryTerm,
    User,
)
from app.services.study.flashcards import generate_document_flashcards
from app.services.study.glossary import (
    grounded_custom_term,
    normalize_term,
    regenerate_glossary,
)
from app.services.study.sm2 import schedule_review

router = APIRouter(prefix="/study", tags=["study"])
AuthenticatedUser = Annotated[User, Depends(get_current_user)]


class ReviewRating(StrEnum):
    AGAIN = "Again"
    HARD = "Hard"
    GOOD = "Good"
    EASY = "Easy"


_QUALITY_BY_RATING = {
    ReviewRating.AGAIN: 0,
    ReviewRating.HARD: 3,
    ReviewRating.GOOD: 4,
    ReviewRating.EASY: 5,
}


class ReviewRequest(BaseModel):
    rating: ReviewRating


class SuspendRequest(BaseModel):
    suspended: bool


class GlossaryTermRequest(BaseModel):
    term: str = Field(min_length=1, max_length=255)
    page: int | None = Field(default=None, ge=1)


def _owned_document(db: Session, document_id: int, owner_id: int) -> Document:
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.owner_id == owner_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


def _owned_card(db: Session, card_id: int, owner_id: int) -> Flashcard:
    card = db.scalar(
        select(Flashcard).where(
            Flashcard.id == card_id,
            Flashcard.owner_id == owner_id,
        )
    )
    if card is None:
        raise HTTPException(status_code=404, detail="Flashcard not found.")
    return card


def _card_payload(card: Flashcard, deck: str | None = None) -> dict[str, Any]:
    return {
        "id": card.id,
        "front": card.front,
        "back": card.back,
        "source_page": card.source_page,
        "evidence_sentence": card.evidence_sentence,
        "deck": deck,
        "document_id": card.document_id,
        "due_at": card.due_at,
        "ease": card.ease,
        "interval": card.interval,
        "repetitions": card.repetitions,
        "suspended": card.suspended,
    }


def _glossary_payload(term: GlossaryTerm) -> dict[str, Any]:
    return {
        "id": term.id,
        "term": term.term,
        "definition": term.definition,
        "page": term.page,
        "evidence_sentence": term.evidence_sentence,
        "source": term.source,
        "importance": term.importance,
    }


def _ground_custom_term(
    db: Session,
    *,
    document_id: int,
    term: str,
    preferred_page: int | None,
) -> tuple[int, str]:
    pages = list(
        db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_number)
        )
    )
    grounded = grounded_custom_term(
        term=term,
        pages=pages,
        preferred_page=preferred_page,
    )
    if grounded is None:
        raise HTTPException(
            status_code=422,
            detail="The term does not appear in the document's stored page text.",
        )
    return grounded


@router.post("/documents/{document_id}/flashcards/generate", status_code=201)
def generate_flashcards(
    document_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Create missing cards from accepted questions and the stored glossary."""
    document = _owned_document(db, document_id, user.id)
    created = generate_document_flashcards(
        db,
        document=document,
        owner_id=user.id,
    )
    db.commit()
    return {
        "document_id": document.id,
        "deck": document.title,
        "created": len(created),
        "cards": [_card_payload(card, document.title) for card in created],
    }


@router.get("/flashcards/due")
def list_due_flashcards(
    db: DatabaseSession,
    user: AuthenticatedUser,
    document_id: Annotated[int | None, Query(gt=0)] = None,
) -> list[dict[str, Any]]:
    """List only the authenticated user's unsuspended cards due by UTC midnight."""
    if document_id is not None:
        _owned_document(db, document_id, user.id)
    now = datetime.now(UTC)
    tomorrow = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=UTC)
    query = (
        select(Flashcard, Document.title)
        .outerjoin(Document, Flashcard.document_id == Document.id)
        .where(
            Flashcard.owner_id == user.id,
            Flashcard.suspended.is_(False),
            Flashcard.due_at < tomorrow,
        )
        .order_by(Flashcard.due_at, Flashcard.id)
    )
    if document_id is not None:
        query = query.where(Flashcard.document_id == document_id)
    return [_card_payload(card, deck) for card, deck in db.execute(query)]


@router.get("/flashcards/upcoming")
def upcoming_flashcard_counts(
    db: DatabaseSession,
    user: AuthenticatedUser,
    days: Annotated[int, Query(ge=1, le=30)] = 7,
    document_id: Annotated[int | None, Query(gt=0)] = None,
) -> dict[str, Any]:
    """Count unsuspended cards by UTC due date over the next bounded number of days."""
    if document_id is not None:
        _owned_document(db, document_id, user.id)
    today = datetime.now(UTC).date()
    counts = []
    for offset in range(1, days + 1):
        day = today + timedelta(days=offset)
        start = datetime.combine(day, time.min, tzinfo=UTC)
        end = start + timedelta(days=1)
        query = select(func.count(Flashcard.id)).where(
            Flashcard.owner_id == user.id,
            Flashcard.suspended.is_(False),
            Flashcard.due_at >= start,
            Flashcard.due_at < end,
        )
        if document_id is not None:
            query = query.where(Flashcard.document_id == document_id)
        counts.append({"date": day.isoformat(), "count": db.scalar(query) or 0})
    return {"days": counts}


@router.post("/flashcards/{card_id}/review")
def review_flashcard(
    card_id: int,
    request: ReviewRequest,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Schedule an owner-scoped card using its Again/Hard/Good/Easy rating."""
    card = _owned_card(db, card_id, user.id)
    now = datetime.now(UTC)
    quality = _QUALITY_BY_RATING[request.rating]
    result = schedule_review(
        ease=card.ease,
        interval=card.interval,
        repetitions=card.repetitions,
        quality=quality,
        now=now,
    )
    card.ease = result.ease
    card.interval = result.interval
    card.repetitions = result.repetitions
    card.due_at = result.due_at
    card.last_reviewed_at = now
    db.add(
        FlashcardReviewLog(
            flashcard_id=card.id,
            owner_id=user.id,
            rating=request.rating.value,
            quality=quality,
            reviewed_at=now,
            interval=card.interval,
            ease=card.ease,
            repetitions=card.repetitions,
        )
    )
    db.commit()
    document = (
        db.get(Document, card.document_id) if card.document_id is not None else None
    )
    return {
        "card": _card_payload(card, document.title if document is not None else None),
        "rating": request.rating.value,
        "quality": quality,
    }


@router.patch("/flashcards/{card_id}")
def set_flashcard_suspended(
    card_id: int,
    request: SuspendRequest,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Suspend or resume an owner's flashcard."""
    card = _owned_card(db, card_id, user.id)
    card.suspended = request.suspended
    db.commit()
    deck = (
        db.scalar(select(Document.title).where(Document.id == card.document_id))
        if card.document_id is not None
        else None
    )
    return _card_payload(card, deck)


@router.delete("/flashcards/{card_id}", status_code=204)
def delete_flashcard(
    card_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> Response:
    """Delete an owner-scoped flashcard and its review history."""
    card = _owned_card(db, card_id, user.id)
    db.delete(card)
    db.commit()
    return Response(status_code=204)


@router.get("/documents/{document_id}/flashcards/stats")
def flashcard_deck_stats(
    document_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Return card, due, suspended, and review counts for one owned document."""
    document = _owned_document(db, document_id, user.id)
    tomorrow = datetime.combine(
        datetime.now(UTC).date() + timedelta(days=1), time.min, tzinfo=UTC
    )
    base = (
        Flashcard.owner_id == user.id,
        Flashcard.document_id == document.id,
    )
    total = db.scalar(select(func.count(Flashcard.id)).where(*base)) or 0
    suspended = (
        db.scalar(
            select(func.count(Flashcard.id)).where(
                *base,
                Flashcard.suspended.is_(True),
            )
        )
        or 0
    )
    due = (
        db.scalar(
            select(func.count(Flashcard.id)).where(
                *base,
                Flashcard.suspended.is_(False),
                Flashcard.due_at < tomorrow,
            )
        )
        or 0
    )
    reviews = (
        db.scalar(
            select(func.count(FlashcardReviewLog.id))
            .join(Flashcard, Flashcard.id == FlashcardReviewLog.flashcard_id)
            .where(*base, FlashcardReviewLog.owner_id == user.id)
        )
        or 0
    )
    return {
        "document_id": document.id,
        "deck": document.title,
        "total": total,
        "due": due,
        "suspended": suspended,
        "reviews": reviews,
    }


@router.get("/documents/{document_id}/glossary")
def list_glossary_terms(
    document_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
    search: Annotated[str | None, Query(max_length=255)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """Return a searchable, paginated glossary for an owned document."""
    _owned_document(db, document_id, user.id)
    query = select(GlossaryTerm).where(
        GlossaryTerm.document_id == document_id,
        GlossaryTerm.owner_id == user.id,
    )
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(
            or_(
                GlossaryTerm.term.ilike(pattern),
                GlossaryTerm.definition.ilike(pattern),
            )
        )
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    terms = list(
        db.scalars(
            query.order_by(GlossaryTerm.importance.desc(), GlossaryTerm.term_key)
            .offset(offset)
            .limit(limit)
        )
    )
    return {
        "items": [_glossary_payload(term) for term in terms],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/documents/{document_id}/glossary/regenerate")
def regenerate_document_glossary(
    document_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Regenerate glossary entries from persisted key terms without an LLM."""
    _owned_document(db, document_id, user.id)
    terms = regenerate_glossary(db, owner_id=user.id, document_id=document_id)
    db.commit()
    return {
        "document_id": document_id,
        "generated": len(terms),
        "items": [_glossary_payload(term) for term in terms],
    }


@router.post("/documents/{document_id}/glossary", status_code=201)
def add_custom_glossary_term(
    document_id: int,
    request: GlossaryTermRequest,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Add a custom term only when its supporting sentence exists in the document."""
    _owned_document(db, document_id, user.id)
    term = request.term.strip()
    term_key = normalize_term(term)
    if not term_key:
        raise HTTPException(status_code=422, detail="Term must not be blank.")
    page, evidence = _ground_custom_term(
        db,
        document_id=document_id,
        term=term,
        preferred_page=request.page,
    )
    existing = db.scalar(
        select(GlossaryTerm).where(
            GlossaryTerm.document_id == document_id,
            GlossaryTerm.owner_id == user.id,
            GlossaryTerm.term_key == term_key,
        )
    )
    if existing is not None and existing.source == "custom":
        raise HTTPException(status_code=409, detail="Custom term already exists.")
    if existing is None:
        existing = GlossaryTerm(
            owner_id=user.id,
            document_id=document_id,
            term=term,
            term_key=term_key,
            definition=evidence,
            page=page,
            evidence_sentence=evidence,
            source="custom",
            importance=1.0,
        )
        db.add(existing)
    else:
        existing.term = term
        existing.term_key = term_key
        existing.definition = evidence
        existing.page = page
        existing.evidence_sentence = evidence
        existing.source = "custom"
        existing.importance = 1.0
    db.commit()
    db.refresh(existing)
    return _glossary_payload(existing)


@router.patch("/glossary/{term_id}")
def edit_custom_glossary_term(
    term_id: int,
    request: GlossaryTermRequest,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Rename an owner's custom term and refresh its grounded definition."""
    term = db.scalar(
        select(GlossaryTerm).where(
            GlossaryTerm.id == term_id,
            GlossaryTerm.owner_id == user.id,
        )
    )
    if term is None:
        raise HTTPException(status_code=404, detail="Glossary term not found.")
    if term.source != "custom":
        raise HTTPException(status_code=409, detail="Only custom terms can be edited.")
    new_term = request.term.strip()
    term_key = normalize_term(new_term)
    if not term_key:
        raise HTTPException(status_code=422, detail="Term must not be blank.")
    duplicate = db.scalar(
        select(GlossaryTerm.id).where(
            GlossaryTerm.owner_id == user.id,
            GlossaryTerm.document_id == term.document_id,
            GlossaryTerm.term_key == term_key,
            GlossaryTerm.id != term.id,
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Glossary term already exists.")
    page, evidence = _ground_custom_term(
        db,
        document_id=term.document_id,
        term=new_term,
        preferred_page=request.page,
    )
    term.term = new_term
    term.term_key = term_key
    term.definition = evidence
    term.page = page
    term.evidence_sentence = evidence
    db.commit()
    db.refresh(term)
    return _glossary_payload(term)
