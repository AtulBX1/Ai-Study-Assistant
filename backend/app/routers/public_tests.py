"""Public, snapshot-based test library and handle-only rankings."""

from re import IGNORECASE, escape, split, sub
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.cache import Cache
from app.core.config import get_settings
from app.dependencies.auth import DatabaseSession, get_current_user, require_role
from app.models import (
    Chunk,
    Document,
    PublicTest,
    PublicTestAttempt,
    Question,
    Quiz,
    User,
)
from app.models.entities import utc_now
from app.services import public_tests

router = APIRouter(prefix="/public-tests", tags=["public tests"])
AuthenticatedUser = Annotated[User, Depends(get_current_user)]
Student = Annotated[User, Depends(require_role("student"))]
Admin = Annotated[User, Depends(require_role("admin"))]


class TestMetadata(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    subject: str = Field(min_length=1, max_length=120)
    topic_labels: list[str] = Field(default_factory=list, max_length=30)
    time_limit_seconds: int = Field(ge=1, le=7_200)


class CreateFromQuiz(BaseModel):
    quiz_id: int = Field(gt=0)
    metadata: TestMetadata


class StudentSubmission(CreateFromQuiz):
    rights_confirmed: bool = False


class MetadataUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    subject: str | None = Field(default=None, min_length=1, max_length=120)
    topic_labels: list[str] | None = Field(default=None, max_length=30)
    time_limit_seconds: int | None = Field(default=None, ge=1, le=7_200)


class StatusUpdate(BaseModel):
    status: Literal["approved", "rejected", "hidden"]


class AnswerEntry(BaseModel):
    question_id: int = Field(ge=0)
    answer: str = Field(max_length=2000)


class AnswerSet(BaseModel):
    answers: list[AnswerEntry] = Field(default_factory=list, max_length=100)
    submission_token: str = Field(min_length=30, max_length=100)


class ReportRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


def _cache(request: Request) -> Cache:
    return request.app.state.rate_limit_cache


def _approved_test(db: Session, test_id: int) -> PublicTest:
    test = db.scalar(
        select(PublicTest).where(
            PublicTest.id == test_id, PublicTest.status == "approved"
        )
    )
    if test is None:
        raise HTTPException(status_code=404, detail="Public test not found.")
    return test


def _strip_source_name(value: object, name: str) -> object:
    if isinstance(value, str):
        return sub(escape(name), "", value, flags=IGNORECASE).strip()
    if isinstance(value, dict):
        return {key: _strip_source_name(item, name) for key, item in value.items()}
    return value


def _snapshot_from_quiz(db: Session, quiz: Quiz) -> list[dict]:
    questions = list(
        db.scalars(
            select(Question).where(Question.quiz_id == quiz.id).order_by(Question.id)
        )
    )
    snapshot = public_tests.snapshot_questions(questions)
    if not snapshot:
        raise HTTPException(status_code=422, detail="Quiz has no questions.")
    source_names = []
    if quiz.source_document_id is not None:
        source_document = db.get(Document, quiz.source_document_id)
        if source_document is not None:
            source_names.append(source_document.title)
    chunk_ids = {
        question.source_chunk_id
        for question in questions
        if question.source_chunk_id is not None
    }
    source_texts = []
    if chunk_ids:
        chunks = db.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids)))
        for chunk in chunks:
            source_texts.extend(
                sentence.strip()
                for sentence in split(r"(?<=[.!?])\s+", chunk.text)
                if len(sentence.strip()) >= 20
            )
            document = db.get(Document, chunk.doc_id)
            if document is not None:
                source_names.append(document.title)
    for question in snapshot:
        for name in source_names:
            if name:
                for field in ("question", "correct_answer", "explanation"):
                    question[field] = _strip_source_name(question[field], name)
                question["options"] = [
                    _strip_source_name(option, name) for option in question["options"]
                ]
        if any(
            text.casefold()
            in " ".join(
                [
                    question["question"],
                    question["correct_answer"],
                    *(
                        value
                        for option in question["options"]
                        for value in (
                            option.values() if isinstance(option, dict) else [option]
                        )
                        if isinstance(value, str)
                    ),
                ]
            ).casefold()
            for text in source_texts
        ):
            raise HTTPException(
                status_code=422,
                detail="Quiz contains source page text and cannot be shared.",
            )
        if any(
            text.casefold() in question["explanation"].casefold()
            for text in source_texts
        ):
            question["explanation"] = ""
    return snapshot


def _test_payload(db: Session, test: PublicTest) -> dict[str, object]:
    creator = db.get(User, test.created_by)
    if test.is_demo and get_settings().backend != "local":
        popularity = 0
    else:
        popularity_query = select(func.count(PublicTestAttempt.id)).where(
            PublicTestAttempt.test_id == test.id,
            PublicTestAttempt.completed_at.is_not(None),
        )
        if get_settings().backend == "prod":
            popularity_query = popularity_query.where(
                PublicTestAttempt.is_demo.is_(False)
            )
        popularity = db.scalar(popularity_query)
    return {
        "test_id": test.id,
        "title": test.title,
        "description": test.description,
        "subject": test.subject,
        "topic_labels": test.topic_labels,
        "time_limit_seconds": test.time_limit_seconds,
        "question_count": test.question_count,
        "created_by": (
            creator.public_handle
            if creator is not None and creator.show_on_leaderboards
            else "Anonymous"
        ),
        "created_at": test.created_at.isoformat(),
        "popularity": int(popularity or 0),
        "questions": [
            {
                "question_id": row["id"],
                "question": row["question"],
                "type": row["type"],
                "options": row["options"],
                "topic": row["topic"],
                "difficulty": row["difficulty"],
            }
            for row in test.snapshot
        ],
    }


def _create_test(
    db: Session,
    quiz: Quiz,
    user: User,
    metadata: TestMetadata,
) -> PublicTest:
    snapshot = _snapshot_from_quiz(db, quiz)
    test = PublicTest(
        title=metadata.title.strip(),
        description=metadata.description.strip() if metadata.description else None,
        subject=metadata.subject.strip(),
        topic_labels=[
            label.strip() for label in metadata.topic_labels if label.strip()
        ],
        time_limit_seconds=metadata.time_limit_seconds,
        question_count=len(snapshot),
        snapshot=snapshot,
        status="pending",
        created_by=user.id,
        source_quiz_id=quiz.id,
    )
    db.add(test)
    return test


@router.get("")
def list_public_tests(
    db: DatabaseSession,
    subject: str | None = None,
    topic: str | None = None,
    search: str | None = Query(default=None, max_length=120),
    sort: Literal["newest", "popularity"] = "newest",
) -> list[dict[str, object]]:
    """List only approved tests and return no private user information."""
    query = select(PublicTest).where(PublicTest.status == "approved")
    if subject:
        query = query.where(func.lower(PublicTest.subject) == subject.strip().lower())
    if topic:
        tests = list(db.scalars(query))
        tests = [item for item in tests if topic in item.topic_labels]
    else:
        tests = list(db.scalars(query))
    if search:
        match = f"%{search.strip()}%"
        query = query.where(
            PublicTest.title.ilike(match)
            | PublicTest.description.ilike(match)
            | PublicTest.subject.ilike(match)
        )
        tests = [
            item
            for item in tests
            if search.strip().casefold()
            in " ".join((item.title, item.description or "", item.subject)).casefold()
        ]
    payloads = [_test_payload(db, item) for item in tests]
    if sort == "popularity":
        payloads.sort(key=lambda item: (-int(item["popularity"]), -item["test_id"]))
    else:
        payloads.sort(key=lambda item: str(item["created_at"]), reverse=True)
    return payloads


@router.get("/leaderboards/accuracy")
def global_accuracy_leaderboard(
    db: DatabaseSession,
    user: AuthenticatedUser,
    window: Literal["weekly", "all-time"] = "all-time",
) -> dict[str, object]:
    return public_tests.accuracy_leaderboard(
        db, window=window, caller=user, clock=utc_now
    )


@router.get("/me/overview")
def my_public_test_overview(
    db: DatabaseSession, user: AuthenticatedUser
) -> dict[str, object]:
    return public_tests.personal_overview(db, user)


@router.get("/{test_id}")
def get_public_test(
    test_id: int,
    db: DatabaseSession,
) -> dict[str, object]:
    return _test_payload(db, _approved_test(db, test_id))


@router.get("/{test_id}/statistics")
def get_public_test_statistics(test_id: int, db: DatabaseSession) -> dict[str, object]:
    test = _approved_test(db, test_id)
    return public_tests.test_statistics(db, test)


@router.get("/{test_id}/leaderboard")
def get_public_test_leaderboard(
    test_id: int, db: DatabaseSession, user: AuthenticatedUser
) -> dict[str, object]:
    return public_tests.test_leaderboard(db, _approved_test(db, test_id), caller=user)


@router.post("/admin/tests/from-quiz", status_code=201)
def admin_create_from_quiz(
    request: CreateFromQuiz,
    db: DatabaseSession,
    user: Admin,
) -> dict[str, object]:
    quiz = db.get(Quiz, request.quiz_id)
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    test = _create_test(db, quiz, user, request.metadata)
    db.commit()
    db.refresh(test)
    return {"test_id": test.id, "status": test.status}


@router.post("/submissions", status_code=201)
def submit_quiz_for_publication(
    request: StudentSubmission,
    db: DatabaseSession,
    user: Student,
) -> dict[str, object]:
    if request.rights_confirmed is not True:
        raise HTTPException(
            status_code=422,
            detail="Confirm that you have the right to share this content.",
        )
    quiz = db.scalar(
        select(Quiz).where(Quiz.id == request.quiz_id, Quiz.owner_id == user.id)
    )
    if quiz is None:
        raise HTTPException(status_code=404, detail="Quiz not found.")
    test = _create_test(db, quiz, user, request.metadata)
    db.commit()
    db.refresh(test)
    return {"test_id": test.id, "status": test.status}


@router.get("/admin/queue")
def get_review_queue(db: DatabaseSession, _: Admin) -> list[dict[str, object]]:
    return public_tests.report_queue(db)


@router.patch("/admin/tests/{test_id}")
def edit_test_metadata(
    test_id: int,
    request: MetadataUpdate,
    db: DatabaseSession,
    _: Admin,
) -> dict[str, object]:
    test = db.get(PublicTest, test_id)
    if test is None:
        raise HTTPException(status_code=404, detail="Public test not found.")
    for field, value in request.model_dump(exclude_unset=True).items():
        if field in {"title", "subject"} and value is not None:
            value = value.strip()
        if field == "topic_labels" and value is not None:
            value = [item.strip() for item in value if item.strip()]
        setattr(test, field, value)
    db.commit()
    return {"test_id": test.id, "status": test.status}


@router.patch("/admin/tests/{test_id}/status")
def moderate_test(
    test_id: int,
    request: StatusUpdate,
    db: DatabaseSession,
    _: Admin,
) -> dict[str, object]:
    test = db.get(PublicTest, test_id)
    if test is None:
        raise HTTPException(status_code=404, detail="Public test not found.")
    test.status = request.status
    db.commit()
    return {"test_id": test.id, "status": test.status}


@router.post("/{test_id}/reports", status_code=201)
def report_test(
    test_id: int,
    request: ReportRequest,
    db: DatabaseSession,
    user: AuthenticatedUser,
    http_request: Request,
) -> dict[str, str]:
    test = _approved_test(db, test_id)
    try:
        public_tests.report_public_test(
            db, test, user, request.reason, cache=_cache(http_request)
        )
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="You have already reported this test."
        ) from error
    return {"status": "reported"}


@router.post("/{test_id}/attempts", status_code=201)
def start_test_attempt(
    test_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
    request: Request,
) -> dict[str, object]:
    test = _approved_test(db, test_id)
    attempt, token = public_tests.start_public_attempt(
        db, test, user, cache=_cache(request)
    )
    db.commit()
    return {
        "attempt_id": attempt.id,
        "time_limit_seconds": test.time_limit_seconds,
        "submission_token": token,
        "questions": [
            {
                "question_id": test.snapshot[index]["id"],
                "question": test.snapshot[index]["question"],
                "type": test.snapshot[index]["type"],
                "options": test.snapshot[index]["options"],
                "topic": test.snapshot[index]["topic"],
                "difficulty": test.snapshot[index]["difficulty"],
            }
            for index in attempt.shuffled_order
        ],
    }


def _owned_attempt(
    db: Session, test_id: int, attempt_id: int, user: User
) -> tuple[PublicTest, PublicTestAttempt]:
    test = _approved_test(db, test_id)
    attempt = db.scalar(
        select(PublicTestAttempt)
        .where(
            PublicTestAttempt.id == attempt_id,
            PublicTestAttempt.test_id == test.id,
            PublicTestAttempt.user_id == user.id,
        )
        .with_for_update()
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Attempt not found.")
    return test, attempt


@router.put("/{test_id}/attempts/{attempt_id}/answers")
def save_test_answers(
    test_id: int,
    attempt_id: int,
    request: AnswerSet,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, int]:
    test, attempt = _owned_attempt(db, test_id, attempt_id, user)
    count = public_tests.save_public_answers(
        test,
        attempt,
        answers=_answer_map(request),
        token=request.submission_token,
    )
    db.commit()
    return {"saved_answers": count}


@router.post("/{test_id}/attempts/{attempt_id}/submit")
def submit_test_answers(
    test_id: int,
    attempt_id: int,
    request: AnswerSet,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, object]:
    test, attempt = _owned_attempt(db, test_id, attempt_id, user)
    result = public_tests.submit_public_attempt(
        db,
        test,
        attempt,
        answers=_answer_map(request),
        token=request.submission_token,
    )
    db.commit()
    return result


def _answer_map(request: AnswerSet) -> dict[int, str]:
    answers = [item.question_id for item in request.answers]
    if len(answers) != len(set(answers)):
        raise HTTPException(
            status_code=422, detail="Each question may be answered once."
        )
    return {item.question_id: item.answer for item in request.answers}
