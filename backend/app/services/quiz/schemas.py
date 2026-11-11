"""Validated quiz payloads shared by generation and API layers."""

import re
import unicodedata
from enum import StrEnum
from typing import Any

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class QuestionType(StrEnum):
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    FILL_BLANK = "fill_in_the_blank"
    SHORT_ANSWER = "short_answer"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class QuizEngine(StrEnum):
    AUTO = "auto"
    OFFLINE = "offline"
    AI = "ai"


class QuizQuestion(BaseModel):
    """Question data validated before it is persisted or shown to a student."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=12, max_length=1000)
    type: QuestionType
    options: list[str] | None = None
    correct_answer: str = Field(min_length=1, max_length=1000)
    evidence: str = Field(min_length=1, max_length=2000)
    explanation: str = Field(min_length=1, max_length=2000)
    source_chunk_id: int = Field(gt=0)
    page: int = Field(ge=1)
    difficulty: Difficulty
    engine: str = Field(pattern="^(classic|llm|offline|ai)$")
    topic: str = Field(default="General", max_length=255)
    provider: str | None = Field(default=None, max_length=64)
    source_page_url: str | None = None

    @model_validator(mode="after")
    def validate_options(self) -> "QuizQuestion":
        if self.options:
            for option in self.options:
                if not option.strip():
                    raise ValueError("Options must not be empty.")
                filtered = re.sub(
                    r"(?<!\w)(?:C\+\+|C#|F#)(?!\w)",
                    "",
                    option,
                    flags=re.IGNORECASE,
                )
                if any(
                    unicodedata.category(character).startswith("S")
                    or character
                    in {"•", "●", "▪", "◦", "◆", "◇", "■", "□", "\u200d", "\ufe0f"}
                    for character in filtered
                ):
                    raise ValueError("Options must not contain symbols or emoji.")
        if self.type == QuestionType.MULTIPLE_CHOICE:
            if self.options is None or len(self.options) < 4:
                raise ValueError("Multiple choice requires at least four options.")
            normalized = [option.strip().casefold() for option in self.options]
            if len(set(normalized)) != len(normalized):
                raise ValueError("Options must be unique.")
            if (
                sum(
                    option.casefold() == self.correct_answer.casefold()
                    for option in self.options
                )
                != 1
            ):
                raise ValueError("Exactly one option must match the correct answer.")
        elif self.options is not None and self.type != QuestionType.TRUE_FALSE:
            raise ValueError("Only multiple choice and true/false accept options.")
        if self.type == QuestionType.TRUE_FALSE and self.options != ["True", "False"]:
            raise ValueError("True/false options must be True and False.")
        return self


class GenerationRequest(BaseModel):
    """Bounded quiz-generation request."""

    title: str = Field(default="Study quiz", min_length=1, max_length=255)
    document_ids: list[int] = Field(min_length=1, max_length=10)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    chapter: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        validation_alias=AliasChoices("chapter", "chapter_scope"),
    )
    topics: list[str] = Field(default_factory=list, max_length=30)
    chunk_ids: list[int] = Field(default_factory=list, max_length=100)
    question_types: list[QuestionType] = Field(
        default_factory=lambda: [
            QuestionType.MULTIPLE_CHOICE,
            QuestionType.TRUE_FALSE,
            QuestionType.FILL_BLANK,
            QuestionType.SHORT_ANSWER,
        ],
        min_length=1,
        max_length=4,
    )
    count: int = Field(
        default=10,
        ge=1,
        le=50,
        validation_alias=AliasChoices("count", "question_count"),
    )
    engine: QuizEngine = QuizEngine.AUTO
    difficulty: Difficulty | None = None

    @field_validator("engine", mode="before")
    @classmethod
    def normalize_legacy_engine(cls, value: Any) -> Any:
        return (
            {"classic": "offline", "llm": "ai"}.get(value, value)
            if isinstance(value, str)
            else value
        )

    @model_validator(mode="after")
    def valid_range(self) -> "GenerationRequest":
        if len(set(self.question_types)) != len(self.question_types):
            raise ValueError("question_types must not contain duplicates.")
        if self.page_start and self.page_end and self.page_end < self.page_start:
            raise ValueError("page_end must be at least page_start.")
        if self.chapter and (self.page_start or self.page_end):
            raise ValueError("Use either chapter or page range, not both.")
        return self
