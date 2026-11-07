"""Authenticated, owner-scoped flashcard and grounded glossary endpoints."""

import json
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Response,
)
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.dependencies.auth import DatabaseSession, get_current_user
from app.models import (
    Document,
    DocumentPage,
    DocumentSummary,
    Flashcard,
    FlashcardReviewLog,
    GlossaryTerm,
    StudyPlan,
    StudyPlanItem,
    User,
)
from app.routers.chat import get_rag_pipeline
from app.services.job_queue import JobQueue, create_job_queue
from app.services.rag.pipeline import RAGChatPipeline
from app.services.rag.providers import ProviderError, ProviderUnavailableError
from app.services.study.concept_graph import (
    build_concept_graph,
    get_graph_node_detail,
    graph_definitions,
)
from app.services.study.exports import content_disposition, generate_export
from app.services.study.flashcards import generate_document_flashcards
from app.services.study.glossary import (
    grounded_custom_term,
    normalize_term,
    regenerate_glossary,
)
from app.services.study.multi_document import (
    answer_across_documents,
    compare_documents,
)
from app.services.study.notes import generate_chapter_notes, generate_cheat_sheet
from app.services.study.planner import (
    MAX_PLAN_DOCUMENTS,
    collect_study_topics,
    generate_study_plan,
)
from app.services.study.sm2 import schedule_review
from app.services.study.summaries import (
    generate_document_summary,
    get_summary_job_status,
    start_summary_job,
)

router = APIRouter(prefix="/study", tags=["study"])
export_router = APIRouter(tags=["exports"])
AuthenticatedUser = Annotated[User, Depends(get_current_user)]
RAGPipeline = Annotated[RAGChatPipeline, Depends(get_rag_pipeline)]


class MultiDocumentQuestionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    document_ids: list[int] = Field(min_length=1, max_length=20)
    language: Literal["English", "Hindi", "Punjabi"] = "English"


class DocumentComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_ids: list[int] = Field(min_length=2, max_length=2)


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


class StudyPlanRequest(BaseModel):
    exam_date: date
    daily_minutes: int = Field(ge=1, le=600)
    document_ids: list[int] = Field(min_length=1, max_length=MAX_PLAN_DOCUMENTS)


def _plan_payload(db: Session, plan: StudyPlan) -> dict[str, Any]:
    items = list(
        db.scalars(
            select(StudyPlanItem)
            .where(StudyPlanItem.plan_id == plan.id)
            .order_by(StudyPlanItem.scheduled_date, StudyPlanItem.id)
        )
    )
    grouped: dict[date, list[StudyPlanItem]] = {}
    for item in items:
        grouped.setdefault(item.scheduled_date, []).append(item)
    if plan.start_date <= plan.exam_date:
        days = []
        current = plan.start_date
        while current <= plan.exam_date:
            day_items = grouped.get(current, [])
            days.append(
                {
                    "date": current.isoformat(),
                    "activities": [
                        {
                            "id": item.id,
                            "activity_type": item.activity_type,
                            "topic": item.topic,
                            "document_id": item.document_id,
                            "page_start": item.page_start,
                            "page_end": item.page_end,
                            "minutes": item.minutes,
                            "is_done": item.is_done,
                        }
                        for item in day_items
                    ],
                    "total_minutes": sum(item.minutes for item in day_items),
                }
            )
            current += timedelta(days=1)
    else:
        days = []
    return {
        "id": plan.id,
        "exam_date": plan.exam_date.isoformat(),
        "daily_minutes": plan.daily_minutes,
        "document_ids": plan.document_ids,
        "days": days,
        "omitted_topics": plan.omitted_topics,
    }


def _persist_plan_activities(
    db: Session, *, plan: StudyPlan, generated: dict[str, Any]
) -> None:
    for day in generated["days"]:
        scheduled_date = date.fromisoformat(day["date"])
        for activity in day["activities"]:
            db.add(
                StudyPlanItem(
                    plan_id=plan.id,
                    scheduled_date=scheduled_date,
                    activity_type=activity["activity_type"],
                    topic=activity["topic"],
                    document_id=activity["document_id"],
                    page_start=activity["page_start"],
                    page_end=activity["page_end"],
                    minutes=activity["minutes"],
                )
            )


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


def _owned_plan(db: Session, plan_id: int, owner_id: int) -> StudyPlan:
    plan = db.scalar(
        select(StudyPlan).where(
            StudyPlan.id == plan_id,
            StudyPlan.owner_id == owner_id,
        )
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="Study plan not found.")
    return plan


def _resolve_graph_scope(
    db: Session,
    *,
    document_id: int,
    chapter: str | None,
    page_start: int | None,
    page_end: int | None,
) -> tuple[int | None, int | None]:
    if chapter is None:
        return page_start, page_end
    if page_start is not None or page_end is not None:
        raise HTTPException(
            status_code=422,
            detail="Use either chapter or page range, not both.",
        )
    pages = list(
        db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_number)
        )
    )
    headings = [
        (page.page_number, str(heading["text"]).strip())
        for page in pages
        for heading in page.headings or []
        if isinstance(heading, dict)
        and isinstance(heading.get("text"), str)
        and heading["text"].strip()
    ]
    chapter_key = chapter.strip().casefold()
    matches = [
        index
        for index, (_, title) in enumerate(headings)
        if title.casefold() == chapter_key
    ]
    if not matches:
        raise HTTPException(status_code=404, detail="Chapter not found.")
    heading_index = matches[0]
    start = headings[heading_index][0]
    next_page = next(
        (
            heading_page
            for heading_page, _ in headings[heading_index + 1 :]
            if heading_page > start
        ),
        None,
    )
    end = (
        next_page - 1
        if next_page is not None
        else max((page.page_number for page in pages), default=start)
    )
    return start, end


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


class SummaryRequest(BaseModel):
    summary_type: Literal["short", "detailed", "chapter_wise"] = "short"
    engine: Literal["extractive", "t5", "llm"] = "extractive"
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    regenerate: bool = False
    run_async: bool = False


def _summary_payload(summary: DocumentSummary) -> dict[str, Any]:
    return {
        "id": summary.id,
        "document_id": summary.document_id,
        "owner_id": summary.owner_id,
        "summary_type": summary.summary_type,
        "engine_requested": summary.engine_requested,
        "engine_used": summary.engine_used,
        "fallback_reason": summary.fallback_reason,
        "page_start": summary.page_start,
        "page_end": summary.page_end,
        "content": summary.content,
        "items": summary.items,
        "created_at": summary.created_at,
        "updated_at": summary.updated_at,
    }


def get_study_job_queue(background_tasks: BackgroundTasks) -> JobQueue:
    """Resolve the queue and register summary job handler."""
    return create_job_queue(
        background_tasks,
        {"generate_summary": start_summary_job},
    )


StudyJobQueue = Annotated[JobQueue, Depends(get_study_job_queue)]


@router.post("/documents/{document_id}/summaries", status_code=201)
def create_summary(
    document_id: int,
    request: SummaryRequest,
    db: DatabaseSession,
    user: AuthenticatedUser,
    job_queue: StudyJobQueue,
) -> dict[str, Any]:
    """Generate or retrieve a grounded summary for an owned document."""
    document = _owned_document(db, document_id, user.id)

    if (
        request.page_start
        and request.page_end
        and request.page_start > request.page_end
    ):
        raise HTTPException(
            status_code=422, detail="page_start must not exceed page_end."
        )

    # Cache lookup if not explicitly regenerating
    if not request.regenerate:
        query = (
            select(DocumentSummary)
            .where(
                DocumentSummary.document_id == document.id,
                DocumentSummary.owner_id == user.id,
                DocumentSummary.summary_type == request.summary_type,
                DocumentSummary.engine_requested == request.engine,
            )
            .order_by(DocumentSummary.id.desc())
        )
        existing = next(
            (
                summary
                for summary in db.scalars(query)
                if isinstance(summary.generation_metadata, dict)
                and "requested_page_start" in summary.generation_metadata
                and "requested_page_end" in summary.generation_metadata
                and summary.generation_metadata["requested_page_start"]
                == request.page_start
                and summary.generation_metadata["requested_page_end"]
                == request.page_end
            ),
            None,
        )
        if existing:
            return _summary_payload(existing)

    if request.run_async:
        job_id = str(uuid4())
        job_queue.enqueue(
            "generate_summary",
            job_id,
            db,
            document.id,
            user.id,
            request.summary_type,
            request.engine,
            request.page_start,
            request.page_end,
        )
        return {"job_id": job_id, "status": "queued"}

    summary = generate_document_summary(
        db,
        document=document,
        summary_type=request.summary_type,
        engine=request.engine,
        page_start=request.page_start,
        page_end=request.page_end,
    )
    db.commit()
    db.refresh(summary)
    return _summary_payload(summary)


@router.get("/documents/{document_id}/summaries")
def list_document_summaries(
    document_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> list[dict[str, Any]]:
    """List summaries generated for an owned document."""
    _owned_document(db, document_id, user.id)
    summaries = list(
        db.scalars(
            select(DocumentSummary)
            .where(
                DocumentSummary.document_id == document_id,
                DocumentSummary.owner_id == user.id,
            )
            .order_by(DocumentSummary.id.desc())
        )
    )
    return [_summary_payload(s) for s in summaries]


@router.get("/summaries/{summary_id}")
def get_summary(
    summary_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Get a specific summary by ID."""
    summary = db.scalar(
        select(DocumentSummary).where(
            DocumentSummary.id == summary_id,
            DocumentSummary.owner_id == user.id,
        )
    )
    if summary is None:
        raise HTTPException(status_code=404, detail="Summary not found.")
    return _summary_payload(summary)


@router.delete("/summaries/{summary_id}", status_code=204)
def delete_summary(
    summary_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> None:
    """Delete a summary by ID."""
    summary = db.scalar(
        select(DocumentSummary).where(
            DocumentSummary.id == summary_id,
            DocumentSummary.owner_id == user.id,
        )
    )
    if summary is None:
        raise HTTPException(status_code=404, detail="Summary not found.")
    db.delete(summary)
    db.commit()


@router.get("/summaries/jobs/{job_id}")
def get_summary_job(
    job_id: str,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Retrieve async summary job status."""
    status_info = get_summary_job_status(job_id, user.id)
    if not status_info:
        raise HTTPException(status_code=404, detail="Summary job not found.")
    return {"job_id": job_id, **status_info}


@router.get("/documents/{document_id}/notes")
def get_chapter_notes(
    document_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
    page_start: Annotated[int | None, Query(ge=1)] = None,
    page_end: Annotated[int | None, Query(ge=1)] = None,
) -> Response:
    """Return rule-based chapter notes in Markdown."""
    document = _owned_document(db, document_id, user.id)
    if page_start and page_end and page_start > page_end:
        raise HTTPException(
            status_code=422, detail="page_start must not exceed page_end."
        )

    notes_md = generate_chapter_notes(
        db,
        document=document,
        page_start=page_start,
        page_end=page_end,
    )
    return Response(content=notes_md, media_type="text/markdown; charset=utf-8")


@router.get("/documents/{document_id}/cheat-sheet")
def get_cheat_sheet(
    document_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
    page_start: Annotated[int | None, Query(ge=1)] = None,
    page_end: Annotated[int | None, Query(ge=1)] = None,
) -> Response:
    """Return a rule-based one-page cheat sheet in Markdown."""
    document = _owned_document(db, document_id, user.id)
    if page_start and page_end and page_start > page_end:
        raise HTTPException(
            status_code=422, detail="page_start must not exceed page_end."
        )

    cheat_sheet_md = generate_cheat_sheet(
        db,
        document=document,
        page_start=page_start,
        page_end=page_end,
    )
    return Response(content=cheat_sheet_md, media_type="text/markdown; charset=utf-8")


@router.get("/documents/{document_id}/graph")
def get_document_graph(
    document_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
    chapter: Annotated[str | None, Query(max_length=255)] = None,
    page_start: Annotated[int | None, Query(ge=1)] = None,
    page_end: Annotated[int | None, Query(ge=1)] = None,
    max_nodes: Annotated[int, Query(ge=1, le=200)] = 40,
    label_relations: bool = False,
) -> dict[str, Any]:
    """Return a bounded, owner-scoped graph with copied page evidence."""
    document = _owned_document(db, document_id, user.id)
    page_start, page_end = _resolve_graph_scope(
        db,
        document_id=document.id,
        chapter=chapter,
        page_start=page_start,
        page_end=page_end,
    )
    if page_start and page_end and page_start > page_end:
        raise HTTPException(
            status_code=422, detail="page_start must not exceed page_end."
        )
    provider = None
    settings = get_settings()
    if label_relations and not document.is_private:
        candidate = RAGChatPipeline(settings=settings).provider
        if not candidate.is_external or settings.allow_external_llm:
            provider = candidate
    try:
        graph = build_concept_graph(
            db,
            document=document,
            owner_id=user.id,
            page_start=page_start,
            page_end=page_end,
            max_nodes=max_nodes,
            relation_provider=provider,
        )
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except (ProviderError, ProviderUnavailableError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=502, detail="Optional relation labeling failed."
        ) from exc
    return graph


@router.get("/documents/{document_id}/graph/nodes/{node_id}")
def get_graph_node(
    document_id: int,
    node_id: str,
    db: DatabaseSession,
    user: AuthenticatedUser,
    chapter: Annotated[str | None, Query(max_length=255)] = None,
    page_start: Annotated[int | None, Query(ge=1)] = None,
    page_end: Annotated[int | None, Query(ge=1)] = None,
) -> dict[str, Any]:
    """Return a graph node, its stored definition, and evidenced neighbours."""
    document = _owned_document(db, document_id, user.id)
    page_start, page_end = _resolve_graph_scope(
        db,
        document_id=document.id,
        chapter=chapter,
        page_start=page_start,
        page_end=page_end,
    )
    if page_start and page_end and page_start > page_end:
        raise HTTPException(
            status_code=422, detail="page_start must not exceed page_end."
        )
    try:
        graph = build_concept_graph(
            db,
            document=document,
            owner_id=user.id,
            page_start=page_start,
            page_end=page_end,
        )
    except ValueError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    detail = get_graph_node_detail(
        graph,
        node_id,
        graph_definitions(
            db,
            document_id=document.id,
            owner_id=user.id,
            nodes=graph["nodes"],
        ),
    )
    if detail is None:
        raise HTTPException(status_code=404, detail="Graph node not found.")
    return detail


@router.post("/plans", status_code=201)
def create_study_plan(
    request: StudyPlanRequest,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Create and persist a deterministic study plan for owned documents."""
    if len(set(request.document_ids)) != len(request.document_ids):
        raise HTTPException(status_code=422, detail="document_ids must be unique.")
    today = date.today()
    try:
        topics = collect_study_topics(
            db, owner_id=user.id, document_ids=request.document_ids
        )
        generated = generate_study_plan(
            topics,
            exam_date=request.exam_date,
            daily_minutes=request.daily_minutes,
            today=today,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    plan = StudyPlan(
        owner_id=user.id,
        start_date=today,
        exam_date=request.exam_date,
        daily_minutes=request.daily_minutes,
        document_ids=request.document_ids,
        omitted_topics=generated["omitted_topics"],
    )
    db.add(plan)
    db.flush()
    _persist_plan_activities(db, plan=plan, generated=generated)
    db.commit()
    db.refresh(plan)
    return _plan_payload(db, plan)


@router.get("/plans/current")
def get_current_study_plan(
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Get the most recently created plan for the authenticated user."""
    plan = db.scalar(
        select(StudyPlan)
        .where(StudyPlan.owner_id == user.id)
        .order_by(StudyPlan.created_at.desc(), StudyPlan.id.desc())
        .limit(1)
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="Study plan not found.")
    return _plan_payload(db, plan)


@router.patch("/plans/{plan_id}/days/{scheduled_date}/done")
def mark_study_day_done(
    plan_id: int,
    scheduled_date: date,
    done: bool,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Mark all activities on one owned plan date complete or incomplete."""
    plan = _owned_plan(db, plan_id, user.id)
    items = list(
        db.scalars(
            select(StudyPlanItem).where(
                StudyPlanItem.plan_id == plan.id,
                StudyPlanItem.scheduled_date == scheduled_date,
            )
        )
    )
    if not items:
        raise HTTPException(status_code=404, detail="Study plan day not found.")
    completed_at = datetime.now(UTC) if done else None
    for item in items:
        item.is_done = done
        item.completed_at = completed_at
    db.commit()
    return _plan_payload(db, plan)


@router.patch("/plans/{plan_id}/items/{item_id}/done")
def mark_study_activity_done(
    plan_id: int,
    item_id: int,
    done: bool,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Mark one activity done only when both plan and item are owner-scoped."""
    plan = _owned_plan(db, plan_id, user.id)
    item = db.scalar(
        select(StudyPlanItem).where(
            StudyPlanItem.id == item_id,
            StudyPlanItem.plan_id == plan.id,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Study plan activity not found.")
    item.is_done = done
    item.completed_at = datetime.now(UTC) if done else None
    db.commit()
    return _plan_payload(db, plan)


@router.post("/plans/{plan_id}/regenerate")
def regenerate_study_plan(
    plan_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Rebuild future activities from today while keeping completed items."""
    plan = _owned_plan(db, plan_id, user.id)
    today = date.today()
    if plan.exam_date < today:
        raise HTTPException(status_code=422, detail="The plan exam date has passed.")
    completed = list(
        db.scalars(
            select(StudyPlanItem).where(
                StudyPlanItem.plan_id == plan.id,
                StudyPlanItem.is_done.is_(True),
            )
        )
    )
    try:
        topics = collect_study_topics(
            db, owner_id=user.id, document_ids=plan.document_ids
        )
        generated = generate_study_plan(
            topics,
            exam_date=plan.exam_date,
            daily_minutes=plan.daily_minutes,
            today=today,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    plan.start_date = min([today, *(item.scheduled_date for item in completed)])
    plan.omitted_topics = generated["omitted_topics"]
    db.execute(
        delete(StudyPlanItem).where(
            StudyPlanItem.plan_id == plan.id,
            StudyPlanItem.is_done.is_(False),
        )
    )
    completed_signatures = {
        (
            item.scheduled_date,
            item.activity_type,
            item.topic,
            item.document_id,
            item.page_start,
            item.page_end,
        )
        for item in completed
    }
    for day in generated["days"]:
        scheduled_date = date.fromisoformat(day["date"])
        for activity in day["activities"]:
            signature = (
                scheduled_date,
                activity["activity_type"],
                activity["topic"],
                activity["document_id"],
                activity["page_start"],
                activity["page_end"],
            )
            if signature in completed_signatures:
                continue
            db.add(
                StudyPlanItem(
                    plan_id=plan.id,
                    scheduled_date=scheduled_date,
                    activity_type=activity["activity_type"],
                    topic=activity["topic"],
                    document_id=activity["document_id"],
                    page_start=activity["page_start"],
                    page_end=activity["page_end"],
                    minutes=activity["minutes"],
                )
            )
    db.commit()
    return _plan_payload(db, plan)


def _selected_documents(
    db: Session,
    *,
    document_ids: list[int],
    owner_id: int,
    max_count: int,
    allow_duplicates: bool = False,
) -> list[Document]:
    if len(document_ids) > max_count:
        raise HTTPException(
            status_code=413,
            detail=f"Select no more than {max_count} documents.",
        )
    if not allow_duplicates and len(set(document_ids)) != len(document_ids):
        raise HTTPException(
            status_code=422,
            detail="Selected document IDs must be unique.",
        )
    documents = list(
        db.scalars(
            select(Document).where(
                Document.owner_id == owner_id,
                Document.id.in_(set(document_ids)),
            )
        )
    )
    if {document.id for document in documents} != set(document_ids):
        raise HTTPException(status_code=404, detail="One or more documents not found.")
    by_id = {document.id: document for document in documents}
    return [by_id[document_id] for document_id in document_ids]


@router.post("/multi-document/qa")
def ask_across_documents(
    request: MultiDocumentQuestionRequest,
    db: DatabaseSession,
    user: AuthenticatedUser,
    pipeline: RAGPipeline,
) -> dict[str, Any]:
    """Answer one question from a bounded set of the user's documents."""
    documents = _selected_documents(
        db,
        document_ids=request.document_ids,
        owner_id=user.id,
        max_count=get_settings().max_multi_document_count,
    )
    return answer_across_documents(
        db,
        pipeline=pipeline,
        user_id=user.id,
        document_ids=[document.id for document in documents],
        question=request.question,
        language=request.language,
    )


@router.post("/documents/compare")
def compare_owned_documents(
    request: DocumentComparisonRequest,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Compare two owned documents using stored terms and section embeddings."""
    documents = _selected_documents(
        db,
        document_ids=request.document_ids,
        owner_id=user.id,
        max_count=get_settings().max_multi_document_count,
        allow_duplicates=True,
    )
    return compare_documents(
        db,
        document_a=documents[0],
        document_b=documents[1],
    )


@export_router.get("/export/{kind}/{item_id}")
def download_study_export(
    kind: str,
    item_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
    format: Annotated[str, Query()],
    page_start: Annotated[int | None, Query(ge=1)] = None,
    page_end: Annotated[int | None, Query(ge=1)] = None,
    include_answers: bool = False,
) -> Response:
    """Generate an authenticated, owner-scoped study export in memory."""
    try:
        content, media_type, filename = generate_export(
            db,
            owner_id=user.id,
            kind=kind,
            item_id=item_id,
            format=format,
            page_start=page_start,
            page_end=page_end,
            include_answers=include_answers,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": content_disposition(filename)},
    )
