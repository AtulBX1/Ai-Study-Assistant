"""Validated quiz payloads shared by generation and API layers."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QuestionType(StrEnum):
    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    FILL_BLANK = "fill_in_the_blank"
    SHORT_ANSWER = "short_answer"


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


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
    engine: str = Field(pattern="^(classic|llm)$")
    topic: str = Field(default="General", max_length=255)
    provider: str | None = Field(default=None, max_length=64)
    source_page_url: str | None = None

    @model_validator(mode="after")
    def validate_options(self) -> "QuizQuestion":
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
    topics: list[str] = Field(default_factory=list, max_length=30)
    chunk_ids: list[int] = Field(default_factory=list, max_length=100)
    question_count: int = Field(default=10, ge=1, le=50)
    engine: str = Field(default="classic", pattern="^(classic|llm)$")
    difficulty: Difficulty | None = None

    @model_validator(mode="after")
    def valid_range(self) -> "GenerationRequest":
        if self.page_start and self.page_end and self.page_end < self.page_start:
            raise ValueError("page_end must be at least page_start.")
        return self
