"""Fake-only tests for owner-scoped student analytics."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, select

from alembic import command
from app.core.config import Settings, get_settings
from app.models import (
    AttemptAnswer,
    ChatSession,
    Chunk,
    Document,
    DocumentKeyTerm,
    Flashcard,
    FlashcardReviewLog,
    Message,
    Question,
    Quiz,
    QuizAttempt,
    TopicStat,
    User,
)
from app.routers import quizzes
from app.services.analytics import student
from app.services.rag.providers import ProviderUnavailableError
from tests.conftest import access_token_for


def _user(db_session, name: str, timezone: str = "UTC") -> User:
    user = User(
        email=f"{name}@example.test",
        full_name=name,
        password_hash="unused",
        timezone=timezone,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token_for(user.id)}"}


def _quiz(db_session, owner: User, title: str = "Practice quiz") -> Quiz:
    quiz = Quiz(owner_id=owner.id, title=title, engine="classic")
    db_session.add(quiz)
    db_session.flush()
    return quiz


def _attempt(
    db_session,
    owner: User,
    *,
    title: str,
    score: float,
    started_at: datetime,
    completed_at: datetime,
) -> QuizAttempt:
    quiz = _quiz(db_session, owner, title)
    attempt = QuizAttempt(
        quiz_id=quiz.id,
        user_id=owner.id,
        score=score,
        started_at=started_at,
        completed_at=completed_at,
    )
    db_session.add(attempt)
    db_session.flush()
    return attempt


def _review(
    db_session,
    owner: User,
    card: Flashcard,
    rating: str,
    reviewed_at: datetime,
) -> None:
    db_session.add(
        FlashcardReviewLog(
            flashcard_id=card.id,
            owner_id=owner.id,
            rating=rating,
            quality=5 if rating in {"Good", "Easy"} else 2,
            reviewed_at=reviewed_at,
            interval=card.interval,
            ease=2.5,
            repetitions=card.repetitions,
        )
    )


def test_submitting_attempt_updates_topic_stats_once(client, db_session, monkeypatch):
    owner = _user(db_session, "attempt-owner")
    document = Document(owner_id=owner.id, title="Notes", status="ready")
    db_session.add(document)
    db_session.flush()
    chunk = Chunk(
        doc_id=document.id,
        page=2,
        page_start=2,
        page_end=2,
        section="Unit I: Text Processing",
        text="Text processing prepares a document for analysis.",
        token_count=8,
        chunk_index=0,
    )
    quiz = _quiz(db_session, owner)
    db_session.add(chunk)
    db_session.flush()
    question = Question(
        quiz_id=quiz.id,
        type="true_false",
        difficulty="easy",
        prompt="Text processing prepares documents.",
        answer="True",
        topic="Generated fallback",
        page=2,
        source_chunk_id=chunk.id,
    )
    db_session.add(question)
    db_session.commit()
    monkeypatch.setattr(
        quizzes,
        "_provider",
        lambda: (_ for _ in ()).throw(ProviderUnavailableError("test fake")),
    )

    started = client.post(
        f"/quizzes/{quiz.id}/attempts", headers=_headers(owner)
    ).json()
    payload = {
        "answers": [{"question_id": question.id, "answer": "True"}],
    }
    first = client.post(
        f"/quizzes/{quiz.id}/attempts/{started['attempt_id']}/submit",
        headers=_headers(owner),
        json=payload,
    )
    assert first.status_code == 200, first.text
    db_session.expire_all()
    stat = db_session.scalar(
        select(TopicStat).where(
            TopicStat.owner_id == owner.id,
            TopicStat.topic == "Unit I: Text Processing",
        )
    )
    assert stat is not None
    original = (stat.attempts, stat.correct, stat.accuracy, stat.last_seen)
    assert original[:3] == (1, 1, 1.0)
    assert original[3] is not None

    second = client.post(
        f"/quizzes/{quiz.id}/attempts/{started['attempt_id']}/submit",
        headers=_headers(owner),
        json={"answers": [{"question_id": question.id, "answer": "False"}]},
    )
    assert second.status_code == 200, second.text
    db_session.expire_all()
    unchanged = db_session.scalar(
        select(TopicStat).where(
            TopicStat.owner_id == owner.id,
            TopicStat.topic == "Unit I: Text Processing",
        )
    )
    assert unchanged is not None
    assert (unchanged.attempts, unchanged.correct, unchanged.accuracy) == original[:3]
    assert unchanged.last_seen == original[3]
    answer = db_session.scalar(
        select(AttemptAnswer).where(AttemptAnswer.attempt_id == started["attempt_id"])
    )
    assert answer is not None and answer.answer == "True"


def test_submitting_attempt_uses_source_key_term_without_a_section(
    client, db_session, monkeypatch
):
    owner = _user(db_session, "key-term-owner")
    document = Document(owner_id=owner.id, title="Notes", status="ready")
    db_session.add(document)
    db_session.flush()
    chunk = Chunk(
        doc_id=document.id,
        page=1,
        page_start=1,
        page_end=1,
        text="TF-IDF weights terms by their importance in a document.",
        token_count=10,
        chunk_index=0,
    )
    db_session.add(
        DocumentKeyTerm(
            document_id=document.id,
            term="TF-IDF",
            label="concept",
            page=1,
            source="test",
        )
    )
    quiz = _quiz(db_session, owner)
    db_session.add(chunk)
    db_session.flush()
    question = Question(
        quiz_id=quiz.id,
        type="true_false",
        difficulty="easy",
        prompt="TF-IDF weights terms.",
        answer="True",
        topic="Generated fallback",
        page=1,
        source_chunk_id=chunk.id,
    )
    db_session.add(question)
    db_session.commit()
    monkeypatch.setattr(
        quizzes,
        "_provider",
        lambda: (_ for _ in ()).throw(ProviderUnavailableError("test fake")),
    )
    started = client.post(
        f"/quizzes/{quiz.id}/attempts", headers=_headers(owner)
    ).json()

    response = client.post(
        f"/quizzes/{quiz.id}/attempts/{started['attempt_id']}/submit",
        headers=_headers(owner),
        json={"answers": [{"question_id": question.id, "answer": "True"}]},
    )

    assert response.status_code == 200, response.text
    stat = db_session.scalar(
        select(TopicStat).where(
            TopicStat.owner_id == owner.id,
            TopicStat.topic == "TF-IDF",
        )
    )
    assert stat is not None and stat.attempts == 1 and stat.correct == 1
    topic_response = client.get("/analytics/topic-accuracy", headers=_headers(owner))
    assert topic_response.status_code == 200
    assert topic_response.json()["topics"][0]["source_pages"] == [
        {"document_id": document.id, "page": 1}
    ]


def test_weak_topics_require_three_answers_and_rank_by_accuracy_then_volume(
    db_session,
):
    owner = _user(db_session, "weak-owner")
    db_session.add_all(
        [
            TopicStat(owner_id=owner.id, topic="Only two", attempts=2, correct=0),
            TopicStat(owner_id=owner.id, topic="Weakest", attempts=4, correct=1),
            TopicStat(owner_id=owner.id, topic="Middle", attempts=7, correct=3),
            TopicStat(owner_id=owner.id, topic="Tie fewer", attempts=3, correct=1),
            TopicStat(owner_id=owner.id, topic="Tie more", attempts=6, correct=2),
            TopicStat(owner_id=owner.id, topic="Strong", attempts=4, correct=4),
        ]
    )
    db_session.flush()

    result = student.weak_topics(db_session, owner_id=owner.id)

    assert [topic["topic"] for topic in result["topics"]] == [
        "Weakest",
        "Tie more",
        "Tie fewer",
        "Middle",
    ]
    assert result["topics"][0]["accuracy_percent"] == 25
    assert result["topics"][0]["attempts"] == 4
    assert all(topic["attempts"] >= 3 for topic in result["topics"])


def test_streak_counts_activities_once_and_retains_longest_after_a_gap(db_session):
    owner = _user(db_session, "streak-owner")
    today = date(2026, 11, 7)
    db_session.add(
        TopicStat(owner_id=owner.id, topic="irrelevant", attempts=1, correct=1)
    )
    activity_day = datetime(2026, 11, 7, 9, tzinfo=UTC)
    attempt = _attempt(
        db_session,
        owner,
        title="Today",
        score=1,
        started_at=activity_day,
        completed_at=activity_day + timedelta(minutes=1),
    )
    card = Flashcard(
        owner_id=owner.id,
        front="Question",
        back="Answer",
        due_at=activity_day,
    )
    session = ChatSession(owner_id=owner.id, title="Study chat")
    db_session.add_all([card, session])
    db_session.flush()
    _review(db_session, owner, card, "Good", activity_day)
    db_session.add(
        Message(
            session_id=session.id,
            role="user",
            content="Explain the topic.",
            created_at=activity_day,
        )
    )
    db_session.flush()
    same_day = student.streaks(
        db_session,
        owner_id=owner.id,
        timezone=student.get_timezone(owner.timezone),
        today=today,
    )
    assert same_day["current_days"] == 1
    assert same_day["longest_days"] == 1

    result = student.calculate_streaks(
        {
            date(2026, 11, 1),
            date(2026, 11, 2),
            date(2026, 11, 4),
            date(2026, 11, 5),
            date(2026, 11, 7),
        },
        today=today,
    )
    assert result == {"current_days": 1, "longest_days": 2}
    assert attempt.id is not None


def test_flashcard_retention_ratio_and_card_maturity_counts(db_session):
    owner = _user(db_session, "retention-owner")
    now = datetime(2026, 11, 7, 12, tzinfo=UTC)
    mature_due = Flashcard(
        owner_id=owner.id,
        front="Mature due",
        back="Answer",
        interval=21,
        repetitions=5,
        due_at=now - timedelta(days=1),
    )
    new_due = Flashcard(
        owner_id=owner.id,
        front="New due",
        back="Answer",
        interval=0,
        repetitions=0,
        due_at=now,
    )
    mature_future = Flashcard(
        owner_id=owner.id,
        front="Mature future",
        back="Answer",
        interval=30,
        repetitions=6,
        due_at=now + timedelta(days=1),
    )
    db_session.add_all([mature_due, new_due, mature_future])
    db_session.flush()
    for rating in ("Good", "Easy", "Again"):
        _review(db_session, owner, mature_due, rating, now)
    db_session.flush()

    result = student.flashcard_retention(
        db_session,
        owner_id=owner.id,
        timezone=student.get_timezone("UTC"),
        today=date(2026, 11, 7),
    )

    assert result["weeks"] == [
        {
            "week_start": "2026-11-02",
            "good_easy_reviews": 2,
            "total_reviews": 3,
            "retention_percent": 66.67,
        }
    ]
    assert result["cards_due"] == 2
    assert result["mature_cards"] == 2
    assert result["new_cards"] == 1


def test_study_time_sums_quiz_flashcard_and_chat_estimates(db_session):
    owner = _user(db_session, "time-owner")
    started_at = datetime(2026, 11, 6, 10, tzinfo=UTC)
    completed_at = started_at + timedelta(seconds=120)
    _attempt(
        db_session,
        owner,
        title="Timed quiz",
        score=0.5,
        started_at=started_at,
        completed_at=completed_at,
    )
    cards = [
        Flashcard(owner_id=owner.id, front=f"Q{i}", back="A", due_at=started_at)
        for i in range(2)
    ]
    session = ChatSession(owner_id=owner.id, title="Study chat")
    db_session.add_all([*cards, session])
    db_session.flush()
    for card in cards:
        _review(db_session, owner, card, "Good", completed_at)
    db_session.add(
        Message(
            session_id=session.id,
            role="user",
            content="Explain this concept.",
            created_at=completed_at,
        )
    )
    db_session.flush()

    result = student.study_time(
        db_session,
        owner_id=owner.id,
        timezone=student.get_timezone("UTC"),
        days=1,
        seconds_per_card=30,
        seconds_per_chat_message=300,
        today=date(2026, 11, 6),
    )

    assert result["days"] == [{"date": "2026-11-06", "minutes": 8.0}]
    assert "5 minutes per user chat message" in result["estimate"]


def test_score_history_is_chronological_and_owner_scoped(db_session):
    owner = _user(db_session, "history-owner", "America/Los_Angeles")
    _attempt(
        db_session,
        owner,
        title="Later quiz",
        score=0.8,
        started_at=datetime(2026, 11, 6, 10, tzinfo=UTC),
        completed_at=datetime(2026, 11, 6, 10, 2, tzinfo=UTC),
    )
    _attempt(
        db_session,
        owner,
        title="Earlier quiz",
        score=0.5,
        started_at=datetime(2026, 11, 5, 10, tzinfo=UTC),
        completed_at=datetime(2026, 11, 5, 10, 2, tzinfo=UTC),
    )
    other = _user(db_session, "history-other")
    _attempt(
        db_session,
        other,
        title="Other user's quiz",
        score=1,
        started_at=datetime(2026, 11, 6, 10, tzinfo=UTC),
        completed_at=datetime(2026, 11, 6, 10, 2, tzinfo=UTC),
    )
    db_session.flush()

    result = student.score_history(
        db_session,
        owner_id=owner.id,
        timezone=student.get_timezone(owner.timezone),
    )

    assert [point["quiz_title"] for point in result["points"]] == [
        "Earlier quiz",
        "Later quiz",
    ]
    assert [point["score_percent"] for point in result["points"]] == [50, 80]
    assert [point["date"] for point in result["points"]] == [
        "2026-11-05",
        "2026-11-06",
    ]


def test_analytics_endpoints_are_authenticated_owner_scoped_and_empty_safe(
    client, db_session
):
    owner = _user(db_session, "api-owner")
    other = _user(db_session, "api-other")
    db_session.add(
        TopicStat(owner_id=other.id, topic="Private topic", attempts=3, correct=0)
    )
    _attempt(
        db_session,
        other,
        title="Private quiz",
        score=0.25,
        started_at=datetime.now(UTC) - timedelta(minutes=2),
        completed_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.commit()
    endpoints = [
        "/analytics/score-history",
        "/analytics/topic-accuracy",
        "/analytics/weak-topics",
        "/analytics/study-time",
        "/analytics/streaks",
        "/analytics/flashcard-retention",
        "/analytics/summary",
    ]

    assert client.get("/analytics/summary").status_code == 401
    for endpoint in endpoints:
        response = client.get(endpoint, headers=_headers(owner))
        assert response.status_code == 200, response.text
        assert response.json()["label"]
    assert (
        client.get("/analytics/score-history", headers=_headers(owner)).json()["points"]
        == []
    )
    assert (
        client.get("/analytics/topic-accuracy", headers=_headers(owner)).json()[
            "topics"
        ]
        == []
    )
    assert (
        client.get("/analytics/weak-topics", headers=_headers(owner)).json()["topics"]
        == []
    )
    summary = client.get("/analytics/summary", headers=_headers(owner)).json()
    assert summary["attempts"] == 0
    assert summary["average_score_percent"] == 0
    assert summary["best_topic"] is None
    assert summary["weakest_topic"] is None
    assert summary["cards_due"] == 0


def test_summary_and_weak_topics_endpoints_return_fake_fixture_sample(
    client, db_session
):
    owner = _user(db_session, "sample-owner")
    now = datetime.now(UTC)
    attempt = _attempt(
        db_session,
        owner,
        title="NLP review",
        score=0.75,
        started_at=now - timedelta(minutes=3),
        completed_at=now,
    )
    for offset, score in ((1, 0.9), (2, 0.65)):
        completed_at = now - timedelta(days=offset)
        _attempt(
            db_session,
            owner,
            title=f"NLP review day {offset}",
            score=score,
            started_at=completed_at - timedelta(minutes=3),
            completed_at=completed_at,
        )
    document = Document(owner_id=owner.id, title="NLP notes", status="ready")
    db_session.add(document)
    db_session.flush()
    chunk = Chunk(
        doc_id=document.id,
        page=7,
        page_start=7,
        page_end=7,
        section="RNN",
        text="A recurrent neural network processes sequence data.",
        token_count=8,
        chunk_index=0,
    )
    db_session.add(chunk)
    db_session.flush()
    question = Question(
        quiz_id=attempt.quiz_id,
        type="true_false",
        difficulty="easy",
        prompt="RNNs process sequences.",
        answer="True",
        topic="RNN",
        page=7,
        source_chunk_id=chunk.id,
    )
    db_session.add_all(
        [
            question,
            TopicStat(owner_id=owner.id, topic="RNN", attempts=3, correct=1),
            TopicStat(
                owner_id=owner.id,
                topic="Transformers",
                attempts=4,
                correct=4,
            ),
        ]
    )
    db_session.flush()
    db_session.add(
        AttemptAnswer(
            attempt_id=attempt.id,
            question_id=question.id,
            answer="False",
            is_correct=False,
        )
    )
    db_session.commit()

    summary_response = client.get("/analytics/summary", headers=_headers(owner))
    weak_response = client.get("/analytics/weak-topics", headers=_headers(owner))

    assert summary_response.status_code == 200
    assert summary_response.json()["attempts"] == 3
    assert summary_response.json()["average_score_percent"] == 76.67
    assert summary_response.json()["best_topic"]["topic"] == "Transformers"
    assert summary_response.json()["weakest_topic"]["topic"] == "RNN"
    assert weak_response.status_code == 200
    weak_topic = weak_response.json()["topics"][0]
    assert weak_topic["accuracy_percent"] == 33.33
    assert weak_topic["attempts"] == 3
    assert weak_topic["source_pages"] == [{"document_id": document.id, "page": 7}]


def test_analytics_migration_is_the_single_head_and_upgrades_empty_database(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "empty.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))

    try:
        assert ScriptDirectory.from_config(alembic_config).get_heads() == [
            "14a_student_analytics"
        ]
        command.upgrade(alembic_config, "head")
        engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        try:
            inspector = inspect(engine)
            assert "users" in inspector.get_table_names()
            assert "topic_stats" in inspector.get_table_names()
            assert {
                "timezone",
            } <= {column["name"] for column in inspector.get_columns("users")}
            assert {"accuracy", "last_seen"} <= {
                column["name"] for column in inspector.get_columns("topic_stats")
            }
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()
