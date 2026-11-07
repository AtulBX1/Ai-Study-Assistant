"""Authenticated, owner-scoped quiz generation and attempt endpoints."""

from collections import Counter, defaultdict
from datetime import UTC, datetime
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
    Document,
    DocumentKeyTerm,
    Question,
    Quiz,
    QuizAttempt,
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
        if name == "gemini":
            configured.append(GeminiProvider())
        elif name == "groq":
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


@router.post("", status_code=201)
def create_quiz(
    request: GenerationRequest, db: DatabaseSession, user: AuthenticatedUser
) -> dict[str, Any]:
    """Generate a bounded quiz from only the authenticated user's ready documents."""
    documents = list(
        db.scalars(
            select(Document).where(
                Document.id.in_(request.document_ids),
                Document.owner_id == user.id,
                Document.status == "ready",
            )
        )
    )
    if len(documents) != len(set(request.document_ids)):
        raise HTTPException(
            status_code=404, detail="One or more ready documents were not found."
        )
    doc_by_id = {doc.id: doc for doc in documents}
    query = select(Chunk).where(Chunk.doc_id.in_(doc_by_id))
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
    private_selected = any(doc_by_id[chunk.doc_id].is_private for chunk in chunks)
    engine_name = request.engine
    fallback_reason = None
    llm = None
    if engine_name == "llm":
        if private_selected:
            fallback_reason = "private_document"
        else:
            try:
                llm = LLMEngine(_provider())
            except ProviderUnavailableError:
                fallback_reason = "provider_unavailable"
        if fallback_reason:
            engine_name = "classic"
    classic = ClassicEngine()
    accepted: list[QuizQuestion] = []
    rejects: Counter[str] = Counter()
    attempted = 0
    # Load per-document term candidates without disclosing source text to a provider.
    terms_by_doc: dict[int, list[str]] = defaultdict(list)
    for term in db.scalars(
        select(DocumentKeyTerm).where(DocumentKeyTerm.document_id.in_(doc_by_id))
    ):
        terms_by_doc[term.document_id].append(term.term)
    for chunk in chunks:
        if len(accepted) >= request.question_count:
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
        chunk.key_terms = terms_by_doc[chunk.doc_id]
        topic = chunk.section or (request.topics[0] if request.topics else "General")
        active = llm if engine_name == "llm" and fallback_reason is None else classic
        try:
            generated = active.generate(
                chunk,
                topic=topic,
                difficulty=request.difficulty.value if request.difficulty else None,
            )
            if active is llm and isinstance(llm.provider, ProviderChain):
                for item in generated:
                    item.provider = llm.provider.last_provider or "unknown"
        except StructuredOutputError as error:
            rejects["llm_parse_failure"] += error.parse_failures
            fallback_reason, llm, engine_name = (
                "invalid_structured_output",
                None,
                "classic",
            )
            active = classic
            generated = classic.generate(
                chunk,
                topic=topic,
                difficulty=request.difficulty.value if request.difficulty else None,
            )
        except RateLimitError:
            rejects["llm_parse_failure"] += getattr(llm, "last_parse_failures", 0)
            fallback_reason, llm = "rate_limited", None
            engine_name = "classic"
            active = classic
            generated = classic.generate(
                chunk,
                topic=topic,
                difficulty=request.difficulty.value if request.difficulty else None,
            )
        except (ProviderError, ProviderUnavailableError, ValueError, OSError):
            if engine_name == "llm":
                rejects["llm_parse_failure"] += getattr(llm, "last_parse_failures", 0)
                fallback_reason, llm, engine_name = "provider_error", None, "classic"
                active = classic
                generated = classic.generate(
                    chunk,
                    topic=topic,
                    difficulty=request.difficulty.value if request.difficulty else None,
                )
            else:
                rejects["generation_error"] += 1
                continue
        if active is classic:
            rejects.update(getattr(classic, "last_rejections", {}))
        for candidate in generated:
            attempted += 1
            candidate.engine = engine_name
            if request.difficulty and candidate.difficulty != request.difficulty:
                rejects["difficulty_mismatch"] += 1
                continue
            try:
                ok, reason = validate_generated(
                    candidate,
                    clean_chunk_text(chunk.text) if active is classic else chunk.text,
                    qa_model=classic.qa_model,
                    round_trip_threshold=get_settings().quiz_round_trip_f1_threshold,
                    prior_questions=[item.question for item in accepted],
                    similarity=embedding_similarity,
                )
            except OSError:
                rejects["qa_model_unavailable"] += 1
                continue
            if not ok:
                rejects[reason] += 1
                continue
            accepted.append(candidate)
            if len(accepted) >= request.question_count:
                break
    if not accepted:
        raise HTTPException(
            status_code=422,
            detail={"message": "No questions passed validation.", "rejects": rejects},
        )
    before_balance = len(accepted)
    accepted = balance_true_false_questions(accepted)
    if len(accepted) < before_balance:
        rejects["quiz_true_false_balance"] += before_balance - len(accepted)
    if not accepted:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "No balanced true/false questions passed validation.",
                "rejects": rejects,
            },
        )
    report = {
        "accepted": len(accepted),
        "rejected": dict(rejects),
        "attempted": attempted,
        "requested_engine": request.engine,
        "fallback_reason": fallback_reason,
        "difficulty_mix": dict(Counter(q.difficulty.value for q in accepted)),
    }
    quiz = Quiz(
        owner_id=user.id,
        title=request.title,
        source_document_id=documents[0].id,
        engine=engine_name,
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
