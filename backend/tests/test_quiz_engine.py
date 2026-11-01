"""CI-safe quiz engine tests with injected generators and QA models."""

import json
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from app.services.quiz.exam_export import export_docx, export_pdf
from app.services.quiz.generation import (
    ClassicEngine,
    LLMEngine,
    StructuredOutputError,
    balance_true_false_questions,
    build_false_statement,
    clean_chunk_text,
    complete_source_sentences,
    extract_candidates,
    extract_json_value,
    is_readable_statement,
    normalize_question_item,
)
from app.services.quiz.grading import grade_answer, weak_question_ids
from app.services.quiz.schemas import QuizQuestion
from app.services.quiz.validation import (
    distractor_is_valid,
    validate_generated,
    validate_stem,
)
from app.services.rag.providers import RateLimitError


def _question(**overrides):
    data = {
        "question": "Which organization developed the Python language?",
        "type": "multiple_choice",
        "options": ["Python Software Foundation", "Java", "C++", "Ruby"],
        "correct_answer": "Python Software Foundation",
        "evidence": "The Python Software Foundation developed the Python language.",
        "explanation": "The Python Software Foundation developed the Python language.",
        "source_chunk_id": 7,
        "page": 2,
        "difficulty": "medium",
        "engine": "classic",
        "topic": "Python",
    }
    data.update(overrides)
    return QuizQuestion.model_validate(data)


def test_schema_rejects_nonunique_and_wrong_options():
    import pytest

    with pytest.raises(ValueError):
        _question(options=["A", "A", "B", "C"])
    with pytest.raises(ValueError):
        _question(
            options=["A", "B", "C", "D"],
            correct_answer="Python Software Foundation",
        )


def test_round_trip_answer_source_and_duplicate_rejection():
    item = _question()
    source = "The Python Software Foundation developed the Python language."
    assert validate_generated(
        item, source, qa_model=lambda *_: "Python Software Foundation"
    )[0]
    assert (
        validate_generated(item, source, qa_model=lambda *_: "Ruby")[1]
        == "round_trip_failed"
    )
    assert (
        validate_generated(
            item,
            source,
            qa_model=lambda *_: "Python Software Foundation",
            prior_questions=[item.question],
        )[1]
        == "duplicate"
    )


def test_answer_must_be_in_source():
    assert (
        validate_generated(
            _question(),
            "An unrelated passage.",
            qa_model=lambda *_: "Python Software Foundation",
        )[1]
        == "evidence_not_in_source"
    )


def test_answer_must_align_with_the_stem_sentence():
    item = _question(
        question="What is the name of a tokenizer?",
        correct_answer="Python Software Foundation",
    )
    source = (
        "The Python Software Foundation develops Python. "
        "A tokenizer splits text into tokens."
    )
    assert (
        validate_generated(
            item,
            source,
            qa_model=lambda *_: "Python Software Foundation",
        )[1]
        == "evidence_not_in_source"
    )


def test_distractor_filters_aliases_substrings_and_wrong_types():
    assert not distractor_is_valid("Python", "Python language")
    assert not distractor_is_valid(
        "New York", "York", candidate_type="GPE", answer_type="ORG"
    )
    assert not distractor_is_valid("similar", "different", similarity=0.95)
    assert distractor_is_valid(
        "Java", "Python", candidate_type="LANG", answer_type="LANG", similarity=0.6
    )


def test_grading_and_retake_selection():
    assert grade_answer("true", "True", question_type="true_false")
    assert not grade_answer("Almost", "True", question_type="true_false")
    assert grade_answer(
        "the python foundation",
        "Python Software Foundation",
        question_type="short_answer",
        similarity=lambda *_: 0.9,
    )
    assert weak_question_ids([1, 2, 3], {1: True, 2: False, 3: False}) == [2, 3]


def test_exam_exports_are_readable_containers():
    sections = {
        "Multiple Choice": [
            {
                "question": "What is Python?",
                "options": ["A", "B", "C", "D"],
                "correct_answer": "A",
                "explanation": "Defined in source.",
            }
        ]
    }
    assert export_pdf("Quiz", sections).startswith(b"%PDF-1.4")
    archive = ZipFile(BytesIO(export_docx("Quiz", sections)))
    assert "word/document.xml" in archive.namelist()


def test_llm_strips_prose_and_fences_then_retries_strictly():
    payload = {
        "question": "True or false: Cats are mammals living in homes.",
        "type": "true_false",
        "options": ["True", "False"],
        "correct_answer": "True",
        "evidence": "Cats are mammals living in homes.",
        "explanation": "Cats are mammals living in homes.",
        "source_chunk_id": 999,
        "page": 99,
        "difficulty": "easy",
    }

    class FakeProvider:
        def __init__(self):
            self.calls = []

        def generate(self, prompt, system_prompt=None):
            self.calls.append((prompt, system_prompt))
            return (
                "not JSON"
                if len(self.calls) == 1
                else "Here you go:\n```json\n[" + json.dumps(payload) + "]\n```"
            )

    provider = FakeProvider()
    engine = LLMEngine(provider)
    chunk = SimpleNamespace(id=7, page=3, text="Cats are mammals living in homes.")
    questions = engine.generate(chunk, question_quota=1)
    assert len(provider.calls) == 2
    assert "STRICT RETRY" in provider.calls[1][0]
    assert engine.last_parse_failures == 1
    assert questions[0].source_chunk_id == 7
    assert questions[0].page == 3


def test_llm_handles_think_fences_aliases_extra_keys_and_truncation():
    complete = {
        "stem": "True or false: Cats are mammals living in family homes.",
        "question_type": "true/false",
        "choices": ["yes", "no"],
        "answer": "True",
        "evidence": "Cats are mammals living in family homes.",
        "rationale": "The source states this fact.",
        "unrecognized": "ignored",
    }
    assert extract_json_value(
        "<think>private reasoning</think>Here is JSON:\n```json\n"
        + json.dumps([complete])
        + "\n```"
    ) == [complete]
    normalized = normalize_question_item(complete)
    assert normalized["question"].startswith("True or false:")
    assert normalized["type"] == "true_false"
    assert normalized["options"] == ["True", "False"]

    class TruncatedOnceProvider:
        def __init__(self):
            self.last_diagnostics = {}
            self.output_caps = []

        def generate_json(self, prompt, system_prompt=None, max_tokens=None, **kwargs):
            self.output_caps.append(max_tokens)
            self.last_diagnostics = {
                "finish_reason": "length" if len(self.output_caps) == 1 else "stop",
                "raw_output": "[{" if len(self.output_caps) == 1 else "",
            }
            if len(self.output_caps) == 1:
                return "[{"
            return json.dumps([complete])

    provider = TruncatedOnceProvider()
    engine = LLMEngine(provider, min_delay_seconds=0, parse_retries=2)
    chunk = SimpleNamespace(
        id=701,
        page=4,
        text="Cats are mammals living in family homes. " * 100,
    )
    questions = engine.generate(chunk, question_quota=1)
    assert len(questions) == 1
    assert provider.output_caps == [1800, 2000]
    assert engine.truncated_outputs == 1


def test_llm_response_schema_mode_and_two_parse_failures():
    class SchemaProvider:
        def __init__(self):
            self.schema = None
            self.calls = 0

        def generate_structured(self, prompt, *, schema, system_prompt=None):
            self.schema = schema
            self.calls += 1
            return "still not JSON"

    provider = SchemaProvider()
    engine = LLMEngine(provider)
    with pytest.raises(StructuredOutputError) as error:
        engine.generate(SimpleNamespace(id=1, page=1, text="Source"), question_quota=1)
    assert provider.calls == 2
    assert provider.schema["type"] == "array"
    assert error.value.parse_failures == 2
    assert engine.last_parse_failures == 2


def test_false_statements_swap_readable_same_type_terms_and_honor_quota():
    source = "Cats are mammals that often live with people inside family homes."
    assert (
        build_false_statement(source, "Cats", "Dogs")
        == "Dogs are mammals that often live with people inside family homes."
    )
    assert build_false_statement(source, "Cats", "Very large dogs") is None
    assert (
        build_false_statement(
            "Cats are mammals that often live with people inside family homes",
            "Cats",
            "Dogs",
        )
        is None
    )
    assert is_readable_statement(source)

    engine = ClassicEngine(
        generator=lambda *_: "Why do cats live in homes?",
        entity_extractor=lambda _: [
            {"text": "Cats", "label": "ANIMAL"},
            {"text": "Dogs", "label": "ANIMAL"},
        ],
        qa_model=lambda *_: "Cats",
    )
    chunk = SimpleNamespace(id=4, page=5, text=source, difficulty_label="easy")
    questions = engine.generate(chunk, type_cycle=("true_false",), question_quota=2)
    assert [item.correct_answer for item in questions] == ["True"]
    assert len(questions) == 1


def test_quiz_assembly_balances_true_false_without_rejecting_true_candidates():
    true_questions = [
        _question(
            question=(
                f"True or false: Cats are mammals that often live with people {i}."
            ),
            type="true_false",
            options=["True", "False"],
            correct_answer="True",
        )
        for i in range(8)
    ]
    false_questions = [
        _question(
            question=(
                f"True or false: Cats are reptiles that often live with people {i}."
            ),
            type="true_false",
            options=["True", "False"],
            correct_answer="False",
        )
        for i in range(2)
    ]
    balanced = balance_true_false_questions(true_questions + false_questions)
    true_count = sum(item.correct_answer == "True" for item in balanced)
    assert 30 <= 100 * true_count / len(balanced) <= 70
    assert balance_true_false_questions(true_questions) == []


def test_classic_text_cleaning_and_sentence_filtering():
    raw = (
        "Slide 4\n• NLP is an area of computer science that studies human language.\n"
        "[Table 1]\nB. Speech Synthesis C. Sentiment Analysis\n"
        "→ Short note\n"
        "Machine translation systems convert text between two human languages."
    )
    cleaned = clean_chunk_text(raw)
    assert "•" not in cleaned and "→" not in cleaned and "[Table 1]" not in cleaned
    assert "B. Speech Synthesis" not in cleaned
    sentences = complete_source_sentences(cleaned)
    assert sentences == [
        "NLP is an area of computer science that studies human language.",
        "Machine translation systems convert text between two human languages.",
    ]


def test_classic_uses_one_complete_sentence_and_trusted_key_terms():
    calls = []
    source = (
        "Natural Language Processing studies how computers interpret human language. "
        "The field supports translation systems across several spoken languages."
    )
    engine = ClassicEngine(
        generator=lambda text, answer: (
            calls.append(text)
            or "What does Natural Language Processing study in computer science?"
        ),
        entity_extractor=lambda _: [],
        qa_model=lambda *_: "Natural Language Processing",
        embedder=lambda _: [],
    )
    chunk = SimpleNamespace(
        id=5,
        page=2,
        text=source,
        key_terms=["Natural Language Processing", "translation systems"],
    )
    questions = engine.generate(chunk, type_cycle=("short_answer",))
    assert not calls
    assert len(questions) == 1
    assert questions[0].question.startswith("Fill in the blank:")
    assert "Natural Language Processing" not in questions[0].question
    assert extract_candidates("Humans need a sentence.", key_terms=[]) == []
    assert extract_candidates(
        "Natural Language Processing", key_terms=["Natural Language Processing"]
    )


def test_stem_validation_rejects_options_artifacts_and_fragments():
    assert validate_stem("What does NLP study in human language processing?")[0]
    assert (
        validate_stem("What does NLP study? B. Speech Synthesis")[1]
        == "stem_contains_options"
    )
    assert (
        validate_stem("What does NLP study [Table 1] in this example?")[1]
        == "stem_contains_slide_artifacts"
    )
    assert (
        validate_stem(
            "Because computers understand language from a long contextual passage."
        )[1]
        == "low_readability"
    )
    assert not validate_stem("How do you need to retraining or fine-tun?")[0]
    assert not validate_stem(
        "Need contextual data and models; sarcasm and implicit meaning are "
        "more difficult."
    )[0]


def test_llm_batches_caches_and_obeys_request_budget():
    from app.services.quiz import generation

    generation._LLM_RESPONSE_CACHE.clear()
    payload = {
        "question": "Which organization developed the Python language?",
        "type": "multiple_choice",
        "options": ["Python Software Foundation", "Java", "C++", "Ruby"],
        "correct_answer": "Python Software Foundation",
        "evidence": "The Python Software Foundation developed the Python language.",
        "explanation": "The passage names its creator.",
        "difficulty": "medium",
    }

    class FakeProvider:
        def __init__(self):
            self.calls = 0

        def generate(self, prompt, system_prompt=None):
            self.calls += 1
            return json.dumps([payload])

    provider = FakeProvider()
    engine = LLMEngine(provider, min_delay_seconds=0, max_requests=1, parse_retries=1)
    chunk = SimpleNamespace(
        id=701,
        page=2,
        text="The Python Software Foundation developed the Python language.",
    )
    assert (
        len(engine.generate(chunk, question_quota=4, type_cycle=("multiple_choice",)))
        == 1
    )
    assert (
        len(engine.generate(chunk, question_quota=4, type_cycle=("multiple_choice",)))
        == 1
    )
    assert provider.calls == 1
    assert engine.request_count == 1


def test_llm_retries_rate_limit_using_retry_after_and_backoff_cap(monkeypatch):
    from app.services.quiz import generation

    payload = {
        "question": "Which organization developed the Python language?",
        "type": "multiple_choice",
        "options": ["Python Software Foundation", "Java", "C++", "Ruby"],
        "correct_answer": "Python Software Foundation",
        "evidence": "The Python Software Foundation developed the Python language.",
        "explanation": "The passage names its creator.",
        "difficulty": "medium",
    }

    class ThrottledProvider:
        def __init__(self):
            self.calls = 0

        def generate(self, prompt, system_prompt=None):
            self.calls += 1
            if self.calls == 1:
                raise RateLimitError("429", retry_after_seconds=3)
            return json.dumps([payload])

    sleeps = []
    monkeypatch.setattr(generation.time, "sleep", sleeps.append)
    provider = ThrottledProvider()
    engine = LLMEngine(
        provider,
        min_delay_seconds=0,
        backoff_cap_seconds=2,
        parse_retries=1,
    )
    chunk = SimpleNamespace(
        id=702,
        page=2,
        text="The Python Software Foundation developed the Python language.",
    )
    questions = engine.generate(
        chunk, question_quota=1, type_cycle=("multiple_choice",)
    )
    assert len(questions) == 1
    assert provider.calls == engine.request_count == 2
    assert sleeps == [3]


def test_llm_stops_retrying_when_the_provider_chain_is_rate_limited(monkeypatch):
    from app.services.quiz import generation

    class ThrottledChain:
        rate_limited = True

        def __init__(self):
            self.calls = 0

        def generate_json(self, prompt, **kwargs):
            self.calls += 1
            raise RateLimitError("chain rate limited")

    sleeps = []
    monkeypatch.setattr(generation.time, "sleep", sleeps.append)
    chain = ThrottledChain()
    engine = LLMEngine(chain, min_delay_seconds=0, parse_retries=1)
    chunk = SimpleNamespace(id=703, page=2, text="Grounded source text.")
    with pytest.raises(RateLimitError, match="chain rate limited"):
        engine.generate(chunk, question_quota=1, type_cycle=("fill_in_the_blank",))
    assert chain.calls == engine.request_count == 1
    assert sleeps == []
