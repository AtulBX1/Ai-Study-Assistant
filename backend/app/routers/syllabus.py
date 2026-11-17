"""Owner-private syllabus CRUD, mapping, and coverage endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.dependencies.auth import DatabaseSession, get_current_user
from app.models import (
    AttemptAnswer,
    Chunk,
    ChunkTopic,
    Document,
    DocumentPage,
    Question,
    Quiz,
    QuizAttempt,
    Syllabus,
    SyllabusTopic,
    User,
)
from app.services.embeddings import EmbeddingService, get_embedding_service
from app.services.syllabus import coverage, parse_syllabus, remap_syllabus, save_tree
from app.services.syllabus.questions import important_questions
from app.services.web_search import web_study_items


def remap_now(db: Session, item: Syllabus) -> None:
    remap_syllabus(
        db,
        item,
        item.owner_id,
        get_embedding_service(),
        get_settings().syllabus_mapping_threshold,
    )


router = APIRouter(prefix="/syllabi", tags=["syllabi"])
AuthenticatedUser = Annotated[User, Depends(get_current_user)]


class PreviewRequest(BaseModel):
    text: str = Field(min_length=1)


class SyllabusCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    text: str | None = None
    document_id: int | None = None
    use_web_search: bool = False


class SyllabusRename(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class TopicEdit(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    parent_id: int | None = None
    order: int | None = None
    keywords: list[str] | None = None
    sub_topics: list[str] | None = None


class TopicCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    parent_id: int | None = None
    order: int = 0
    keywords: list[str] = Field(default_factory=list)
    sub_topics: list[str] = Field(default_factory=list)


class ManualMap(BaseModel):
    document_id: int
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)


class QuestionBatchRequest(BaseModel):
    suggest_likely: bool = False


def owned(db: Session, syllabus_id: int, owner_id: int) -> Syllabus:
    item = db.scalar(
        select(Syllabus).where(
            Syllabus.id == syllabus_id, Syllabus.owner_id == owner_id
        )
    )
    if item is None:
        raise HTTPException(404, "Syllabus not found.")
    return item


def tree(db: Session, syllabus: Syllabus) -> list[dict[str, Any]]:
    topics = list(
        db.scalars(
            select(SyllabusTopic)
            .where(SyllabusTopic.syllabus_id == syllabus.id)
            .order_by(SyllabusTopic.order, SyllabusTopic.id)
        )
    )
    children: dict[int | None, list[dict]] = {}
    for topic in topics:
        children.setdefault(topic.parent_id, []).append(
            {
                "id": topic.id,
                "title": topic.title,
                "order": topic.order,
                "keywords": topic.keywords,
                "sub_topics": topic.sub_topics,
                "children": [],
            }
        )
    lookup = {node["id"]: node for values in children.values() for node in values}
    for topic in topics:
        if topic.parent_id is not None and topic.parent_id in lookup:
            lookup[topic.parent_id]["children"].append(lookup[topic.id])
    return children.get(None, [])


@router.post("/preview")
def preview(request: PreviewRequest, user: AuthenticatedUser) -> dict:
    del user
    return {
        "tree": parse_syllabus(request.text),
        "pipeline_stages": {
            "retrieval": "provided syllabus text",
            "generation": "local syllabus parser",
            "validation": "local topic hierarchy checks",
        },
    }


@router.post("")
def create(
    request: SyllabusCreate, db: DatabaseSession, user: AuthenticatedUser
) -> dict:
    if (request.text is None) == (request.document_id is None):
        raise HTTPException(422, "Provide exactly one of text or document_id.")
    text = request.text
    document = None
    if request.document_id is not None:
        document = db.scalar(
            select(Document).where(
                Document.id == request.document_id,
                Document.owner_id == user.id,
                Document.status == "ready",
            )
        )
        if document is None:
            raise HTTPException(404, "Ready document not found.")
        text = "\n".join(
            db.scalars(
                select(DocumentPage.text)
                .where(DocumentPage.document_id == document.id)
                .order_by(DocumentPage.page_number)
            )
        )
    syllabus = Syllabus(owner_id=user.id, title=request.title)
    web_sources: list[dict[str, str]] = []
    web_notice = None
    if request.use_web_search and document is not None:
        if user.local_models_only:
            web_notice = (
                "Web search is unavailable in local-only mode; "
                "continuing with your notes only."
            )
        elif document.is_private:
            web_notice = (
                "Web search is unavailable for private documents; "
                "continuing with your notes only."
            )
        else:
            from app.services.web_search import search_web

            web_sources, web_notice = search_web(request.title)
    syllabus.web_sources = {
        "your_notes": (
            [{"document_id": document.id, "document_title": document.title}]
            if document
            else [{"label": "Provided syllabus text"}]
        ),
        "web": web_sources,
    }
    db.add(syllabus)
    db.flush()
    save_tree(db, syllabus, parse_syllabus(text or ""))
    remap_now(db, syllabus)
    db.commit()
    return {
        "id": syllabus.id,
        "title": syllabus.title,
        "tree": tree(db, syllabus),
        "sources": {
            "your_notes": syllabus.web_sources["your_notes"],
            "web": web_sources,
        },
        "web_items": web_study_items(web_sources),
        "web_notice": web_notice,
        "pipeline_stages": {
            "retrieval": (
                "local document pages"
                if request.document_id
                else "provided syllabus text"
            ),
            "generation": "local syllabus parser",
            "validation": "local topic hierarchy checks",
        },
    }


@router.get("")
def list_syllabi(db: DatabaseSession, user: AuthenticatedUser) -> list[dict]:
    return [
        {"id": item.id, "title": item.title}
        for item in db.scalars(
            select(Syllabus).where(Syllabus.owner_id == user.id).order_by(Syllabus.id)
        )
    ]


@router.get("/{syllabus_id}")
def get(syllabus_id: int, db: DatabaseSession, user: AuthenticatedUser) -> dict:
    item = owned(db, syllabus_id, user.id)
    return {
        "id": item.id,
        "title": item.title,
        "tree": tree(db, item),
        "sources": {
            "your_notes": (item.web_sources or {}).get("your_notes", []),
            "web": (item.web_sources or {}).get("web", []),
        },
        "web_items": web_study_items((item.web_sources or {}).get("web", [])),
    }


@router.patch("/{syllabus_id}")
def rename(
    syllabus_id: int,
    request: SyllabusRename,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict:
    item = owned(db, syllabus_id, user.id)
    item.title = request.title
    db.commit()
    return {"id": item.id, "title": item.title}


@router.post("/{syllabus_id}/topics", status_code=201)
def add_topic(
    syllabus_id: int, request: TopicCreate, db: DatabaseSession, user: AuthenticatedUser
) -> dict:
    item = owned(db, syllabus_id, user.id)
    if (
        request.parent_id is not None
        and db.scalar(
            select(SyllabusTopic.id).where(
                SyllabusTopic.id == request.parent_id,
                SyllabusTopic.syllabus_id == item.id,
            )
        )
        is None
    ):
        raise HTTPException(404, "Parent topic not found.")
    topic = SyllabusTopic(syllabus_id=item.id, **request.model_dump())
    db.add(topic)
    db.flush()
    remap_now(db, item)
    db.commit()
    return {"id": topic.id, "title": topic.title}


@router.patch("/{syllabus_id}/topics/{topic_id}")
def edit_topic(
    syllabus_id: int,
    topic_id: int,
    request: TopicEdit,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict:
    item = owned(db, syllabus_id, user.id)
    topic = db.scalar(
        select(SyllabusTopic).where(
            SyllabusTopic.id == topic_id, SyllabusTopic.syllabus_id == item.id
        )
    )
    if topic is None:
        raise HTTPException(404, "Topic not found.")
    values = request.model_dump(exclude_unset=True)
    if (
        "parent_id" in values
        and values["parent_id"] is not None
        and db.scalar(
            select(SyllabusTopic.id).where(
                SyllabusTopic.id == values["parent_id"],
                SyllabusTopic.syllabus_id == item.id,
            )
        )
        is None
    ):
        raise HTTPException(404, "Parent topic not found.")
    for key, value in values.items():
        setattr(topic, key, value)
    remap_now(db, item)
    db.commit()
    return {"id": topic.id, "title": topic.title, "order": topic.order}


@router.delete("/{syllabus_id}/topics/{topic_id}", status_code=204)
def delete_topic(
    syllabus_id: int, topic_id: int, db: DatabaseSession, user: AuthenticatedUser
):
    item = owned(db, syllabus_id, user.id)
    topic = db.scalar(
        select(SyllabusTopic).where(
            SyllabusTopic.id == topic_id, SyllabusTopic.syllabus_id == item.id
        )
    )
    if topic is None:
        raise HTTPException(404, "Topic not found.")
    db.delete(topic)
    db.flush()
    remap_now(db, item)
    db.commit()


@router.delete("/{syllabus_id}", status_code=204)
def delete_syllabus(syllabus_id: int, db: DatabaseSession, user: AuthenticatedUser):
    db.delete(owned(db, syllabus_id, user.id))
    db.commit()


@router.post("/{syllabus_id}/remap")
def remap(
    syllabus_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
    embedder: Annotated[EmbeddingService, Depends(get_embedding_service)],
) -> dict:
    item = owned(db, syllabus_id, user.id)
    count = remap_syllabus(
        db, item, user.id, embedder, get_settings().syllabus_mapping_threshold
    )
    db.commit()
    return {"mapped": count}


@router.get("/{syllabus_id}/coverage")
def get_coverage(
    syllabus_id: int, db: DatabaseSession, user: AuthenticatedUser
) -> dict:
    owned(db, syllabus_id, user.id)
    return coverage(db, syllabus_id)


@router.post("/{syllabus_id}/topics/{topic_id}/important-questions")
def topic_important_questions(
    syllabus_id: int,
    topic_id: int,
    request: QuestionBatchRequest,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict:
    item = owned(db, syllabus_id, user.id)
    topic = db.scalar(
        select(SyllabusTopic).where(
            SyllabusTopic.id == topic_id, SyllabusTopic.syllabus_id == item.id
        )
    )
    if topic is None:
        raise HTTPException(404, "Topic not found.")
    mapped = list(
        db.execute(
            select(ChunkTopic, Chunk)
            .join(Chunk, ChunkTopic.chunk_id == Chunk.id)
            .join(Document, Chunk.doc_id == Document.id)
            .where(
                ChunkTopic.topic_id == topic.id,
                Document.owner_id == user.id,
                Document.status == "ready",
            )
            .order_by(Chunk.id)
        )
    )
    return important_questions(topic, mapped, suggest_likely=request.suggest_likely)


@router.get("/{syllabus_id}/analytics")
def syllabus_analytics(
    syllabus_id: int, db: DatabaseSession, user: AuthenticatedUser
) -> dict:
    item = owned(db, syllabus_id, user.id)
    topics = list(
        db.scalars(
            select(SyllabusTopic)
            .where(SyllabusTopic.syllabus_id == item.id)
            .order_by(SyllabusTopic.order)
        )
    )
    answers = db.execute(
        select(Question.syllabus_topic_id, AttemptAnswer.is_correct)
        .join(AttemptAnswer, AttemptAnswer.question_id == Question.id)
        .join(QuizAttempt, QuizAttempt.id == AttemptAnswer.attempt_id)
        .join(Quiz, Quiz.id == QuizAttempt.quiz_id)
        .where(
            QuizAttempt.user_id == user.id,
            Quiz.owner_id == user.id,
            Question.syllabus_topic_id.is_not(None),
            AttemptAnswer.is_correct.is_not(None),
        )
    ).all()
    by_topic: dict[int, list[bool]] = {}
    for topic_id, correct in answers:
        by_topic.setdefault(topic_id, []).append(bool(correct))
    stats = []
    for topic in topics:
        results = by_topic.get(topic.id, [])
        correct = sum(results)
        accuracy = correct / len(results) if results else None
        stats.append(
            {
                "topic_id": topic.id,
                "topic": topic.title,
                "answers": len(results),
                "correct": correct,
                "accuracy_percent": (
                    round(accuracy * 100, 2) if accuracy is not None else None
                ),
                "weak": len(results) >= 3 and accuracy < 0.7,
            }
        )
    eligible = [value for value in stats if value["answers"] >= 3]
    progressing = sum(value["accuracy_percent"] >= 70 for value in eligible)
    return {
        "syllabus_id": item.id,
        "topics": stats,
        "weak_areas": [value for value in stats if value["weak"]],
        "progress_percent": (
            round(progressing / len(topics) * 100, 2) if topics else 0.0
        ),
        "progress_topics": progressing,
        "total_topics": len(topics),
    }


@router.post("/{syllabus_id}/topics/{topic_id}/chunks")
def attach_pages(
    syllabus_id: int,
    topic_id: int,
    request: ManualMap,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict:
    item = owned(db, syllabus_id, user.id)
    topic = db.scalar(
        select(SyllabusTopic).where(
            SyllabusTopic.id == topic_id, SyllabusTopic.syllabus_id == item.id
        )
    )
    doc = db.scalar(
        select(Document).where(
            Document.id == request.document_id, Document.owner_id == user.id
        )
    )
    if topic is None or doc is None:
        raise HTTPException(404, "Topic or document not found.")
    if request.page_end < request.page_start:
        raise HTTPException(422, "page_end must be at least page_start.")
    chunks = list(
        db.scalars(
            select(Chunk).where(
                Chunk.doc_id == doc.id,
                Chunk.page_end >= request.page_start,
                Chunk.page_start <= request.page_end,
            )
        )
    )
    for chunk in chunks:
        for automatic in db.scalars(
            select(ChunkTopic).where(
                ChunkTopic.chunk_id == chunk.id,
                ChunkTopic.source == "auto",
            )
        ):
            db.delete(automatic)
        existing = db.scalar(
            select(ChunkTopic).where(
                ChunkTopic.chunk_id == chunk.id, ChunkTopic.topic_id == topic.id
            )
        )
        if existing:
            existing.source = "manual"
            existing.page_start, existing.page_end = (
                request.page_start,
                request.page_end,
            )
        else:
            db.add(
                ChunkTopic(
                    chunk_id=chunk.id,
                    topic_id=topic.id,
                    source="manual",
                    score=1.0,
                    page_start=request.page_start,
                    page_end=request.page_end,
                )
            )
    db.commit()
    return {"attached_chunks": len(chunks)}


@router.delete("/{syllabus_id}/topics/{topic_id}/chunks")
def detach_pages(
    syllabus_id: int,
    topic_id: int,
    request: ManualMap,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict:
    item = owned(db, syllabus_id, user.id)
    topic = db.scalar(
        select(SyllabusTopic).where(
            SyllabusTopic.id == topic_id, SyllabusTopic.syllabus_id == item.id
        )
    )
    doc = db.scalar(
        select(Document).where(
            Document.id == request.document_id, Document.owner_id == user.id
        )
    )
    if topic is None or doc is None:
        raise HTTPException(404, "Topic or document not found.")
    rows = list(
        db.scalars(
            select(ChunkTopic)
            .join(Chunk, Chunk.id == ChunkTopic.chunk_id)
            .where(
                ChunkTopic.topic_id == topic.id,
                ChunkTopic.source == "manual",
                Chunk.doc_id == doc.id,
                Chunk.page_end >= request.page_start,
                Chunk.page_start <= request.page_end,
            )
        )
    )
    for row in rows:
        db.delete(row)
    db.commit()
    return {"detached_chunks": len(rows)}
