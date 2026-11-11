"""Authenticated, owner-scoped quiz generation and attempt endpoints."""

from collections import Counter, defaultdict
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
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
    DocumentKeyTerm,
    DocumentPage,
    Question,
    Quiz,
    QuizAttempt,
    Syllabus,
    SyllabusTopic,
    TopicStat,
    User,
)
from app.services.quiz.exam_export import export_docx, export_pdf
from app.services.quiz.generation import (
    ClassicEngine,
    LLMEngine,
    StructuredOutputError,
    balance_true_false_questions,
    clean_chunk_text,
)
from app.services.quiz.grading import grade_answer, weak_question_ids
from app.services.quiz.schemas import GenerationRequest, QuizQuestion
from app.services.quiz.validation import embedding_similarity, validate_generated
from app.services.rag.providers import (
    GeminiProvider,
    GroqProvider,
    OllamaProvider,
    ProviderChain,
    ProviderError,
    ProviderUnavailableError,
    RateLimitError,
)

router = APIRouter(prefix="/quizzes", tags=["quizzes"])
AuthenticatedUser = Annotated[User, Depends(get_current_user)]


class AnswerItem(BaseModel):
    question_id: int = Field(gt=0)
    answer: str = Field(default="", max_length=2000)


class SubmitAnswers(BaseModel):
    answers: list[AnswerItem] = Field(min_length=1, max_length=100)


def _quiz_or_404(db: Session, quiz_id: int, owner_id: int) -> Quiz:
    quiz = db.scalar(select(Quiz).where(Quiz.id == quiz_id, Quiz.owner_id == owner_id))
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    return quiz


def _source_topic(
    question: Question,
    chunks: dict[int, Chunk],
    terms_by_document: dict[int, list[DocumentKeyTerm]],
) -> str:
    """Prefer a source section or key term to a generated topic label."""
    chunk = chunks.get(question.source_chunk_id)
    if chunk is not None:
        section = (chunk.section or "").strip()
        if section:
            return section
        matching_terms = [
            term.term
            for term in terms_by_document.get(chunk.doc_id, [])
            if chunk.page_start <= term.page <= chunk.page_end
            and term.term.casefold() in chunk.text.casefold()
        ]
        if matching_terms:
            return max(matching_terms, key=lambda value: (len(value), value.casefold()))
    return question.topic or "General"


def _provider() -> Any:
    settings = get_settings()
    if not settings.allow_external_llm:
        raise ProviderUnavailableError("External LLM use is disabled.")
    configured = []
    for name in settings.llm_provider_chain.split(","):
        name = name.strip().lower()
        if name == "gemini" and settings.gemini_api_key:
            configured.append(GeminiProvider())
        elif name == "groq" and settings.groq_api_key:
            configured.append(GroqProvider())
        elif name == "ollama":
            configured.append(OllamaProvider())
    if configured:
        return ProviderChain(
            configured, context_budget=settings.llm_context_token_budget
        )
    if settings.llm_provider == "ollama":
        return OllamaProvider()
    if settings.llm_provider == "gemini":
        provider = GeminiProvider()
        if not provider.api_key:
            raise ProviderUnavailableError("LLM provider key is missing.")
        return provider
    raise ProviderUnavailableError(
        "Configured provider cannot generate structured quizzes."
    )


def _question_payload(
    question: Question, *, include_answer: bool = False
) -> dict[str, Any]:
    metadata = question.options if isinstance(question.options, dict) else {}
    options = metadata.get("choices") if metadata else question.options
    payload = {
        "id": question.id,
        "question": question.prompt,
        "type": question.type,
        "options": options,
        "explanation": question.explanation,
        "evidence": metadata.get("evidence", question.explanation),
        "source_highlight": metadata.get("evidence", question.explanation),
        "source_chunk_id": question.source_chunk_id,
        "page": question.page,
        "difficulty": question.difficulty,
        "engine": question.engine,
        "topic": question.topic,
        "source_page_url": (
            f"/documents/{metadata.get('document_id', '')}/pages/{question.page}"
        ),
        "provider": metadata.get("provider"),
    }
    if include_answer:
        payload["correct_answer"] = question.answer
    return payload


def _type_quotas(request: GenerationRequest) -> dict[str, int]:
    """Split the requested count in question-type round-robin order."""
    selected = [item.value for item in request.question_types]
    return {
        kind: request.count // len(selected)
        + int(index < request.count % len(selected))
        for index, kind in enumerate(selected)
    }


def _type_cycle(quotas: dict[str, int]) -> tuple[str, ...]:
    """Expand remaining per-type quotas into the requested generation order."""
    remaining = quotas.copy()
    cycle: list[str] = []
    while any(remaining.values()):
        for kind in quotas:
            if remaining[kind] > 0:
                cycle.append(kind)
                remaining[kind] -= 1
    return tuple(cycle)


def _top_rejections(rejects: Counter[str]) -> dict[str, int]:
    return dict(rejects.most_common(5))


def _type_report(
    requested: dict[str, int],
    produced: Counter[str] | None = None,
    rejects: dict[str, Counter[str]] | None = None,
) -> dict[str, dict[str, Any]]:
    produced = produced or Counter()
    rejects = rejects or {}
    return {
        kind: {
            "requested": count,
            "produced": produced[kind],
            "reject_reasons": _top_rejections(rejects.get(kind, Counter())),
        }
        for kind, count in requested.items()
    }


@router.post("", status_code=201)
def create_quiz(
    request: GenerationRequest, db: DatabaseSession, user: AuthenticatedUser
) -> dict[str, Any]:
    """Generate a bounded quiz from only the authenticated user's ready documents."""
    scoped_topic_names: dict[int, str] = {}
    syllabus_chunk_ids: set[int] | None = None
    if request.syllabus_id is not None:
        syllabus = db.scalar(
            select(Syllabus).where(
                Syllabus.id == request.syllabus_id, Syllabus.owner_id == user.id
            )
        )
        if syllabus is None:
            raise HTTPException(404, "Syllabus not found.")
        topic_query = select(SyllabusTopic).where(
            SyllabusTopic.syllabus_id == syllabus.id
        )
        if request.topic_ids:
            topic_query = topic_query.where(SyllabusTopic.id.in_(request.topic_ids))
        selected_topics = list(db.scalars(topic_query))
        if request.topic_ids and len(selected_topics) != len(set(request.topic_ids)):
            raise HTTPException(404, "One or more syllabus topics were not found.")
        scoped_topic_names = {topic.id: topic.title for topic in selected_topics}
        if selected_topics:
            syllabus_chunk_ids = set(
                db.scalars(
                    select(ChunkTopic.chunk_id).where(
                        ChunkTopic.topic_id.in_(scoped_topic_names),
                        ChunkTopic.source.in_(["auto", "manual"]),
                    )
                )
            )
        else:
            syllabus_chunk_ids = set()
        if not syllabus_chunk_ids:
            names = ", ".join(scoped_topic_names.values()) or "selected topics"
            return {
                "id": None,
                "title": request.title,
                "engine": request.engine,
                "questions": 0,
                "message": f"no material found for {names}",
                "report": {"accepted": 0},
            }
    document_ids = request.document_ids
    if not document_ids and syllabus_chunk_ids:
        document_ids = list(
            db.scalars(
                select(Chunk.doc_id).where(Chunk.id.in_(syllabus_chunk_ids)).distinct()
            )
        )
    documents = list(
        db.scalars(
            select(Document).where(
                Document.id.in_(document_ids),
                Document.owner_id == user.id,
                Document.status == "ready",
            )
        )
    )
    if len(documents) != len(set(document_ids)):
        raise HTTPException(
            status_code=404, detail="One or more ready documents were not found."
        )
    doc_by_id = {doc.id: doc for doc in documents}
    query = select(Chunk).where(Chunk.doc_id.in_(doc_by_id))
    if syllabus_chunk_ids is not None:
        query = query.where(Chunk.id.in_(syllabus_chunk_ids))
    if request.chunk_ids:
        query = query.where(Chunk.id.in_(request.chunk_ids))
    if request.page_start:
        query = query.where(Chunk.page_end >= request.page_start)
    if request.page_end:
        query = query.where(Chunk.page_start <= request.page_end)
    chunks = list(
        db.scalars(query.order_by(Chunk.doc_id, Chunk.chunk_index).limit(250))
    )
    if request.chunk_ids and len(chunks) != len(set(request.chunk_ids)):
        raise HTTPException(
            status_code=404,
            detail="One or more chunks were not found in the selected documents.",
        )
    if not chunks:
        raise HTTPException(
            status_code=422, detail="No source chunks match the quiz selection."
        )
    requested_by_type = _type_quotas(request)
    private_selected = any(doc_by_id[chunk.doc_id].is_private for chunk in chunks)
    if request.chapter:
        pages = list(
            db.scalars(
                select(DocumentPage)
                .where(DocumentPage.document_id.in_(doc_by_id))
                .order_by(DocumentPage.document_id, DocumentPage.page_number)
            )
        )
        ranges: dict[int, tuple[int, int]] = {}
        for document_id in doc_by_id:
            doc_pages = [page for page in pages if page.document_id == document_id]
            headings = [
                (page.page_number, str(heading["text"]).strip())
                for page in doc_pages
                for heading in page.headings or []
                if isinstance(heading, dict)
                and isinstance(heading.get("text"), str)
                and heading["text"].strip()
            ]
            for index, (start, title) in enumerate(headings):
                if title.casefold() != request.chapter.strip().casefold():
                    continue
                next_page = next(
                    (
                        page_number
                        for page_number, _ in headings[index + 1 :]
                        if page_number > start
                    ),
                    None,
                )
                end = (
                    next_page - 1
                    if next_page is not None
                    else max((page.page_number for page in doc_pages), default=start)
                )
                ranges[document_id] = (start, end)
                break
        if not ranges:
            raise HTTPException(status_code=404, detail="Chapter not found.")
        chunks = [
            chunk
            for chunk in chunks
            if chunk.doc_id in ranges
            and chunk.page_end >= ranges[chunk.doc_id][0]
            and chunk.page_start <= ranges[chunk.doc_id][1]
        ]
        if not chunks:
            raise HTTPException(
                status_code=422, detail="No source chunks match the chapter scope."
            )
        private_selected = any(doc_by_id[chunk.doc_id].is_private for chunk in chunks)

    if request.engine == "ai" and private_selected:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "AI quiz generation is not allowed for private documents.",
                "top_reject_reasons": {"private_document": 1},
                "by_type": _type_report(
                    requested_by_type,
                    rejects={
                        kind: Counter({"private_document": 1})
                        for kind in requested_by_type
                    },
                ),
            },
        )
    ai_engine: LLMEngine | None = None
    fallback_reason: str | None = (
        "private_document" if private_selected and request.engine != "offline" else None
    )
    if request.engine != "offline" and not private_selected:
        try:
            ai_engine = LLMEngine(_provider())
        except ProviderUnavailableError as error:
            if request.engine == "ai":
                raise HTTPException(
                    status_code=503,
                    detail={
                        "message": (
                            "AI quiz generation is unavailable: no provider is ready."
                        ),
                        "top_reject_reasons": {"provider_unavailable": 1},
                        "by_type": _type_report(
                            requested_by_type,
                            rejects={
                                kind: Counter({"provider_unavailable": 1})
                                for kind in requested_by_type
                            },
                        ),
                    },
                ) from error
            fallback_reason = "provider_unavailable"
    if request.engine == "ai" and ai_engine is None:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "AI quiz generation is unavailable.",
                "top_reject_reasons": {"provider_unavailable": 1},
                "by_type": _type_report(requested_by_type),
            },
        )

    offline = ClassicEngine()
    remaining = requested_by_type.copy()
    accepted: list[QuizQuestion] = []
    rejects: Counter[str] = Counter()
    rejects_by_type: dict[str, Counter[str]] = {
        kind: Counter() for kind in requested_by_type
    }
    attempted = 0
    terms_by_doc: dict[int, list[str]] = defaultdict(list)
    for term in db.scalars(
        select(DocumentKeyTerm).where(DocumentKeyTerm.document_id.in_(doc_by_id))
    ):
        terms_by_doc[term.document_id].append(term.term)
    generated_engines: set[str] = set()

    def reject(reason: str, kind: str, count: int = 1) -> None:
        rejects[reason] += count
        if kind in rejects_by_type:
            rejects_by_type[kind][reason] += count

    def generate_for_chunk(
        engine: Any,
        chunk: Chunk,
        *,
        engine_label: str,
    ) -> None:
        nonlocal attempted, ai_engine, fallback_reason
        mapped_ids = (
            list(
                db.scalars(
                    select(ChunkTopic.topic_id)
                    .where(
                        ChunkTopic.chunk_id == chunk.id,
                        ChunkTopic.topic_id.in_(scoped_topic_names)
                        if scoped_topic_names
                        else False,
                    )
                    .order_by(ChunkTopic.score.desc())
                )
            )
            if request.syllabus_id is not None
            else []
        )
        topic = (
            scoped_topic_names[mapped_ids[0]]
            if mapped_ids
            else chunk.section or (request.topics[0] if request.topics else "General")
        )
        topic = topic or chunk.section or "General"
        chunk.key_terms = terms_by_doc[chunk.doc_id]
        source_text = clean_chunk_text(chunk.text)
        generation_chunk = SimpleNamespace(
            id=chunk.id,
            page=chunk.page,
            text=source_text,
            key_terms=chunk.key_terms,
            difficulty_label=chunk.difficulty_label,
        )
        cycle = _type_cycle(remaining)
        if not cycle:
            return
        try:
            generated = engine.generate(
                generation_chunk,
                topic=topic,
                difficulty=request.difficulty.value if request.difficulty else None,
                question_quota=min(3, sum(remaining.values()))
                if engine_label == "offline"
                else sum(remaining.values()),
                type_cycle=cycle,
            )
            if engine_label == "ai":
                provider = getattr(engine, "provider", None)
                provider_name = getattr(provider, "last_provider", "") or getattr(
                    provider, "name", ""
                )
                for item in generated:
                    item.provider = item.provider or provider_name or None
        except (
            StructuredOutputError,
            RateLimitError,
            ProviderError,
            ProviderUnavailableError,
            ValueError,
            OSError,
        ) as error:
            reason = (
                "ai_rate_limited"
                if isinstance(error, RateLimitError)
                else "ai_generation_failed"
            )
            rejects[reason] += 1
            for kind, quota in remaining.items():
                if quota:
                    rejects_by_type[kind][reason] += 1
            if request.engine == "ai":
                status = 429 if isinstance(error, RateLimitError) else 502
                raise HTTPException(
                    status_code=status,
                    detail={
                        "message": (
                            "AI quiz generation failed; no offline fallback was "
                            "requested."
                        ),
                        "top_reject_reasons": _top_rejections(rejects),
                        "by_type": _type_report(
                            requested_by_type,
                            Counter(item.type.value for item in accepted),
                            rejects_by_type,
                        ),
                    },
                ) from error
            fallback_reason = reason
            ai_engine = None
            return
        if engine_label == "offline":
            for reason, count in getattr(engine, "last_rejections", {}).items():
                rejects[reason] += count
                for kind, quota in remaining.items():
                    if quota:
                        rejects_by_type[kind][reason] += count
        for candidate in generated:
            attempted += 1
            kind = candidate.type.value
            if kind not in remaining:
                reject("unrequested_question_type", kind)
                continue
            if remaining[kind] <= 0:
                reject("type_quota_exceeded", kind)
                continue
            if request.difficulty and candidate.difficulty != request.difficulty:
                reject("difficulty_mismatch", kind)
                continue
            candidate.engine = engine_label
            try:
                ok, reason = validate_generated(
                    candidate,
                    source_text,
                    qa_model=offline.qa_model,
                    round_trip_threshold=get_settings().quiz_round_trip_f1_threshold,
                    prior_questions=[item.question for item in accepted],
                    similarity=embedding_similarity,
                    key_terms=terms_by_doc[chunk.doc_id],
                )
            except OSError:
                reject("qa_model_unavailable", kind)
                continue
            if not ok:
                reject(reason, kind)
                continue
            if request.syllabus_id is not None:
                candidate.topic = topic
            accepted.append(candidate)
            remaining[kind] -= 1
            generated_engines.add(engine_label)

    for chunk in chunks:
        if request.topics and not any(
            topic.casefold() in (chunk.section or "").casefold()
            or any(
                topic.casefold() in term.casefold()
                for term in terms_by_doc[chunk.doc_id]
            )
            for topic in request.topics
        ):
            continue
        if ai_engine is not None and request.engine != "offline":
            generate_for_chunk(ai_engine, chunk, engine_label="ai")
        if not any(remaining.values()):
            break

    if request.engine in {"offline", "auto"} and any(remaining.values()):
        if ai_engine is not None and request.engine == "auto":
            fallback_reason = fallback_reason or "offline_top_up"
        for chunk in chunks:
            if not any(remaining.values()):
                break
            if request.topics and not any(
                topic.casefold() in (chunk.section or "").casefold()
                or any(
                    topic.casefold() in term.casefold()
                    for term in terms_by_doc[chunk.doc_id]
                )
                for topic in request.topics
            ):
                continue
            generate_for_chunk(offline, chunk, engine_label="offline")

    before_balance = len(accepted)
    accepted = balance_true_false_questions(accepted)
    balance_rejected = before_balance - len(accepted)
    if balance_rejected:
        rejects["quiz_true_false_balance"] += balance_rejected
        rejects_by_type["true_false"]["quiz_true_false_balance"] += balance_rejected
    produced_by_type = Counter(item.type.value for item in accepted)
    for kind, requested in requested_by_type.items():
        missing = requested - produced_by_type[kind]
        if missing:
            rejects["insufficient_valid_questions"] += missing
            rejects_by_type[kind]["insufficient_valid_questions"] += missing
    report_by_type = _type_report(requested_by_type, produced_by_type, rejects_by_type)
    report = {
        "accepted": len(accepted),
        "rejected": _top_rejections(rejects),
        "top_reject_reasons": _top_rejections(rejects),
        "attempted": attempted,
        "requested_engine": request.engine,
        "engines_used": sorted(generated_engines),
        "fallback_reason": fallback_reason,
        "difficulty_mix": dict(Counter(q.difficulty.value for q in accepted)),
        "by_type": report_by_type,
    }
    if not accepted:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "No questions passed validation.",
                "top_reject_reasons": _top_rejections(rejects),
                "by_type": report_by_type,
            },
        )
    quiz = Quiz(
        owner_id=user.id,
        title=request.title,
        source_document_id=documents[0].id,
        engine=request.engine,
        generation_report=report,
    )
    db.add(quiz)
    db.flush()
    for item in accepted:
        db.add(
            Question(
                quiz_id=quiz.id,
                type=item.type.value,
                difficulty=item.difficulty.value,
                prompt=item.question,
                options={
                    "choices": item.options,
                    "provider": item.provider,
                    "evidence": item.evidence,
                    "document_id": next(
                        (c.doc_id for c in chunks if c.id == item.source_chunk_id),
                        documents[0].id,
                    ),
                },
                answer=item.correct_answer,
                explanation=item.explanation,
                source_chunk_id=item.source_chunk_id,
                engine=item.engine,
                topic=item.topic,
                syllabus_topic_id=next(
                    (
                        topic_id
                        for topic_id, title in scoped_topic_names.items()
                        if title == item.topic
                        and db.scalar(
                            select(ChunkTopic.id).where(
                                ChunkTopic.chunk_id == item.source_chunk_id,
                                ChunkTopic.topic_id == topic_id,
                            )
                        )
                    ),
                    None,
                )
                if request.syllabus_id is not None
                else None,
                page=item.page,
            )
        )
    db.commit()
    return {
        "id": quiz.id,
        "title": quiz.title,
        "engine": quiz.engine,
        "questions": len(accepted),
        "report": report,
    }


@router.get("")
def list_quizzes(
    db: DatabaseSession,
    user: AuthenticatedUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    quizzes = db.scalars(
        select(Quiz)
        .where(Quiz.owner_id == user.id)
        .order_by(Quiz.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return [
        {
            "id": item.id,
            "title": item.title,
            "engine": item.engine,
            "generation_report": item.generation_report,
        }
        for item in quizzes
    ]


@router.get("/{quiz_id}")
def get_quiz(
    quiz_id: int, db: DatabaseSession, user: AuthenticatedUser
) -> dict[str, Any]:
    quiz = _quiz_or_404(db, quiz_id, user.id)
    questions = db.scalars(
        select(Question).where(Question.quiz_id == quiz.id).order_by(Question.id)
    )
    return {
        "id": quiz.id,
        "title": quiz.title,
        "engine": quiz.engine,
        "report": quiz.generation_report,
        "questions": [_question_payload(item) for item in questions],
    }


@router.get("/{quiz_id}/questions/{question_id}/explanation")
def question_explanation(
    quiz_id: int,
    question_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Return the explanation and owner-scoped source page link."""
    quiz = _quiz_or_404(db, quiz_id, user.id)
    question = db.scalar(
        select(Question).where(
            Question.id == question_id,
            Question.quiz_id == quiz.id,
        )
    )
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found.")
    metadata = question.options if isinstance(question.options, dict) else {}
    return {
        "question_id": question.id,
        "explanation": question.explanation,
        "source_chunk_id": question.source_chunk_id,
        "page": question.page,
        "source_page_url": (
            f"/documents/{metadata.get('document_id', '')}/pages/{question.page}"
        ),
    }


@router.post("/{quiz_id}/attempts", status_code=201)
def start_attempt(
    quiz_id: int, db: DatabaseSession, user: AuthenticatedUser
) -> dict[str, int]:
    quiz = _quiz_or_404(db, quiz_id, user.id)
    attempt = QuizAttempt(quiz_id=quiz.id, user_id=user.id)
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return {"attempt_id": attempt.id, "quiz_id": quiz.id}


@router.post("/{quiz_id}/attempts/{attempt_id}/submit")
def submit_answers(
    quiz_id: int,
    attempt_id: int,
    request: SubmitAnswers,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    quiz = _quiz_or_404(db, quiz_id, user.id)
    attempt = db.scalar(
        select(QuizAttempt).where(
            QuizAttempt.id == attempt_id,
            QuizAttempt.quiz_id == quiz.id,
            QuizAttempt.user_id == user.id,
        )
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found.")
    questions = {
        item.id: item
        for item in db.scalars(select(Question).where(Question.quiz_id == quiz.id))
    }
    if any(item.question_id not in questions for item in request.answers):
        raise HTTPException(
            status_code=422, detail="Answer contains a question outside this quiz."
        )
    if len({item.question_id for item in request.answers}) != len(request.answers):
        raise HTTPException(
            status_code=422, detail="Each question may be answered only once."
        )
    existing = {item.question_id: item for item in attempt.answers}
    chunk_ids = {
        item.source_chunk_id
        for item in questions.values()
        if item.source_chunk_id is not None
    }
    source_chunks = (
        {
            chunk.id: chunk
            for chunk in db.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids)))
        }
        if chunk_ids
        else {}
    )
    document_ids = {chunk.doc_id for chunk in source_chunks.values()}
    terms_by_document: dict[int, list[DocumentKeyTerm]] = defaultdict(list)
    if document_ids:
        for term in db.scalars(
            select(DocumentKeyTerm).where(DocumentKeyTerm.document_id.in_(document_ids))
        ):
            terms_by_document[term.document_id].append(term)
    if attempt.completed_at is not None:
        stored_results = []
        previous_by_topic: dict[str, list[bool]] = defaultdict(list)
        for item in attempt.answers:
            question = questions.get(item.question_id)
            if question is None or item.is_correct is None:
                continue
            metadata = question.options if isinstance(question.options, dict) else {}
            stored_results.append(
                {
                    "question_id": item.question_id,
                    "is_correct": item.is_correct,
                    "correct_answer": question.answer,
                    "explanation": question.explanation,
                    "source_page_url": (
                        f"/documents/{metadata.get('document_id', '')}"
                        f"/pages/{question.page}"
                    ),
                }
            )
            previous_by_topic[
                _source_topic(question, source_chunks, terms_by_document)
            ].append(item.is_correct)
        return {
            "attempt_id": attempt.id,
            "score": attempt.score,
            "correct": sum(item["is_correct"] for item in stored_results),
            "total": len(stored_results),
            "topic_breakdown": {
                topic: {"correct": sum(outcomes), "total": len(outcomes)}
                for topic, outcomes in previous_by_topic.items()
            },
            "results": stored_results,
        }
    results = []
    by_topic: dict[str, list[bool]] = defaultdict(list)
    rubric_provider = None
    if not any(
        (
            db.get(Chunk, item.source_chunk_id).document.is_private
            if item.source_chunk_id and db.get(Chunk, item.source_chunk_id)
            else False
        )
        for item in questions.values()
    ):
        try:
            rubric_provider = _provider()
        except ProviderUnavailableError:
            pass
    for submitted in request.answers:
        question = questions[submitted.question_id]
        metadata = question.options if isinstance(question.options, dict) else {}
        rubric = None
        if question.type == "short_answer" and rubric_provider is not None:

            def score_with_rubric(response: str, expected: str) -> float | None:
                rubric_prompt = (
                    "Score the student response from 0 to 1 against "
                    "the expected answer. "
                    'Return JSON {"score": number}.\n'
                    f"Expected: {expected}\nStudent: {response}"
                )
                try:
                    raw = rubric_provider.generate(
                        rubric_prompt,
                        "Use only answer equivalence and factual coverage. JSON only.",
                    )
                    import json

                    return float(json.loads(raw)["score"])
                except (
                    ProviderError,
                    ProviderUnavailableError,
                    RateLimitError,
                    ValueError,
                ):
                    return None

            rubric = score_with_rubric
        is_correct = grade_answer(
            submitted.answer,
            question.answer,
            question_type=question.type,
            rubric=rubric,
        )
        record = existing.get(question.id)
        if record is None:
            record = AttemptAnswer(attempt_id=attempt.id, question_id=question.id)
            db.add(record)
        record.answer, record.is_correct = submitted.answer, is_correct
        by_topic[_source_topic(question, source_chunks, terms_by_document)].append(
            is_correct
        )
        results.append(
            {
                "question_id": question.id,
                "is_correct": is_correct,
                "correct_answer": question.answer,
                "explanation": question.explanation,
                "source_page_url": (
                    f"/documents/{metadata.get('document_id', '')}"
                    f"/pages/{question.page}"
                ),
            }
        )
    total = len(request.answers)
    score = sum(item["is_correct"] for item in results) / total if total else 0
    attempt.score = score
    attempt.completed_at = datetime.now(UTC)
    for topic, outcomes in by_topic.items():
        stat = db.scalar(
            select(TopicStat).where(
                TopicStat.owner_id == user.id, TopicStat.topic == topic
            )
        )
        if stat is None:
            stat = TopicStat(owner_id=user.id, topic=topic, attempts=0, correct=0)
            db.add(stat)
        stat.attempts += len(outcomes)
        stat.correct += sum(outcomes)
        stat.accuracy = stat.correct / stat.attempts
        stat.last_seen = attempt.completed_at
    db.commit()
    return {
        "attempt_id": attempt.id,
        "score": score,
        "correct": sum(item["is_correct"] for item in results),
        "total": total,
        "topic_breakdown": {
            topic: {"correct": sum(outcomes), "total": len(outcomes)}
            for topic, outcomes in by_topic.items()
        },
        "results": results,
    }


@router.get("/{quiz_id}/results/{attempt_id}")
def results(
    quiz_id: int, attempt_id: int, db: DatabaseSession, user: AuthenticatedUser
) -> dict[str, Any]:
    quiz = _quiz_or_404(db, quiz_id, user.id)
    attempt = db.scalar(
        select(QuizAttempt).where(
            QuizAttempt.id == attempt_id,
            QuizAttempt.quiz_id == quiz.id,
            QuizAttempt.user_id == user.id,
        )
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found.")
    rows = db.execute(
        select(AttemptAnswer, Question)
        .join(Question)
        .where(AttemptAnswer.attempt_id == attempt.id)
    ).all()
    by_topic: dict[str, list[bool]] = defaultdict(list)
    for answer, question in rows:
        by_topic[question.topic].append(bool(answer.is_correct))
    return {
        "attempt_id": attempt.id,
        "score": attempt.score,
        "topic_breakdown": {
            key: {"correct": sum(value), "total": len(value)}
            for key, value in by_topic.items()
        },
        "answers": [
            {
                "question_id": answer.question_id,
                "is_correct": answer.is_correct,
                "explanation": question.explanation,
                "source_page_url": (
                    f"/documents/{(question.options or {}).get('document_id', '')}"
                    f"/pages/{question.page}"
                ),
            }
            for answer, question in rows
        ],
    }


@router.post("/{quiz_id}/retake", status_code=201)
def retake(
    quiz_id: int, attempt_id: int, db: DatabaseSession, user: AuthenticatedUser
) -> dict[str, Any]:
    quiz = _quiz_or_404(db, quiz_id, user.id)
    attempt = db.scalar(
        select(QuizAttempt).where(
            QuizAttempt.id == attempt_id,
            QuizAttempt.quiz_id == quiz.id,
            QuizAttempt.user_id == user.id,
        )
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found.")
    ids = [item.question_id for item in attempt.answers]
    answers = {item.question_id: bool(item.is_correct) for item in attempt.answers}
    weak = set(weak_question_ids(ids, answers))
    rows = (
        list(
            db.scalars(
                select(Question).where(Question.id.in_(weak)).order_by(Question.id)
            )
        )
        if weak
        else []
    )
    retry = Quiz(
        owner_id=user.id,
        title=f"{quiz.title} — retake",
        source_document_id=quiz.source_document_id,
        engine=quiz.engine,
        generation_report={"retake_of": quiz.id, "weak_question_count": len(rows)},
    )
    db.add(retry)
    db.flush()
    for item in rows:
        db.add(
            Question(
                quiz_id=retry.id,
                type=item.type,
                difficulty=item.difficulty,
                prompt=item.prompt,
                options=item.options,
                answer=item.answer,
                explanation=item.explanation,
                source_chunk_id=item.source_chunk_id,
                engine=item.engine,
                topic=item.topic,
                page=item.page,
            )
        )
    db.commit()
    db.refresh(retry)
    return {
        "id": retry.id,
        "source_quiz_id": quiz.id,
        "title": retry.title,
        "questions": [_question_payload(item) for item in retry.questions],
    }


@router.get("/{quiz_id}/exam.{format}")
def exam(
    quiz_id: int,
    format: str,
    db: DatabaseSession,
    user: AuthenticatedUser,
    marks_per_question: Annotated[int, Query(ge=1, le=100)] = 1,
) -> Response:
    quiz = _quiz_or_404(db, quiz_id, user.id)
    if format not in {"pdf", "docx"}:
        raise HTTPException(
            status_code=404, detail="Exam export format must be pdf or docx."
        )
    questions = db.scalars(
        select(Question).where(Question.quiz_id == quiz.id).order_by(Question.id)
    )
    sections: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in questions:
        options = item.options if isinstance(item.options, dict) else {}
        sections[item.type.replace("_", " ").title()].append(
            {
                "question": item.prompt,
                "options": options.get(
                    "choices", item.options if isinstance(item.options, list) else None
                ),
                "correct_answer": item.answer,
                "explanation": item.explanation or "",
            }
        )
    content = (
        export_pdf(quiz.title, sections, marks_per_question)
        if format == "pdf"
        else export_docx(quiz.title, sections, marks_per_question)
    )
    media = (
        "application/pdf"
        if format == "pdf"
        else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return Response(
        content,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="quiz-{quiz.id}.{format}"'
        },
    )
