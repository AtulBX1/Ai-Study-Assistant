"""Deterministic study-plan scheduling with spaced revision."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk, Document, DocumentPage, TopicStat
from app.services.study.summaries import extract_sections

MAX_PLAN_DOCUMENTS = 20
MAX_PLAN_DAYS = 366
_DIFFICULTY_MULTIPLIER = {"easy": 0.9, "medium": 1.0, "hard": 1.25}
_NON_TOPIC_TITLE = re.compile(
    r"^(?:correct\s+answer\b|explanation\b|solution\b|question\s*\d+\b|"
    r"quiz\b|references\b)|\?\s*$",
    re.IGNORECASE,
)
_SENTENCE_TITLE_VERBS = re.compile(r"\b(?:is|are|can|should|means|refers\s+to)\b", re.I)


def _is_study_section_title(title: str) -> bool:
    normalized = " ".join(title.split())
    words = normalized.split()
    return bool(
        normalized
        and normalized[0].isalnum()
        and not _NON_TOPIC_TITLE.search(normalized)
        and not re.search(r"[.!?]", normalized)
        and not (len(words) >= 8 and _SENTENCE_TITLE_VERBS.search(normalized))
        and len(normalized) <= 120
    )


@dataclass(frozen=True)
class StudyTopic:
    """A document section with estimated effort and learner performance."""

    document_id: int
    title: str
    page_start: int
    page_end: int
    difficulty: str
    weak_score: float
    importance: float
    study_minutes: int


def collect_study_topics(
    db: Session, *, owner_id: int, document_ids: list[int]
) -> list[StudyTopic]:
    """Derive planner topics from stored document sections and learner data."""
    if not document_ids or len(document_ids) > MAX_PLAN_DOCUMENTS:
        raise ValueError(f"Select between 1 and {MAX_PLAN_DOCUMENTS} documents.")
    documents = list(
        db.scalars(
            select(Document).where(
                Document.owner_id == owner_id,
                Document.id.in_(document_ids),
            )
        )
    )
    if {document.id for document in documents} != set(document_ids):
        raise LookupError("One or more selected documents were not found.")

    stats = {
        stat.topic.casefold(): stat
        for stat in db.scalars(select(TopicStat).where(TopicStat.owner_id == owner_id))
    }
    topics: list[StudyTopic] = []
    for document in documents:
        pages = list(
            db.scalars(
                select(DocumentPage)
                .where(DocumentPage.document_id == document.id)
                .order_by(DocumentPage.page_number)
            )
        )
        sections = extract_sections(pages)
        chunks = list(
            db.scalars(
                select(Chunk)
                .where(Chunk.doc_id == document.id)
                .order_by(Chunk.page_start, Chunk.chunk_index)
            )
        )
        for section in sections:
            if not _is_study_section_title(section.title):
                continue
            section_chunks = [
                chunk
                for chunk in chunks
                if chunk.page_start <= section.page_end
                and chunk.page_end >= section.page_start
            ]
            difficulty = max(
                (
                    (chunk.difficulty_label or "medium").casefold()
                    for chunk in section_chunks
                ),
                key=lambda label: _DIFFICULTY_MULTIPLIER.get(label, 1.0),
                default="medium",
            )
            stat = stats.get(section.title.casefold())
            weak_score = (
                max(0.0, min(1.0, 1 - stat.correct / stat.attempts))
                if stat and stat.attempts
                else 0.0
            )
            pages_count = max(1, section.page_end - section.page_start + 1)
            importance = (
                1.0 + weak_score + 0.25 * _DIFFICULTY_MULTIPLIER.get(difficulty, 1.0)
            )
            estimated_minutes = round(
                pages_count
                * 10
                * _DIFFICULTY_MULTIPLIER.get(difficulty, 1.0)
                * (1 + weak_score * 0.75)
            )
            topics.append(
                StudyTopic(
                    document_id=document.id,
                    title=section.title,
                    page_start=section.page_start,
                    page_end=section.page_end,
                    difficulty=difficulty,
                    weak_score=weak_score,
                    importance=importance,
                    study_minutes=max(15, estimated_minutes),
                )
            )
    return sorted(
        topics,
        key=lambda topic: (
            -topic.weak_score,
            -topic.importance,
            topic.title.casefold(),
            topic.document_id,
        ),
    )


def generate_study_plan(
    topics: list[StudyTopic],
    *,
    exam_date: date,
    daily_minutes: int,
    today: date,
) -> dict[str, Any]:
    """Create a capped day-by-day plan, reporting topics that do not fit."""
    days = (exam_date - today).days + 1
    if days <= 0 or days > MAX_PLAN_DAYS:
        raise ValueError("exam_date must be between today and one year from today.")
    if daily_minutes < 1:
        raise ValueError("daily_minutes must be positive.")
    dates = [today + timedelta(days=offset) for offset in range(days)]
    plan_days: dict[date, list[dict[str, Any]]] = {day: [] for day in dates}
    used_minutes = dict.fromkeys(dates, 0)
    prioritized_topics = sorted(
        topics,
        key=lambda topic: (
            -topic.weak_score,
            -topic.importance,
            topic.title.casefold(),
            topic.document_id,
        ),
    )

    # Reserve the exam day and the preceding day for revision only.
    study_days = dates[:-2] if len(dates) > 1 else []
    study_capacity_per_day = daily_minutes - min(15, max(0, daily_minutes - 30))
    total_study_capacity = len(study_days) * study_capacity_per_day
    included: list[StudyTopic] = []
    omitted: list[dict[str, Any]] = []
    capacity_left = total_study_capacity
    for topic in prioritized_topics:
        if topic.study_minutes <= capacity_left:
            included.append(topic)
            capacity_left -= topic.study_minutes
        else:
            omitted.append(
                {
                    "document_id": topic.document_id,
                    "topic": topic.title,
                    "page_start": topic.page_start,
                    "page_end": topic.page_end,
                    "reason": "insufficient_available_study_time",
                }
            )

    first_study_date: dict[tuple[int, str, int, int], date] = {}
    cursor = 0
    for topic in included:
        key = (topic.document_id, topic.title, topic.page_start, topic.page_end)
        remaining = topic.study_minutes
        first_study_date[key] = study_days[cursor]
        while remaining:
            while (
                cursor < len(study_days)
                and used_minutes[study_days[cursor]] >= study_capacity_per_day
            ):
                cursor += 1
            if cursor >= len(study_days):
                omitted.append(
                    {
                        "document_id": topic.document_id,
                        "topic": topic.title,
                        "page_start": topic.page_start,
                        "page_end": topic.page_end,
                        "reason": "insufficient_available_study_time",
                    }
                )
                break
            day = study_days[cursor]
            allocated = min(remaining, study_capacity_per_day - used_minutes[day])
            if day == first_study_date[key] and allocated > 0:
                quiz_minutes = min(10, allocated)
                read_minutes = allocated - quiz_minutes
                if read_minutes:
                    plan_days[day].append(
                        _activity(topic, "read_summary", read_minutes)
                    )
                plan_days[day].append(_activity(topic, "take_quiz", quiz_minutes))
            else:
                plan_days[day].append(_activity(topic, "read_summary", allocated))
            used_minutes[day] += allocated
            remaining -= allocated
        if remaining:
            omitted = [
                item
                for item in omitted
                if not (
                    item["document_id"] == topic.document_id
                    and item["topic"] == topic.title
                    and item["page_start"] == topic.page_start
                    and item["page_end"] == topic.page_end
                )
            ]
            omitted.append(
                {
                    "document_id": topic.document_id,
                    "topic": topic.title,
                    "page_start": topic.page_start,
                    "page_end": topic.page_end,
                    "reason": "insufficient_available_study_time",
                }
            )

    for topic in included:
        key = (topic.document_id, topic.title, topic.page_start, topic.page_end)
        first_day = first_study_date[key]
        for offset in (1, 3, 7):
            revision_day = first_day + timedelta(days=offset)
            if revision_day not in plan_days:
                continue
            activity_type = (
                "revise_weak_topic" if topic.weak_score > 0 else "review_flashcards"
            )
            revision_minutes = min(15, daily_minutes)
            if used_minutes[revision_day] + revision_minutes > daily_minutes:
                continue
            plan_days[revision_day].append(
                _activity(topic, activity_type, revision_minutes)
            )
            used_minutes[revision_day] += revision_minutes
    if dates:
        exam_day = dates[-1]
        last_topic = next(
            (topic for topic in included if topic.weak_score > 0),
            included[0] if included else None,
        )
        if not plan_days[exam_day]:
            plan_days[exam_day].append(
                _activity(last_topic, "revise_weak_topic", min(15, daily_minutes))
                if last_topic
                else {
                    "activity_type": "review_flashcards",
                    "topic": "All selected topics",
                    "document_id": None,
                    "page_start": None,
                    "page_end": None,
                    "minutes": min(15, daily_minutes),
                }
            )
            used_minutes[exam_day] += min(15, daily_minutes)

    result_days = []
    for day in dates:
        activities = plan_days[day]
        if day == exam_date or day == exam_date - timedelta(days=1):
            activities = [
                activity
                for activity in activities
                if activity["activity_type"]
                in {"review_flashcards", "revise_weak_topic"}
            ]
            if not activities:
                fallback_topic = next(
                    (topic for topic in included if topic.weak_score > 0),
                    included[0] if included else None,
                )
                activities = [
                    (
                        _activity(
                            fallback_topic, "revise_weak_topic", min(15, daily_minutes)
                        )
                        if fallback_topic
                        else {
                            "activity_type": "review_flashcards",
                            "topic": "All selected topics",
                            "document_id": None,
                            "page_start": None,
                            "page_end": None,
                            "minutes": min(15, daily_minutes),
                        }
                    )
                ]
        result_days.append(
            {
                "date": day.isoformat(),
                "activities": activities,
                "total_minutes": sum(activity["minutes"] for activity in activities),
            }
        )
    return {
        "exam_date": exam_date.isoformat(),
        "daily_minutes": daily_minutes,
        "days": result_days,
        "omitted_topics": omitted,
    }


def _activity(
    topic: StudyTopic | None, activity_type: str, minutes: int
) -> dict[str, Any]:
    if topic is None:
        return {
            "activity_type": activity_type,
            "topic": "All selected topics",
            "document_id": None,
            "page_start": None,
            "page_end": None,
            "minutes": minutes,
        }
    return {
        "activity_type": activity_type,
        "topic": topic.title,
        "document_id": topic.document_id,
        "page_start": topic.page_start,
        "page_end": topic.page_end,
        "minutes": minutes,
    }
