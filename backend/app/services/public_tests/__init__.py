"""Snapshotting, grading, and chart-ready ranking for the public test library."""

import hashlib
import hmac
import re
import secrets
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from statistics import median, pstdev
from typing import Any

from fastapi import HTTPException
from redis.exceptions import RedisError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.cache import Cache
from app.core.config import Settings, get_settings
from app.models import (
    PublicTest,
    PublicTestAttempt,
    PublicTestReport,
    Question,
    User,
)
from app.models.entities import utc_now
from app.services.quiz.grading import grade_answer

Clock = Callable[[], datetime]


def snapshot_questions(questions: Sequence[Question]) -> list[dict[str, Any]]:
    """Copy only shareable question fields; source metadata never enters a snapshot."""
    snapshot = []
    for index, question in enumerate(questions):
        metadata = question.options if isinstance(question.options, dict) else {}
        raw_options = metadata.get("choices", []) if metadata else question.options
        options = []
        if isinstance(raw_options, list):
            for option in raw_options:
                if isinstance(option, str):
                    options.append(option)
                elif isinstance(option, dict):
                    safe_option = {
                        key: value
                        for key, value in option.items()
                        if key in {"text", "label", "value"}
                        and isinstance(value, (str, int, float, bool))
                    }
                    if safe_option:
                        options.append(safe_option)
        forbidden = [
            str(value).strip()
            for key, value in metadata.items()
            if any(
                part in key.casefold()
                for part in ("evidence", "source", "document", "page")
            )
            and isinstance(value, str)
            and value.strip()
        ]
        prompt = question.prompt
        for value in forbidden:
            prompt = re.sub(re.escape(value), "", prompt, flags=re.IGNORECASE).strip()
        explanation = (question.explanation or "")[:500]
        if any(value.casefold() in explanation.casefold() for value in forbidden):
            explanation = ""
        snapshot.append(
            {
                "id": index,
                "question": prompt,
                "type": question.type,
                "options": options,
                "correct_answer": question.answer,
                "explanation": explanation,
                "topic": question.topic or "General",
                "difficulty": question.difficulty,
            }
        )
    return snapshot


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def change_public_handle(
    db: Session,
    user: User,
    handle: str,
    *,
    clock: Clock = utc_now,
) -> None:
    """Validate and update a handle using an injectable clock."""
    normalized = handle.strip()
    if not 3 <= len(normalized) <= 20 or not all(
        char.isascii() and (char.isalnum() or char in "-_") for char in normalized
    ):
        raise HTTPException(status_code=422, detail="Invalid public handle.")
    if any(
        word in normalized.casefold()
        for word in ("admin", "moderator", "support", "fuck", "shit")
    ):
        raise HTTPException(status_code=422, detail="This public handle is blocked.")
    now = _as_utc(clock())
    if user.public_handle_changed_at is not None:
        changed_at = user.public_handle_changed_at
        if changed_at.tzinfo is None:
            changed_at = changed_at.replace(tzinfo=UTC)
        if now - changed_at < timedelta(days=30):
            raise HTTPException(
                status_code=429,
                detail="A public handle can be changed once every 30 days.",
            )
    collision = db.scalar(
        select(User.id).where(
            User.id != user.id, func.lower(User.public_handle) == normalized.lower()
        )
    )
    if collision is not None:
        raise HTTPException(status_code=409, detail="Public handle is unavailable.")
    user.public_handle = normalized
    user.public_handle_changed_at = now


def _is_local_demo(settings: Settings | None = None) -> bool:
    return (settings or get_settings()).backend == "local"


def ranked_attempts(
    db: Session,
    test: PublicTest,
    *,
    window_start: datetime | None = None,
    settings: Settings | None = None,
) -> list[PublicTestAttempt]:
    """Return all eligible first attempts, including hidden users for fair pools."""
    query = (
        select(PublicTestAttempt)
        .join(PublicTest, PublicTestAttempt.test_id == PublicTest.id)
        .where(
            PublicTestAttempt.test_id == test.id,
            PublicTestAttempt.completed_at.is_not(None),
            PublicTestAttempt.is_first_completed.is_(True),
            PublicTestAttempt.is_suspicious.is_(False),
        )
    )
    if window_start is not None:
        query = query.where(PublicTestAttempt.completed_at >= window_start)
    if not _is_local_demo(settings):
        query = query.where(
            PublicTestAttempt.is_demo.is_(False), PublicTest.is_demo.is_(False)
        )
    rows = list(db.scalars(query))
    return sorted(
        rows,
        key=lambda item: (
            -float(item.score_percent or 0),
            int(item.elapsed_seconds or 0),
            item.completed_at or item.started_at,
            item.id,
        ),
    )


def attempt_rank_percentile(
    attempts: Sequence[PublicTestAttempt], attempt: PublicTestAttempt
) -> tuple[int, float]:
    """Return ordinal rank and score percentile; score ties use a midrank."""
    rank = next(
        index for index, row in enumerate(attempts, start=1) if row.id == attempt.id
    )
    others = [row for row in attempts if row.id != attempt.id]
    if not others:
        return rank, 100.0
    score = float(attempt.score_percent or 0)
    below = sum(float(row.score_percent or 0) < score for row in others)
    ties = sum(float(row.score_percent or 0) == score for row in others)
    return rank, 100 * (below + ties / 2) / len(others)


def _question_pool_accuracy(
    test: PublicTest, attempts: Sequence[PublicTestAttempt]
) -> list[dict[str, object]]:
    results = []
    for question in test.snapshot:
        question_id = str(question["id"])
        correctness = [row.graded_answers.get(question_id, False) for row in attempts]
        percent_correct = (
            round(100 * sum(correctness) / len(correctness), 2) if correctness else None
        )
        results.append(
            {
                "question": question["question"],
                "topic": question["topic"],
                "percent_correct": percent_correct,
                "answers": len(correctness),
            }
        )
    return results


def test_statistics(
    db: Session,
    test: PublicTest,
    *,
    settings: Settings | None = None,
) -> dict[str, object]:
    """Create chart-ready pool metrics without exposing participant identity."""
    attempts = ranked_attempts(db, test, settings=settings)
    scores = [float(row.score_percent or 0) for row in attempts]
    bins = {f"{start}-{start + 9}": 0 for start in range(0, 100, 10)}
    bins["100"] = 0
    for score in scores:
        key = (
            "100"
            if score >= 100
            else f"{int(score // 10) * 10}-{int(score // 10) * 10 + 9}"
        )
        bins[key] += 1
    return {
        "test_id": test.id,
        "ranked_attempts": len(attempts),
        "mean_score_percent": round(sum(scores) / len(scores), 2) if scores else None,
        "median_score_percent": round(float(median(scores)), 2) if scores else None,
        "score_standard_deviation": round(pstdev(scores), 2) if scores else None,
        "score_distribution": [
            {"bin": key, "count": value} for key, value in bins.items()
        ],
        "question_accuracy": _question_pool_accuracy(test, attempts),
    }


def _public_handle(db: Session, user_id: int) -> str:
    user = db.get(User, user_id)
    return (
        user.public_handle
        if user is not None and user.show_on_leaderboards
        else "Anonymous"
    )


def test_leaderboard(
    db: Session,
    test: PublicTest,
    *,
    caller: User | None,
    settings: Settings | None = None,
) -> dict[str, object]:
    attempts = ranked_attempts(db, test, settings=settings)
    minimum = (settings or get_settings()).public_test_pool_minimum
    if len(attempts) < minimum:
        return {
            "status": "pool too small",
            "ranked_attempts": len(attempts),
            "rows": [],
        }
    visible = [
        row
        for row in attempts
        if (participant := db.get(User, row.user_id)) is not None
        and participant.show_on_leaderboards
    ]

    def row_payload(attempt: PublicTestAttempt) -> dict[str, object]:
        rank, _ = attempt_rank_percentile(attempts, attempt)
        return {
            "rank": rank,
            "handle": _public_handle(db, attempt.user_id),
            "score_percent": round(float(attempt.score_percent or 0), 2),
            "time_seconds": attempt.elapsed_seconds,
        }

    rows = [row_payload(item) for item in visible[:20]]
    caller_attempt = next(
        (row for row in attempts if caller is not None and row.user_id == caller.id),
        None,
    )
    if (
        caller_attempt is not None
        and caller is not None
        and caller.show_on_leaderboards
        and caller_attempt not in visible[:20]
    ):
        rows.append(row_payload(caller_attempt))
    return {"status": "ok", "ranked_attempts": len(attempts), "rows": rows}


def submission_result(
    db: Session,
    test: PublicTest,
    attempt: PublicTestAttempt,
    *,
    settings: Settings | None = None,
) -> dict[str, object]:
    attempts = ranked_attempts(db, test, settings=settings)
    total = len(attempts)
    minimum = (settings or get_settings()).public_test_pool_minimum
    result: dict[str, object] = {
        "attempt_id": attempt.id,
        "score_percent": attempt.score_percent,
        "correct": attempt.correct_count,
        "total": test.question_count,
        "late": attempt.is_late,
        "suspicious": attempt.is_suspicious,
        "ranked": attempt.is_first_completed and not attempt.is_suspicious,
        "practice": not attempt.is_first_completed,
        "results": [
            {
                "question_id": question["id"],
                "question": question["question"],
                "topic": question["topic"],
                "is_correct": attempt.graded_answers.get(str(question["id"]), False),
                "answer": attempt.saved_answers.get(str(question["id"]), ""),
                "correct_answer": question["correct_answer"],
                "explanation": question["explanation"],
            }
            for question in test.snapshot
        ],
    }
    if attempt.is_suspicious:
        result["note"] = (
            "Suspiciously fast; excluded from rankings and pool statistics."
        )
    if total < minimum:
        result["pool_comparison"] = {"status": "pool too small"}
        return result
    if not attempt.is_first_completed or attempt.is_suspicious:
        result["pool_comparison"] = {"status": "not ranked"}
        return result
    rank, percentile = attempt_rank_percentile(attempts, attempt)
    stats = test_statistics(db, test, settings=settings)
    median_time = median([row.elapsed_seconds or 0 for row in attempts])
    user_topic: dict[str, list[bool]] = defaultdict(list)
    for question in test.snapshot:
        key = str(question["id"])
        user_topic[question["topic"]].append(attempt.graded_answers.get(key, False))
    topic_pool = {
        str(row["topic"]): row["percent_correct"] for row in stats["question_accuracy"]
    }
    result["rank"] = rank
    result["percentile"] = round(percentile, 2)
    result["pool_comparison"] = {
        "status": "ok",
        "ranked_attempts": total,
        "score_vs_pool_mean_percent": round(
            float(attempt.score_percent or 0) - float(stats["mean_score_percent"] or 0),
            2,
        ),
        "time_vs_pool_median_seconds": round(
            (attempt.elapsed_seconds or 0) - float(median_time), 2
        ),
        "topics": [
            {
                "topic": topic,
                "user_accuracy_percent": round(100 * sum(outcomes) / len(outcomes), 2),
                "pool_accuracy_percent": topic_pool.get(topic),
            }
            for topic, outcomes in sorted(user_topic.items())
        ],
    }
    return result


def _accuracy_rows(
    db: Session,
    *,
    window_start: datetime | None,
    caller: User | None,
    settings: Settings | None = None,
) -> dict[str, object]:
    tests = list(db.scalars(select(PublicTest).where(PublicTest.status == "approved")))
    percentile_by_user: dict[int, list[float]] = defaultdict(list)
    tests_by_user: Counter[int] = Counter()
    for test in tests:
        attempts = ranked_attempts(
            db, test, window_start=window_start, settings=settings
        )
        if len(attempts) < (settings or get_settings()).public_test_pool_minimum:
            continue
        for attempt in attempts:
            _, percentile = attempt_rank_percentile(attempts, attempt)
            percentile_by_user[attempt.user_id].append(percentile)
            tests_by_user[attempt.user_id] += 1
    eligible = []
    for user_id, percentiles in percentile_by_user.items():
        participant = db.get(User, user_id)
        if (
            participant is not None
            and participant.show_on_leaderboards
            and tests_by_user[user_id] >= 3
        ):
            eligible.append(
                {
                    "handle": participant.public_handle,
                    "accuracy_rank_percentile": round(
                        sum(percentiles) / len(percentiles), 2
                    ),
                    "ranked_tests": tests_by_user[user_id],
                    "_user_id": user_id,
                }
            )
    eligible.sort(
        key=lambda item: (
            -float(item["accuracy_rank_percentile"]),
            str(item["handle"]).casefold(),
        )
    )
    rows = [
        {
            "rank": index,
            "handle": row["handle"],
            "accuracy_rank_percentile": row["accuracy_rank_percentile"],
            "ranked_tests": row["ranked_tests"],
        }
        for index, row in enumerate(eligible[:50], start=1)
    ]
    own = next(
        (
            row
            for row in eligible
            if caller is not None and row["_user_id"] == caller.id
        ),
        None,
    )
    if own is not None and caller is not None and caller.show_on_leaderboards:
        own_rank = eligible.index(own) + 1
        if own_rank > 50:
            rows.append(
                {
                    "rank": own_rank,
                    "handle": own["handle"],
                    "accuracy_rank_percentile": own["accuracy_rank_percentile"],
                    "ranked_tests": own["ranked_tests"],
                }
            )
    return {"status": "ok" if eligible else "pool too small", "rows": rows}


def accuracy_leaderboard(
    db: Session,
    *,
    window: str,
    caller: User | None,
    clock: Clock = utc_now,
    settings: Settings | None = None,
) -> dict[str, object]:
    if window not in {"weekly", "all-time"}:
        raise HTTPException(status_code=422, detail="Unsupported leaderboard window.")
    start = clock() - timedelta(days=7) if window == "weekly" else None
    return {
        "window": window,
        **_accuracy_rows(db, window_start=start, caller=caller, settings=settings),
    }


def personal_overview(
    db: Session,
    user: User,
    *,
    settings: Settings | None = None,
) -> dict[str, object]:
    tests = list(db.scalars(select(PublicTest).where(PublicTest.status == "approved")))
    ranked_tests = []
    topic_outcomes: dict[str, list[bool]] = defaultdict(list)
    trend = []
    for test in tests:
        rows = ranked_attempts(db, test, settings=settings)
        own = next((row for row in rows if row.user_id == user.id), None)
        if own is None:
            continue
        if len(rows) < (settings or get_settings()).public_test_pool_minimum:
            ranked_tests.append(
                {
                    "test": test.title,
                    "score_percent": own.score_percent,
                    "rank": None,
                    "percentile": None,
                    "status": "pool too small",
                }
            )
            continue
        rank, percentile = attempt_rank_percentile(rows, own)
        ranked_tests.append(
            {
                "test": test.title,
                "score_percent": own.score_percent,
                "rank": rank,
                "percentile": round(percentile, 2),
                "status": "ok",
            }
        )
        trend.append(
            {
                "date": own.completed_at.isoformat() if own.completed_at else None,
                "test": test.title,
                "percentile": round(percentile, 2),
            }
        )
        for question in test.snapshot:
            key = str(question["id"])
            topic_outcomes[question["topic"]].append(own.graded_answers.get(key, False))
    comparisons: list[dict[str, object]] = []
    for topic, outcomes in sorted(topic_outcomes.items()):
        differences = []
        own_accuracy = 100 * sum(outcomes) / len(outcomes)
        for test in tests:
            pool = ranked_attempts(db, test, settings=settings)
            if len(pool) < (settings or get_settings()).public_test_pool_minimum:
                continue
            for item in _question_pool_accuracy(test, pool):
                if item["topic"] == topic and item["percent_correct"] is not None:
                    differences.append(float(item["percent_correct"]))
        pool_accuracy = sum(differences) / len(differences) if differences else None
        rounded_pool_accuracy = (
            round(pool_accuracy, 2) if pool_accuracy is not None else None
        )
        accuracy_difference = (
            round(own_accuracy - pool_accuracy, 2)
            if pool_accuracy is not None
            else None
        )
        comparisons.append(
            {
                "topic": topic,
                "user_accuracy_percent": round(own_accuracy, 2),
                "pool_accuracy_percent": rounded_pool_accuracy,
                "difference_percent": accuracy_difference,
            }
        )
    available = [row for row in comparisons if row["difference_percent"] is not None]
    return {
        "ranked_tests": ranked_tests,
        "topic_accuracy_vs_pool": {
            "topics": comparisons,
            "strongest": max(
                available,
                key=lambda row: float(row["difference_percent"]),
                default=None,
            ),
            "weakest": min(
                available,
                key=lambda row: float(row["difference_percent"]),
                default=None,
            ),
        },
        "percentile_trend": sorted(trend, key=lambda row: str(row["date"] or "")),
    }


def pool_summary(
    db: Session, *, owner_id: int, settings: Settings | None = None
) -> dict[str, object]:
    settings = settings or get_settings()
    tests = list(db.scalars(select(PublicTest).where(PublicTest.status == "approved")))
    comparisons = []
    score_differences = []
    for test in tests:
        rows = ranked_attempts(db, test, settings=settings)
        if len(rows) < settings.public_test_pool_minimum:
            continue
        own = next((row for row in rows if row.user_id == owner_id), None)
        if own is None:
            continue
        rank, percentile = attempt_rank_percentile(rows, own)
        pool_mean = test_statistics(db, test, settings=settings)["mean_score_percent"]
        if pool_mean is not None:
            score_differences.append(float(own.score_percent or 0) - float(pool_mean))
        comparisons.append(
            {
                "test": test.title,
                "rank": rank,
                "percentile": round(percentile, 2),
                "ranked_attempts": len(rows),
            }
        )
    if not comparisons:
        return {
            "status": "pool too small",
            "rank": None,
            "percentile": None,
            "score_vs_pool_mean_percent": None,
            "tests": [],
        }
    average_score_difference = (
        round(sum(score_differences) / len(score_differences), 2)
        if score_differences
        else None
    )
    return {
        "status": "ok",
        "rank": round(sum(row["rank"] for row in comparisons) / len(comparisons), 2),
        "percentile": round(
            sum(row["percentile"] for row in comparisons) / len(comparisons), 2
        ),
        "score_vs_pool_mean_percent": average_score_difference,
        "tests": comparisons,
    }


def _cache_increment(cache: Cache, key: str, limit: int) -> None:
    try:
        count = cache.increment(key, 60)
    except RedisError as error:
        raise HTTPException(
            status_code=503, detail="Rate-limit service is unavailable."
        ) from error
    if count > limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded.")


def start_public_attempt(
    db: Session,
    test: PublicTest,
    user: User,
    *,
    cache: Cache,
    clock: Clock = utc_now,
    settings: Settings | None = None,
    shuffle: Callable[[list[int]], None] | None = None,
) -> tuple[PublicTestAttempt, str]:
    settings = settings or get_settings()
    _cache_increment(
        cache,
        f"public-test:start:{user.id}",
        settings.public_test_start_limit_per_minute,
    )
    order = list(range(test.question_count))
    if shuffle is None:
        secrets.SystemRandom().shuffle(order)
    else:
        shuffle(order)
    previous = db.scalar(
        select(PublicTestAttempt)
        .where(
            PublicTestAttempt.test_id == test.id,
            PublicTestAttempt.user_id == user.id,
        )
        .order_by(PublicTestAttempt.started_at.desc(), PublicTestAttempt.id.desc())
        .limit(1)
    )
    if previous is not None and len(order) > 1 and order == previous.shuffled_order:
        order = order[1:] + order[:1]
    token = secrets.token_urlsafe(32)
    attempt = PublicTestAttempt(
        test_id=test.id,
        user_id=user.id,
        started_at=_as_utc(clock()),
        shuffled_order=order,
        submission_token_hash=hashlib.sha256(token.encode()).hexdigest(),
        is_demo=test.is_demo,
    )
    db.add(attempt)
    db.flush()
    return attempt, token


def save_public_answers(
    test: PublicTest,
    attempt: PublicTestAttempt,
    *,
    answers: dict[int, str],
    token: str,
    clock: Clock = utc_now,
) -> int:
    _check_token(attempt, token)
    if attempt.completed_at is not None:
        raise HTTPException(status_code=409, detail="Attempt is already submitted.")
    if _as_utc(clock()) > _as_utc(attempt.started_at) + timedelta(
        seconds=test.time_limit_seconds
    ):
        raise HTTPException(status_code=409, detail="The test deadline has passed.")
    _validate_answers(test, answers)
    saved = dict(attempt.saved_answers)
    saved.update({str(key): value for key, value in answers.items()})
    attempt.saved_answers = saved
    return len(saved)


def submit_public_attempt(
    db: Session,
    test: PublicTest,
    attempt: PublicTestAttempt,
    *,
    answers: dict[int, str],
    token: str,
    clock: Clock = utc_now,
    settings: Settings | None = None,
) -> dict[str, object]:
    settings = settings or get_settings()
    _check_token(attempt, token)
    if attempt.completed_at is not None:
        raise HTTPException(status_code=409, detail="Attempt is already submitted.")
    _validate_answers(test, answers)
    now = _as_utc(clock())
    started_at = _as_utc(attempt.started_at)
    deadline = started_at + timedelta(seconds=test.time_limit_seconds)
    is_late = now > deadline
    saved = dict(attempt.saved_answers)
    if not is_late:
        saved.update({str(key): value for key, value in answers.items()})
    submitter = db.scalar(
        select(User).where(User.id == attempt.user_id).with_for_update()
    )
    if submitter is None:
        raise HTTPException(status_code=404, detail="User not found.")
    utc_day_start = now.astimezone(UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    daily_count = db.scalar(
        select(func.count(PublicTestAttempt.id)).where(
            PublicTestAttempt.user_id == attempt.user_id,
            PublicTestAttempt.completed_at >= utc_day_start,
        )
    )
    if int(daily_count or 0) >= settings.public_test_daily_submission_cap:
        raise HTTPException(status_code=429, detail="Daily submission cap reached.")
    graded = {}
    for question in test.snapshot:
        key = str(question["id"])
        if key not in saved:
            continue
        graded[key] = grade_answer(
            saved[key],
            question["correct_answer"],
            question_type=question["type"],
        )
    correct = sum(graded.values())
    attempt.saved_answers = saved
    attempt.graded_answers = graded
    attempt.correct_count = correct
    attempt.score_percent = round(100 * correct / test.question_count, 2)
    attempt.completed_at = now
    attempt.elapsed_seconds = max(0, int((now - started_at).total_seconds()))
    attempt.is_late = is_late
    minimum_duration = (
        settings.public_test_min_seconds_per_question * test.question_count
    )
    attempt.is_suspicious = (now - started_at).total_seconds() < minimum_duration
    previous_completed = db.scalar(
        select(func.count(PublicTestAttempt.id)).where(
            PublicTestAttempt.test_id == test.id,
            PublicTestAttempt.user_id == attempt.user_id,
            PublicTestAttempt.completed_at.is_not(None),
            PublicTestAttempt.id != attempt.id,
        )
    )
    attempt.is_first_completed = not bool(previous_completed)
    db.flush()
    return submission_result(db, test, attempt, settings=settings)


def _check_token(attempt: PublicTestAttempt, token: str) -> None:
    submitted_hash = hashlib.sha256(token.encode()).hexdigest()
    if not hmac.compare_digest(submitted_hash, attempt.submission_token_hash):
        raise HTTPException(status_code=403, detail="Invalid submission token.")


def _validate_answers(test: PublicTest, answers: dict[int, str]) -> None:
    if any(
        not isinstance(question_id, int)
        or question_id < 0
        or question_id >= test.question_count
        for question_id in answers
    ):
        raise HTTPException(status_code=422, detail="Unknown question in answer list.")
    if any(len(answer) > 2000 for answer in answers.values()):
        raise HTTPException(status_code=422, detail="Answer exceeds the size limit.")


def report_public_test(
    db: Session,
    test: PublicTest,
    user: User,
    reason: str,
    *,
    cache: Cache,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    _cache_increment(
        cache,
        f"public-test:report:{user.id}",
        settings.public_test_report_limit_per_minute,
    )
    prior = db.scalar(
        select(PublicTestReport.id).where(
            PublicTestReport.test_id == test.id,
            PublicTestReport.reporter_id == user.id,
        )
    )
    if prior is not None:
        raise HTTPException(
            status_code=409, detail="You have already reported this test."
        )
    db.add(
        PublicTestReport(test_id=test.id, reporter_id=user.id, reason=reason.strip())
    )
    db.flush()
    report_count = db.scalar(
        select(func.count(PublicTestReport.id)).where(
            PublicTestReport.test_id == test.id
        )
    )
    if int(report_count or 0) >= 3:
        test.status = "hidden"


def report_queue(db: Session) -> list[dict[str, object]]:
    reported_test_ids = select(PublicTestReport.test_id).distinct()
    tests = list(
        db.scalars(
            select(PublicTest)
            .where(
                PublicTest.status.in_(("pending", "hidden"))
                | PublicTest.id.in_(reported_test_ids)
            )
            .order_by(PublicTest.created_at, PublicTest.id)
        )
    )
    output = []
    for test in tests:
        submitter = db.get(User, test.created_by)
        reports = list(
            db.scalars(
                select(PublicTestReport)
                .where(PublicTestReport.test_id == test.id)
                .order_by(PublicTestReport.created_at)
            )
        )
        output.append(
            {
                "test_id": test.id,
                "title": test.title,
                "status": test.status,
                "submitted_by": (
                    submitter.public_handle
                    if submitter is not None and submitter.show_on_leaderboards
                    else "Anonymous"
                ),
                "reports": [
                    {
                        "reason": report.reason,
                        "created_at": report.created_at.isoformat(),
                    }
                    for report in reports
                ],
            }
        )
    return output
