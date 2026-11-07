"""Seed anonymous, reproducible public-test demo data for local development."""

import json
import os
import re
import sys
from pathlib import Path

if os.environ.get("BACKEND", "local").strip().casefold() == "prod":
    raise SystemExit("Demo seeding is disabled when BACKEND=prod.")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from alembic.config import Config  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from alembic import command  # noqa: E402
from app.core.config import Settings, get_settings  # noqa: E402

Settings.model_config["env_file"] = None
get_settings.cache_clear()

from app.core.database import SessionLocal  # noqa: E402
from app.models import PublicTest, PublicTestAttempt, Question, Quiz, User  # noqa: E402
from app.models.entities import utc_now  # noqa: E402
from app.services.public_tests import (  # noqa: E402
    attempt_rank_percentile,
    ranked_attempts,
    snapshot_questions,
    submission_result,
    test_leaderboard,
)


def _sample_test_specs() -> list[dict[str, object]]:
    """Derive small, synthetic questions from the checked-in sample PDFs."""
    import pymupdf

    sample_dir = REPOSITORY_ROOT / "data" / "samples"
    sample_files = sorted(sample_dir.glob("*.pdf"))
    if not sample_files:
        raise FileNotFoundError(f"No sample PDFs found in {sample_dir}.")
    labels = {
        "text": "Text concepts",
        "tables": "Table concepts",
        "scanned": "Scanned-text concepts",
    }
    fallback_terms = ("sample", "document", "concept")
    specs = []
    for index, sample_path in enumerate(sample_files):
        with pymupdf.open(sample_path) as document:
            text = " ".join(page.get_text("text") for page in document)
        terms = list(
            dict.fromkeys(
                word.casefold()
                for word in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", text)
            )
        )
        terms = (terms + list(fallback_terms))[:3]
        topic = labels.get(sample_path.stem.casefold(), f"Sample {index + 1} concepts")
        specs.append(
            {
                "title": f"Demo Sample Test {index + 1}",
                "subject": "Sample document concepts",
                "topics": [topic],
                "questions": tuple(
                    (
                        f"Which term appears at position {position} in the sample?",
                        term,
                        topic,
                    )
                    for position, term in enumerate(terms, start=1)
                ),
            }
        )
    return specs


def _demo_user(db: Session, handle: str) -> User:
    user = db.scalar(select(User).where(User.public_handle.ilike(handle)))
    if user is None:
        user = User(
            email=f"{handle}@demo.invalid",
            full_name="Demo learner",
            password_hash="demo-not-for-login",
            role="student",
            public_handle=handle,
            show_on_leaderboards=True,
            is_demo=True,
        )
        db.add(user)
        db.flush()
    else:
        user.is_demo = True
    return user


def _create_or_get_test(
    db: Session,
    creator: User,
    item: dict[str, object],
) -> PublicTest:
    title = str(item["title"])
    test = db.scalar(
        select(PublicTest).where(
            PublicTest.title == title, PublicTest.is_demo.is_(True)
        )
    )
    if test is not None:
        return test
    quiz = db.scalar(
        select(Quiz).where(Quiz.owner_id == creator.id, Quiz.title == title)
    )
    if quiz is None:
        quiz = Quiz(owner_id=creator.id, title=title, engine="classic", is_demo=True)
        db.add(quiz)
        db.flush()
        for prompt, answer, topic in item["questions"]:
            db.add(
                Question(
                    quiz_id=quiz.id,
                    type="short_answer",
                    difficulty="easy",
                    prompt=prompt,
                    options=[],
                    answer=answer,
                    explanation=f"Sample concept: {topic}.",
                    topic=topic,
                )
            )
        db.flush()
    questions = list(
        db.scalars(
            select(Question).where(Question.quiz_id == quiz.id).order_by(Question.id)
        )
    )
    snapshot = snapshot_questions(questions)
    test = PublicTest(
        title=title,
        description="Synthetic sample questions for local public-test demos.",
        subject=str(item["subject"]),
        topic_labels=list(item["topics"]),
        time_limit_seconds=900,
        question_count=len(snapshot),
        snapshot=snapshot,
        status="approved",
        created_by=creator.id,
        source_quiz_id=quiz.id,
        is_demo=True,
    )
    db.add(test)
    db.flush()
    return test


def _create_attempts(db: Session, test: PublicTest, users: list[User]) -> None:
    for index, user in enumerate(users):
        exists = db.scalar(
            select(PublicTestAttempt.id).where(
                PublicTestAttempt.test_id == test.id,
                PublicTestAttempt.user_id == user.id,
                PublicTestAttempt.is_demo.is_(True),
                PublicTestAttempt.completed_at.is_not(None),
            )
        )
        if exists is not None:
            continue
        score_pattern = (index * 2 + 1) % (test.question_count + 1)
        graded = {
            str(question["id"]): position < score_pattern
            for position, question in enumerate(test.snapshot)
        }
        now = utc_now()
        db.add(
            PublicTestAttempt(
                test_id=test.id,
                user_id=user.id,
                started_at=now.replace(microsecond=0),
                completed_at=now,
                shuffled_order=list(range(test.question_count)),
                saved_answers={},
                graded_answers=graded,
                score_percent=round(
                    100 * sum(graded.values()) / test.question_count, 2
                ),
                correct_count=sum(graded.values()),
                elapsed_seconds=90 + index,
                is_first_completed=True,
                is_suspicious=False,
                is_late=False,
                submission_token_hash=f"demo-{test.id}-{user.id}".ljust(64, "0")[:64],
                is_demo=True,
            )
        )


def main() -> None:
    """Apply migrations, seed three sample tests, and print a local demo summary."""
    settings = get_settings()
    if settings.backend == "prod":
        raise SystemExit("Demo seeding is disabled when BACKEND=prod.")
    alembic_config = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic_config.set_main_option(
        "script_location", str(BACKEND_ROOT / "alembic").replace("%", "%%")
    )
    command.upgrade(alembic_config, "head")

    with SessionLocal() as db:
        author = _demo_user(db, "demo-author")
        demo_users = [
            _demo_user(db, f"demo-learner-{index:02d}") for index in range(1, 10)
        ]
        me = _demo_user(db, "demo-me")
        tests = [_create_or_get_test(db, author, item) for item in _sample_test_specs()]
        _create_attempts(db, tests[0], demo_users + [me])
        db.commit()
        test = tests[0]
        my_attempt = db.scalar(
            select(PublicTestAttempt).where(
                PublicTestAttempt.test_id == test.id,
                PublicTestAttempt.user_id == me.id,
                PublicTestAttempt.is_demo.is_(True),
            )
        )
        pool = ranked_attempts(db, test)
        if my_attempt is None:
            raise RuntimeError("Demo attempt was not created.")
        rank, percentile = attempt_rank_percentile(pool, my_attempt)
        print(
            json.dumps(
                {
                    "demo_test": test.title,
                    "leaderboard": test_leaderboard(db, test, caller=me),
                    "my_rank": rank,
                    "my_percentile": round(percentile, 2),
                    "per_topic_comparison": submission_result(db, test, my_attempt)[
                        "pool_comparison"
                    ]["topics"],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
