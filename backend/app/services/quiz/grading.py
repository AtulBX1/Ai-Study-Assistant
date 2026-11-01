"""Objective and semantic answer grading plus retake selection."""

from collections.abc import Callable, Iterable

from app.services.quiz.validation import token_f1


def grade_answer(
    answer: str,
    correct_answer: str,
    *,
    question_type: str,
    similarity: Callable[[str, str], float] | None = None,
    threshold: float = 0.78,
    rubric_score: float | None = None,
    rubric: Callable[[str, str], float | None] | None = None,
) -> bool:
    """Exactly grade objective questions; score free text semantically."""
    if question_type in {"multiple_choice", "true_false", "fill_in_the_blank"}:
        return " ".join(answer.casefold().split()) == " ".join(
            correct_answer.casefold().split()
        )
    score = (
        similarity(answer, correct_answer)
        if similarity
        else token_f1(answer, correct_answer)
    )
    if rubric is not None:
        rubric_score = rubric(answer, correct_answer)
    if rubric_score is not None:
        return rubric_score >= threshold
    return score >= threshold


def weak_question_ids(
    question_ids: Iterable[int], answers: dict[int, bool], *, threshold: float = 0.6
) -> list[int]:
    """Select incorrect questions and questions from low-performing attempts."""
    ids = list(question_ids)
    if not ids:
        return []
    correct_ratio = sum(bool(answers.get(item)) for item in ids) / len(ids)
    if correct_ratio < threshold:
        return [item for item in ids if not answers.get(item, False)] or ids
    return [item for item in ids if not answers.get(item, False)]
