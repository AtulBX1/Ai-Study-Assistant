"""Authenticated, owner-scoped student analytics endpoints."""

from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query

from app.dependencies.auth import DatabaseSession, get_current_user
from app.models import User
from app.services.analytics import student

router = APIRouter(prefix="/analytics", tags=["analytics"])
AuthenticatedUser = Annotated[User, Depends(get_current_user)]


def _timezone_for_user(user: User) -> ZoneInfo:
    try:
        return student.get_timezone(user.timezone)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/score-history")
def get_score_history(
    db: DatabaseSession, user: AuthenticatedUser
) -> dict[str, object]:
    """Return one dated score point per owned submitted attempt."""
    return student.score_history(
        db, owner_id=user.id, timezone=_timezone_for_user(user)
    )


@router.get("/topic-accuracy")
def get_topic_accuracy(
    db: DatabaseSession, user: AuthenticatedUser
) -> dict[str, object]:
    """Return owner-scoped topic correctness, counts, and source pages."""
    return student.topic_accuracy(db, owner_id=user.id)


@router.get("/weak-topics")
def get_weak_topics(
    db: DatabaseSession,
    user: AuthenticatedUser,
    threshold_percent: Annotated[float, Query(ge=0, le=100)] = 60,
) -> dict[str, object]:
    """List topics with three or more answers below the accuracy threshold."""
    return student.weak_topics(
        db, owner_id=user.id, threshold_percent=threshold_percent
    )


@router.get("/study-time")
def get_study_time(
    db: DatabaseSession,
    user: AuthenticatedUser,
    days: Annotated[int, Query(ge=1, le=366)] = 30,
    seconds_per_card: Annotated[int, Query(ge=0, le=3600)] = 30,
    seconds_per_chat_message: Annotated[int, Query(ge=0, le=3600)] = 300,
) -> dict[str, object]:
    """Return estimated daily minutes over a bounded date window."""
    return student.study_time(
        db,
        owner_id=user.id,
        timezone=_timezone_for_user(user),
        days=days,
        seconds_per_card=seconds_per_card,
        seconds_per_chat_message=seconds_per_chat_message,
    )


@router.get("/streaks")
def get_streaks(
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, object]:
    """Return activity streaks using the learner's configured timezone."""
    return student.streaks(db, owner_id=user.id, timezone=_timezone_for_user(user))


@router.get("/flashcard-retention")
def get_flashcard_retention(
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, object]:
    """Return weekly review retention and due/mature/new card counts."""
    return student.flashcard_retention(
        db, owner_id=user.id, timezone=_timezone_for_user(user)
    )


@router.get("/summary")
def get_summary(
    db: DatabaseSession,
    user: AuthenticatedUser,
    threshold_percent: Annotated[float, Query(ge=0, le=100)] = 60,
) -> dict[str, object]:
    """Return headline quiz, topic, streak, and due-card measures."""
    return student.summary(
        db,
        owner_id=user.id,
        timezone=_timezone_for_user(user),
        threshold_percent=threshold_percent,
    )
