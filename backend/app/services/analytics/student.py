"""Owner-scoped student analytics and deterministic activity calculations."""

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

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
)

DEFAULT_WEAK_THRESHOLD_PERCENT = 60.0
DEFAULT_SECONDS_PER_CARD = 30
DEFAULT_SECONDS_PER_CHAT_MESSAGE = 300


def get_timezone(timezone_name: str | None) -> ZoneInfo:
    """Return a user's configured IANA timezone, defaulting to UTC."""
    try:
        return ZoneInfo(timezone_name or "UTC")
    except ZoneInfoNotFoundError as error:
        message = "The user's timezone must be a valid IANA timezone."
        raise ValueError(message) from error


def local_today(timezone: ZoneInfo) -> date:
    """Return today's date in the supplied user timezone."""
    return datetime.now(timezone).date()


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _local_date(value: datetime, timezone: ZoneInfo) -> date:
    return _as_utc(value).astimezone(timezone).date()


def score_history(
    db: Session, *, owner_id: int, timezone: ZoneInfo
) -> dict[str, object]:
    """Return completed quiz scores in chronological order as chart points."""
    rows = db.execute(
        select(QuizAttempt, Quiz.title)
        .join(Quiz, QuizAttempt.quiz_id == Quiz.id)
        .where(
            QuizAttempt.user_id == owner_id,
            Quiz.owner_id == owner_id,
            QuizAttempt.score.is_not(None),
        )
    ).all()
    attempts = sorted(
        rows,
        key=lambda row: (
            row[0].completed_at or row[0].started_at,
            row[0].id,
        ),
    )
    return {
        "label": "Quiz score history",
        "unit": "percent",
        "points": [
            {
                "date": _local_date(
                    attempt.completed_at or attempt.started_at, timezone
                ).isoformat(),
                "quiz_title": title,
                "score_percent": round(float(attempt.score or 0) * 100, 2),
            }
            for attempt, title in attempts
        ],
    }


def _source_pages_by_topic(db: Session, *, owner_id: int) -> dict[str, list[dict]]:
    rows = db.execute(
        select(
            Question.topic,
            Question.page,
            Quiz.source_document_id,
            Chunk.doc_id,
            Chunk.section,
            Chunk.text,
            Chunk.page_start,
            Chunk.page_end,
        )
        .select_from(AttemptAnswer)
        .join(Question, AttemptAnswer.question_id == Question.id)
        .join(QuizAttempt, AttemptAnswer.attempt_id == QuizAttempt.id)
        .join(Quiz, QuizAttempt.quiz_id == Quiz.id)
        .outerjoin(
            Chunk,
            Question.source_chunk_id == Chunk.id,
        )
        .where(
            QuizAttempt.user_id == owner_id,
            Quiz.owner_id == owner_id,
            AttemptAnswer.is_correct.is_not(None),
        )
    ).all()
    pages: dict[str, set[tuple[int | None, int]]] = defaultdict(set)
    document_ids = {row[3] for row in rows if row[3] is not None}
    terms_by_document: dict[int, list[DocumentKeyTerm]] = defaultdict(list)
    if document_ids:
        terms = db.scalars(
            select(DocumentKeyTerm)
            .join(Document, DocumentKeyTerm.document_id == Document.id)
            .where(
                Document.owner_id == owner_id,
                DocumentKeyTerm.document_id.in_(document_ids),
            )
        )
        for term in terms:
            terms_by_document[term.document_id].append(term)
    for (
        topic,
        page,
        source_document_id,
        chunk_document_id,
        section,
        chunk_text,
        page_start,
        page_end,
    ) in rows:
        document_id = chunk_document_id or source_document_id
        if topic:
            pages[topic].add((document_id, page))
        if section:
            pages[section].add((document_id, page))
        if chunk_document_id and chunk_text:
            for term in terms_by_document.get(chunk_document_id, []):
                if (
                    page_start <= term.page <= page_end
                    and term.term.casefold() in chunk_text.casefold()
                ):
                    pages[term.term].add((document_id, page))
    return {
        topic: [
            {"document_id": document_id, "page": page}
            for document_id, page in sorted(
                values, key=lambda item: (item[0] or 0, item[1])
            )
        ]
        for topic, values in pages.items()
    }


def topic_accuracy(db: Session, *, owner_id: int) -> dict[str, object]:
    """Return accuracy and answered counts for all topics owned by one learner."""
    pages_by_topic = _source_pages_by_topic(db, owner_id=owner_id)
    stats = db.scalars(
        select(TopicStat)
        .where(TopicStat.owner_id == owner_id)
        .order_by(TopicStat.topic)
    )
    topics = []
    for stat in stats:
        accuracy = stat.correct / stat.attempts if stat.attempts else 0.0
        topics.append(
            {
                "label": stat.topic,
                "topic": stat.topic,
                "accuracy_percent": round(accuracy * 100, 2),
                "attempts": stat.attempts,
                "correct": stat.correct,
                "source_pages": pages_by_topic.get(stat.topic, []),
            }
        )
    return {
        "label": "Topic accuracy",
        "unit": "percent",
        "units": {
            "accuracy": "percent",
            "attempts": "answers",
            "correct": "answers",
        },
        "topics": topics,
    }


def weak_topics(
    db: Session,
    *,
    owner_id: int,
    threshold_percent: float = DEFAULT_WEAK_THRESHOLD_PERCENT,
) -> dict[str, object]:
    """Rank topics with at least three answers below a configurable threshold."""
    if not 0 <= threshold_percent <= 100:
        raise ValueError("threshold_percent must be between 0 and 100.")
    all_topics = topic_accuracy(db, owner_id=owner_id)["topics"]
    eligible = [
        item
        for item in all_topics
        if item["attempts"] >= 3 and item["accuracy_percent"] < threshold_percent
    ]
    eligible.sort(
        key=lambda item: (
            item["accuracy_percent"],
            -item["attempts"],
            item["topic"].casefold(),
        )
    )
    return {
        "label": "Weak topics",
        "unit": "percent",
        "units": {
            "accuracy": "percent",
            "attempts": "answers",
            "correct": "answers",
        },
        "threshold_percent": threshold_percent,
        "topics": eligible,
    }


def _activity_dates(db: Session, *, owner_id: int, timezone: ZoneInfo) -> set[date]:
    dates: set[date] = set()
    attempts = db.scalars(select(QuizAttempt).where(QuizAttempt.user_id == owner_id))
    dates.update(
        _local_date(attempt.completed_at or attempt.started_at, timezone)
        for attempt in attempts
    )
    reviews = db.scalars(
        select(FlashcardReviewLog).where(FlashcardReviewLog.owner_id == owner_id)
    )
    dates.update(_local_date(review.reviewed_at, timezone) for review in reviews)
    messages = db.scalars(
        select(Message)
        .join(ChatSession, Message.session_id == ChatSession.id)
        .where(ChatSession.owner_id == owner_id, Message.role == "user")
    )
    dates.update(_local_date(message.created_at, timezone) for message in messages)
    return dates


def calculate_streaks(activity_dates: set[date], *, today: date) -> dict[str, int]:
    """Count unique active dates and the current/longest consecutive streaks."""
    active_dates = {
        activity_day for activity_day in activity_dates if activity_day <= today
    }
    longest = 0
    run = 0
    previous: date | None = None
    for activity_day in sorted(active_dates):
        run = (
            run + 1 if previous and activity_day == previous + timedelta(days=1) else 1
        )
        longest = max(longest, run)
        previous = activity_day

    anchor = today if today in active_dates else today - timedelta(days=1)
    current = 0
    while anchor in active_dates:
        current += 1
        anchor -= timedelta(days=1)
    return {"current_days": current, "longest_days": longest}


def streaks(
    db: Session, *, owner_id: int, timezone: ZoneInfo, today: date | None = None
) -> dict[str, object]:
    """Return current and longest streaks, with multiple events counting once."""
    reference_day = today or local_today(timezone)
    result = calculate_streaks(
        _activity_dates(db, owner_id=owner_id, timezone=timezone),
        today=reference_day,
    )
    return {
        "label": "Study streak",
        "unit": "days",
        **result,
    }


def study_time(
    db: Session,
    *,
    owner_id: int,
    timezone: ZoneInfo,
    days: int = 30,
    seconds_per_card: int = DEFAULT_SECONDS_PER_CARD,
    seconds_per_chat_message: int = DEFAULT_SECONDS_PER_CHAT_MESSAGE,
    today: date | None = None,
) -> dict[str, object]:
    """Estimate daily study minutes from quizzes, reviews, and chat messages."""
    if not 1 <= days <= 366:
        raise ValueError("days must be between 1 and 366.")
    if seconds_per_card < 0 or seconds_per_chat_message < 0:
        raise ValueError("Activity estimates must not be negative.")
    final_day = today or local_today(timezone)
    first_day = final_day - timedelta(days=days - 1)
    start_utc = datetime.combine(first_day, time.min, tzinfo=timezone).astimezone(UTC)
    seconds_by_day: dict[date, float] = defaultdict(float)

    attempts = db.scalars(
        select(QuizAttempt).where(
            QuizAttempt.user_id == owner_id,
            QuizAttempt.completed_at.is_not(None),
            QuizAttempt.completed_at >= start_utc,
        )
    )
    for attempt in attempts:
        if attempt.started_at is None or attempt.completed_at is None:
            continue
        activity_day = _local_date(attempt.completed_at, timezone)
        duration = (
            _as_utc(attempt.completed_at) - _as_utc(attempt.started_at)
        ).total_seconds()
        if first_day <= activity_day <= final_day:
            seconds_by_day[activity_day] += max(0.0, duration)

    reviews = db.scalars(
        select(FlashcardReviewLog).where(
            FlashcardReviewLog.owner_id == owner_id,
            FlashcardReviewLog.reviewed_at >= start_utc,
        )
    )
    for review in reviews:
        activity_day = _local_date(review.reviewed_at, timezone)
        if first_day <= activity_day <= final_day:
            seconds_by_day[activity_day] += seconds_per_card

    messages = db.scalars(
        select(Message)
        .join(ChatSession, Message.session_id == ChatSession.id)
        .where(
            ChatSession.owner_id == owner_id,
            Message.role == "user",
            Message.created_at >= start_utc,
        )
    )
    for message in messages:
        activity_day = _local_date(message.created_at, timezone)
        if first_day <= activity_day <= final_day:
            seconds_by_day[activity_day] += seconds_per_chat_message

    return {
        "label": "Estimated study time",
        "unit": "minutes per day",
        "estimate": (
            "Quiz elapsed time plus 30 seconds per flashcard review by default "
            "and 5 minutes per user chat message by default; override either "
            "estimate with the request parameters."
        ),
        "days": [
            {
                "date": (first_day + timedelta(days=offset)).isoformat(),
                "minutes": round(
                    seconds_by_day[first_day + timedelta(days=offset)] / 60, 2
                ),
            }
            for offset in range(days)
        ],
    }


def flashcard_retention(
    db: Session, *, owner_id: int, timezone: ZoneInfo, today: date | None = None
) -> dict[str, object]:
    """Summarize weekly Good/Easy review share and active card inventory."""
    reference_day = today or local_today(timezone)
    reviews = db.scalars(
        select(FlashcardReviewLog)
        .where(FlashcardReviewLog.owner_id == owner_id)
        .order_by(FlashcardReviewLog.reviewed_at)
    )
    weekly: dict[date, list[int]] = defaultdict(lambda: [0, 0])
    for review in reviews:
        review_day = _local_date(review.reviewed_at, timezone)
        week_start = review_day - timedelta(days=review_day.weekday())
        counts = weekly[week_start]
        counts[1] += 1
        if review.rating.casefold() in {"good", "easy"}:
            counts[0] += 1
    weekly_points = [
        {
            "week_start": week_start.isoformat(),
            "good_easy_reviews": counts[0],
            "total_reviews": counts[1],
            "retention_percent": round(counts[0] / counts[1] * 100, 2),
        }
        for week_start, counts in sorted(weekly.items())
    ]
    cards = db.scalars(
        select(Flashcard).where(
            Flashcard.owner_id == owner_id,
            Flashcard.suspended.is_(False),
        )
    )
    due = mature = new = 0
    for card in cards:
        if _local_date(card.due_at, timezone) <= reference_day:
            due += 1
        if card.interval >= 21:
            mature += 1
        if card.repetitions == 0:
            new += 1
    return {
        "label": "Flashcard retention",
        "unit": "percent",
        "weeks": weekly_points,
        "units": {
            "retention": "percent",
            "cards_due": "cards",
            "mature_cards": "cards",
            "new_cards": "cards",
        },
        "cards_due": due,
        "mature_cards": mature,
        "new_cards": new,
    }


def summary(
    db: Session,
    *,
    owner_id: int,
    timezone: ZoneInfo,
    today: date | None = None,
    threshold_percent: float = DEFAULT_WEAK_THRESHOLD_PERCENT,
) -> dict[str, object]:
    """Combine the main learner progress indicators into one response."""
    history = score_history(db, owner_id=owner_id, timezone=timezone)["points"]
    topics = topic_accuracy(db, owner_id=owner_id)["topics"]
    weak = weak_topics(db, owner_id=owner_id, threshold_percent=threshold_percent)[
        "topics"
    ]
    reference_day = today or local_today(timezone)
    streak = calculate_streaks(
        _activity_dates(db, owner_id=owner_id, timezone=timezone),
        today=reference_day,
    )
    card_counts = flashcard_retention(
        db, owner_id=owner_id, timezone=timezone, today=reference_day
    )
    best = max(
        (topic for topic in topics if topic["attempts"]),
        key=lambda topic: (topic["accuracy_percent"], topic["attempts"]),
        default=None,
    )
    weakest = weak[0] if weak else None
    average_score = (
        sum(point["score_percent"] for point in history) / len(history)
        if history
        else 0.0
    )
    return {
        "label": "Student analytics summary",
        "units": {
            "attempts": "attempts",
            "average_score_percent": "percent",
            "streak": "days",
            "cards_due": "cards",
        },
        "attempts": len(history),
        "average_score_percent": round(average_score, 2),
        "best_topic": best,
        "weakest_topic": weakest,
        "streak": streak,
        "cards_due": card_counts["cards_due"],
    }
