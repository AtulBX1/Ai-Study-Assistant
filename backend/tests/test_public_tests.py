"""Fake-only coverage for public tests, ranking, privacy, and moderation."""

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.cache import MemoryCache
from app.core.config import Settings
from app.core.database import Base
from app.models import (
    ChatSession,
    Document,
    Flashcard,
    Message,
    PublicTest,
    PublicTestAttempt,
    PublicTestReport,
    Question,
    Quiz,
    QuizAttempt,
    User,
)
from app.services import public_tests
from tests.conftest import access_token_for


def _user(db_session, name: str, *, role: str = "student") -> User:
    user = User(
        email=f"{name}@example.test",
        full_name=f"Real name {name}",
        password_hash="unused",
        role=role,
        public_handle=name.replace(".", "-")[:20],
    )
    db_session.add(user)
    db_session.flush()
    return user


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token_for(user.id)}"}


def _quiz(db_session, owner: User, title: str = "Private quiz") -> Quiz:
    quiz = Quiz(owner_id=owner.id, title=title, engine="classic")
    db_session.add(quiz)
    db_session.flush()
    for index, (prompt, answer, topic) in enumerate(
        (
            ("What does TF-IDF measure?", "term importance", "TF-IDF"),
            ("What is tokenization?", "splitting text", "Text processing"),
            ("What learns contextual vectors?", "word2vec", "Embeddings"),
        )
    ):
        db_session.add(
            Question(
                quiz_id=quiz.id,
                type="multiple_choice" if index == 0 else "short_answer",
                difficulty="easy",
                prompt=prompt,
                options={
                    "choices": ["term importance", "page text"],
                    "evidence": "PRIVATE EVIDENCE SENTENCE",
                    "document_name": "secret-notes.pdf",
                    "document_id": 93,
                },
                answer=answer,
                explanation=f"Short explanation about {topic}.",
                topic=topic,
            )
        )
    db_session.flush()
    return quiz


def _test(db_session, owner: User, *, status: str = "approved") -> PublicTest:
    quiz = _quiz(db_session, owner)
    questions = list(
        db_session.scalars(
            select(Question).where(Question.quiz_id == quiz.id).order_by(Question.id)
        )
    )
    snapshot = public_tests.snapshot_questions(questions)
    test = PublicTest(
        title="NLP public test",
        description="Sample questions",
        subject="NLP",
        topic_labels=["TF-IDF", "Text processing", "Embeddings"],
        time_limit_seconds=120,
        question_count=len(snapshot),
        snapshot=snapshot,
        status=status,
        created_by=owner.id,
        source_quiz_id=quiz.id,
    )
    db_session.add(test)
    db_session.flush()
    return test


def _attempt(
    db_session,
    test: PublicTest,
    user: User,
    *,
    score: float,
    elapsed: int,
    completed: datetime,
    answers: dict[str, bool] | None = None,
) -> PublicTestAttempt:
    attempt = PublicTestAttempt(
        test_id=test.id,
        user_id=user.id,
        started_at=completed - timedelta(seconds=elapsed),
        completed_at=completed,
        shuffled_order=[0, 1, 2],
        saved_answers={},
        graded_answers=answers or {"0": True},
        score_percent=score,
        correct_count=round(score * test.question_count / 100),
        elapsed_seconds=elapsed,
        is_first_completed=True,
        is_suspicious=False,
        is_late=False,
        submission_token_hash=f"hash-{user.id}-{test.id}-{completed.isoformat()}".ljust(
            64, "0"
        ),
    )
    db_session.add(attempt)
    db_session.flush()
    return attempt


def test_rank_and_midrank_percentile_respect_time_tiebreaks(db_session) -> None:
    owner = _user(db_session, "rank-owner")
    test = _test(db_session, owner)
    now = datetime(2026, 11, 7, tzinfo=UTC)
    slower_tie = _attempt(
        db_session,
        test,
        _user(db_session, "rank-slower"),
        score=80,
        elapsed=80,
        completed=now,
    )
    faster_tie = _attempt(
        db_session,
        test,
        _user(db_session, "rank-faster"),
        score=80,
        elapsed=60,
        completed=now + timedelta(seconds=1),
    )
    _attempt(
        db_session,
        test,
        _user(db_session, "rank-high"),
        score=90,
        elapsed=100,
        completed=now + timedelta(seconds=2),
    )
    _attempt(
        db_session,
        test,
        _user(db_session, "rank-low"),
        score=40,
        elapsed=50,
        completed=now + timedelta(seconds=3),
    )
    ordered = public_tests.ranked_attempts(db_session, test)

    assert ordered.index(faster_tie) == 1
    assert public_tests.attempt_rank_percentile(ordered, faster_tie) == (2, 50.0)
    assert public_tests.attempt_rank_percentile(ordered, slower_tie) == (3, 50.0)


def test_only_first_completion_ranks_and_retakes_do_not_change_pool(db_session) -> None:
    user = _user(db_session, "first-attempt")
    test = _test(db_session, user)
    now = datetime(2026, 11, 7, tzinfo=UTC)
    first = _attempt(
        db_session,
        test,
        user,
        score=50,
        elapsed=30,
        completed=now,
    )
    second = _attempt(
        db_session,
        test,
        user,
        score=100,
        elapsed=30,
        completed=now + timedelta(minutes=1),
    )
    second.is_first_completed = False
    db_session.flush()

    rows = public_tests.ranked_attempts(db_session, test)
    stats = public_tests.test_statistics(db_session, test)

    assert rows == [first]
    assert stats["ranked_attempts"] == 1
    assert stats["mean_score_percent"] == 50


def test_start_hides_answers_shuffles_attempts_and_double_submit_is_rejected(
    client: TestClient, db_session
) -> None:
    owner = _user(db_session, "quiz-author")
    student = _user(db_session, "attempt-student")
    test = _test(db_session, owner)
    db_session.commit()
    headers = _headers(student)

    first = client.post(f"/public-tests/{test.id}/attempts", headers=headers)
    second = client.post(f"/public-tests/{test.id}/attempts", headers=headers)
    assert first.status_code == second.status_code == 201
    first_data, second_data = first.json(), second.json()
    assert [item["question_id"] for item in first_data["questions"]] != [
        item["question_id"] for item in second_data["questions"]
    ]
    assert "correct_answer" not in json.dumps(first_data)
    assert "explanation" not in json.dumps(first_data)
    assert "PRIVATE EVIDENCE SENTENCE" not in first.text

    payload = {
        "submission_token": first_data["submission_token"],
        "answers": [{"question_id": 0, "answer": "term importance"}],
    }
    submitted = client.post(
        f"/public-tests/{test.id}/attempts/{first_data['attempt_id']}/submit",
        headers=headers,
        json=payload,
    )
    assert submitted.status_code == 200
    assert "correct_answer" in submitted.text and "explanation" in submitted.text
    again = client.post(
        f"/public-tests/{test.id}/attempts/{first_data['attempt_id']}/submit",
        headers=headers,
        json=payload,
    )
    assert again.status_code == 409


def test_late_submission_keeps_only_answers_saved_before_deadline(db_session) -> None:
    owner = _user(db_session, "late-owner")
    student = _user(db_session, "late-student")
    test = _test(db_session, owner)
    test.question_count = 1
    test.snapshot = test.snapshot[:1]
    test.time_limit_seconds = 10
    start = datetime(2026, 11, 7, tzinfo=UTC)
    settings = Settings(
        backend="local",
        public_test_pool_minimum=1,
        public_test_min_seconds_per_question=1,
    )
    attempt, token = public_tests.start_public_attempt(
        db_session,
        test,
        student,
        cache=MemoryCache(),
        clock=lambda: start,
        settings=settings,
        shuffle=lambda order: None,
    )
    public_tests.save_public_answers(
        test,
        attempt,
        answers={0: "term importance"},
        token=token,
        clock=lambda: start + timedelta(seconds=5),
    )
    result = public_tests.submit_public_attempt(
        db_session,
        test,
        attempt,
        answers={0: "incorrect late answer"},
        token=token,
        clock=lambda: start + timedelta(seconds=11),
        settings=settings,
    )

    assert attempt.is_late is True
    assert attempt.saved_answers == {"0": "term importance"}
    assert attempt.graded_answers == {"0": True}
    assert result["late"] is True


def test_suspiciously_fast_first_attempt_is_excluded(db_session) -> None:
    owner = _user(db_session, "speed-owner")
    student = _user(db_session, "speed-student")
    test = _test(db_session, owner)
    test.question_count = 1
    test.snapshot = test.snapshot[:1]
    settings = Settings(backend="local", public_test_pool_minimum=1)
    start = datetime(2026, 11, 7, tzinfo=UTC)
    attempt, token = public_tests.start_public_attempt(
        db_session,
        test,
        student,
        cache=MemoryCache(),
        clock=lambda: start,
        settings=settings,
        shuffle=lambda order: None,
    )
    public_tests.submit_public_attempt(
        db_session,
        test,
        attempt,
        answers={0: "term importance"},
        token=token,
        clock=lambda: start + timedelta(seconds=2),
        settings=settings,
    )

    assert attempt.is_suspicious is True
    assert public_tests.ranked_attempts(db_session, test) == []
    assert public_tests.test_statistics(db_session, test)["ranked_attempts"] == 0


def test_small_pool_withholds_rank_percentile_and_leaderboard(db_session) -> None:
    user = _user(db_session, "small-owner")
    test = _test(db_session, user)
    _attempt(
        db_session,
        test,
        user,
        score=100,
        elapsed=60,
        completed=datetime(2026, 11, 7, tzinfo=UTC),
    )
    settings = Settings(backend="local", public_test_pool_minimum=10)

    board = public_tests.test_leaderboard(
        db_session, test, caller=user, settings=settings
    )

    assert board == {"status": "pool too small", "ranked_attempts": 1, "rows": []}


def test_hidden_user_counts_for_pool_but_is_not_listed(db_session) -> None:
    hidden = _user(db_session, "hidden-ranker")
    hidden.show_on_leaderboards = False
    test = _test(db_session, hidden)
    _attempt(
        db_session,
        test,
        hidden,
        score=100,
        elapsed=60,
        completed=datetime(2026, 11, 7, tzinfo=UTC),
    )
    settings = Settings(backend="local", public_test_pool_minimum=1)

    stats = public_tests.test_statistics(db_session, test, settings=settings)
    board = public_tests.test_leaderboard(
        db_session, test, caller=None, settings=settings
    )

    assert stats["ranked_attempts"] == 1
    assert board["rows"] == []


def test_unanswered_items_count_wrong_and_demo_data_is_local_only(db_session) -> None:
    owner = _user(db_session, "demo-stat-owner")
    test = _test(db_session, owner)
    test.is_demo = True
    attempt = _attempt(
        db_session,
        test,
        _user(db_session, "demo-stat-learner"),
        score=33.33,
        elapsed=60,
        completed=datetime(2026, 11, 7, tzinfo=UTC),
        answers={"0": True},
    )
    attempt.is_demo = True
    local_settings = Settings(backend="local", public_test_pool_minimum=1)
    production_settings = Settings(backend="prod", public_test_pool_minimum=1)

    local_stats = public_tests.test_statistics(
        db_session, test, settings=local_settings
    )
    production_stats = public_tests.test_statistics(
        db_session, test, settings=production_settings
    )

    assert local_stats["ranked_attempts"] == 1
    assert [row["percent_correct"] for row in local_stats["question_accuracy"]] == [
        100.0,
        0.0,
        0.0,
    ]
    assert production_stats["ranked_attempts"] == 0


def test_handles_are_case_insensitive_change_limited_and_public_payloads_private(
    client: TestClient, db_session
) -> None:
    first = _user(db_session, "handle-owner")
    second = _user(db_session, "handle-other")
    test = _test(db_session, first)
    test.status = "approved"
    db_session.commit()
    headers = _headers(first)

    changed = client.patch(
        "/auth/profile",
        headers=headers,
        json={"public_handle": "Bright-Learner"},
    )
    assert changed.status_code == 200
    duplicate = client.patch(
        "/auth/profile",
        headers=_headers(second),
        json={"public_handle": "BRIGHT-LEARNER"},
    )
    too_soon = client.patch(
        "/auth/profile",
        headers=headers,
        json={"public_handle": "Another-Learner"},
    )
    assert duplicate.status_code == 409
    assert too_soon.status_code == 429
    hidden = client.patch(
        "/auth/profile",
        headers=headers,
        json={"show_on_leaderboards": False},
    )
    assert hidden.status_code == 200

    listing = client.get("/public-tests")
    assert listing.status_code == 200
    serialized = listing.text
    for private_value in (first.email, first.full_name, second.email, second.full_name):
        assert private_value not in serialized
    response_items = json.loads(serialized)
    assert all(
        "user_id" not in item and "owner_id" not in item for item in response_items
    )
    assert "Bright-Learner" not in serialized
    stats = client.get(f"/public-tests/{test.id}/statistics")
    assert stats.status_code == 200


def test_submission_requires_rights_and_snapshot_discards_source_metadata(
    client: TestClient, db_session
) -> None:
    student = _user(db_session, "submitter")
    quiz = _quiz(db_session, student, "Share this quiz")
    db_session.commit()
    metadata = {
        "title": "Shared quiz",
        "description": "A short public quiz",
        "subject": "NLP",
        "topic_labels": ["Tokenization"],
        "time_limit_seconds": 300,
    }
    path = "/public-tests/submissions"
    rejected = client.post(
        path,
        headers=_headers(student),
        json={"quiz_id": quiz.id, "metadata": metadata, "rights_confirmed": False},
    )
    assert rejected.status_code == 422
    created = client.post(
        path,
        headers=_headers(student),
        json={"quiz_id": quiz.id, "metadata": metadata, "rights_confirmed": True},
    )
    assert created.status_code == 201
    test = db_session.get(PublicTest, created.json()["test_id"])
    assert test is not None and test.status == "pending"
    snapshot_text = json.dumps(test.snapshot)
    for forbidden in (
        "evidence",
        "PRIVATE EVIDENCE SENTENCE",
        "document_name",
        "secret-notes.pdf",
    ):
        assert forbidden not in snapshot_text
    assert set(test.snapshot[0]) == {
        "id",
        "question",
        "type",
        "options",
        "correct_answer",
        "explanation",
        "topic",
        "difficulty",
    }
    assert client.get("/public-tests").json() == []
    assert (
        client.patch(
            f"/public-tests/admin/tests/{test.id}/status",
            headers=_headers(student),
            json={"status": "approved"},
        ).status_code
        == 403
    )
    admin = _user(db_session, "review-admin", role="admin")
    approved = client.patch(
        f"/public-tests/admin/tests/{test.id}/status",
        headers=_headers(admin),
        json={"status": "approved"},
    )
    assert approved.status_code == 200
    assert len(client.get("/public-tests").json()) == 1


def test_three_distinct_reports_hide_test_for_review(
    client: TestClient, db_session
) -> None:
    owner = _user(db_session, "report-owner")
    test = _test(db_session, owner)
    reporters = [_user(db_session, f"reporter-{index}") for index in range(3)]
    db_session.commit()

    for reporter in reporters:
        response = client.post(
            f"/public-tests/{test.id}/reports",
            headers=_headers(reporter),
            json={"reason": "This test needs review."},
        )
        assert response.status_code == 201
    db_session.refresh(test)
    assert test.status == "hidden"
    assert db_session.scalar(
        select(PublicTestReport.id).where(PublicTestReport.test_id == test.id)
    )
    assert client.get("/public-tests").json() == []
    assert (
        client.get("/public-tests/admin/queue", headers=_headers(owner)).status_code
        == 403
    )
    admin = _user(db_session, "report-admin", role="admin")
    assert (
        len(client.get("/public-tests/admin/queue", headers=_headers(admin)).json())
        == 1
    )


def test_private_data_remains_owner_scoped_for_student_and_admin(
    client: TestClient, db_session
) -> None:
    owner = _user(db_session, "privacy-owner")
    other_student = _user(db_session, "privacy-student")
    admin = _user(db_session, "privacy-admin", role="admin")
    document = Document(owner_id=owner.id, title="Private doc", status="ready")
    chat = ChatSession(owner_id=owner.id, title="Private chat")
    quiz = _quiz(db_session, owner)
    db_session.add_all([document, chat])
    db_session.flush()
    db_session.add(
        Message(session_id=chat.id, role="user", content="secret chat message")
    )
    db_session.add(
        Flashcard(
            owner_id=owner.id,
            document_id=document.id,
            front="private front",
            back="private back",
        )
    )
    attempt = QuizAttempt(quiz_id=quiz.id, user_id=owner.id, score=1.0)
    db_session.add(attempt)
    db_session.commit()

    for user in (other_student, admin):
        headers = _headers(user)
        assert (
            client.get(f"/documents/{document.id}", headers=headers).status_code == 404
        )
        assert (
            client.get(f"/chat/sessions/{chat.id}", headers=headers).status_code == 404
        )
        assert client.get(f"/quizzes/{quiz.id}", headers=headers).status_code == 404
        assert (
            client.get(
                f"/quizzes/{quiz.id}/results/{attempt.id}", headers=headers
            ).status_code
            == 404
        )
        assert client.get("/study/flashcards/due", headers=headers).json() == []
        assert (
            client.get("/analytics/score-history", headers=headers).json()["points"]
            == []
        )
        assert (
            client.get("/analytics/topic-accuracy", headers=headers).json()["topics"]
            == []
        )


def test_handle_change_clock_and_blocked_words(db_session) -> None:
    user = _user(db_session, "clocked-user")
    now = datetime(2026, 11, 7, tzinfo=UTC)
    user.public_handle_changed_at = now

    with pytest.raises(HTTPException) as too_soon:
        public_tests.change_public_handle(
            db_session,
            user,
            "new-handle",
            clock=lambda: now + timedelta(days=29),
        )
    assert too_soon.value.status_code == 429

    public_tests.change_public_handle(
        db_session,
        user,
        "new-handle",
        clock=lambda: now + timedelta(days=30),
    )
    assert user.public_handle == "new-handle"
    with pytest.raises(HTTPException) as blocked:
        public_tests.change_public_handle(
            db_session,
            user,
            "admin-helper",
            clock=lambda: now + timedelta(days=60),
        )
    assert blocked.value.status_code == 422


def test_start_report_rate_limits_and_daily_submission_cap(db_session) -> None:
    owner = _user(db_session, "limits-owner")
    student = _user(db_session, "limits-student")
    reporter = _user(db_session, "limits-reporter")
    test = _test(db_session, owner)
    settings = Settings(
        backend="local",
        public_test_start_limit_per_minute=1,
        public_test_report_limit_per_minute=1,
        public_test_daily_submission_cap=1,
        public_test_min_seconds_per_question=1,
        public_test_pool_minimum=1,
    )
    start = datetime(2026, 11, 7, tzinfo=UTC)
    starts = MemoryCache()
    public_tests.start_public_attempt(
        db_session,
        test,
        student,
        cache=starts,
        clock=lambda: start,
        settings=settings,
        shuffle=lambda order: None,
    )
    with pytest.raises(HTTPException) as start_limited:
        public_tests.start_public_attempt(
            db_session,
            test,
            student,
            cache=starts,
            clock=lambda: start,
            settings=settings,
            shuffle=lambda order: None,
        )
    assert start_limited.value.status_code == 429

    report_cache = MemoryCache()
    public_tests.report_public_test(
        db_session,
        test,
        reporter,
        "Please review this test.",
        cache=report_cache,
        settings=settings,
    )
    with pytest.raises(HTTPException) as report_limited:
        public_tests.report_public_test(
            db_session,
            test,
            reporter,
            "Please review this test.",
            cache=report_cache,
            settings=settings,
        )
    assert report_limited.value.status_code == 429

    first_submitter = _user(db_session, "limits-first-submit")
    completed_attempt, token = public_tests.start_public_attempt(
        db_session,
        test,
        first_submitter,
        cache=MemoryCache(),
        clock=lambda: start,
        settings=settings,
        shuffle=lambda order: None,
    )
    public_tests.submit_public_attempt(
        db_session,
        test,
        completed_attempt,
        answers={0: "term importance"},
        token=token,
        clock=lambda: start + timedelta(seconds=30),
        settings=settings,
    )
    second_attempt, second_token = public_tests.start_public_attempt(
        db_session,
        test,
        first_submitter,
        cache=MemoryCache(),
        clock=lambda: start,
        settings=settings,
        shuffle=lambda order: None,
    )
    with pytest.raises(HTTPException) as daily_limited:
        public_tests.submit_public_attempt(
            db_session,
            test,
            second_attempt,
            answers={0: "term importance"},
            token=second_token,
            clock=lambda: start + timedelta(seconds=30),
            settings=settings,
        )
    assert daily_limited.value.status_code == 429


def test_models_have_only_student_and_admin_roles_and_no_class_tables() -> None:
    assert User.__table__.c.role.type.enums == ["student", "admin"]
    assert not {"classes", "class_members", "class_assignments"} & set(
        Base.metadata.tables
    )


def test_seed_script_refuses_production() -> None:
    script = Path(__file__).parents[1] / "scripts" / "seed_demo.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        check=False,
        capture_output=True,
        text=True,
        env={"BACKEND": "prod"},
    )
    assert result.returncode != 0
    assert "disabled when BACKEND=prod" in result.stderr
