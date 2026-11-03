"""Classic and structured-JSON LLM question generation adapters."""

import inspect
import json
import re
import time
from collections import Counter
from collections.abc import Callable, Sequence
from typing import Any

from app.services.quiz.schemas import QuizQuestion
from app.services.quiz.validation import (
    GENERIC_ANSWERS,
    STEM_STOPWORDS,
    difficulty_for_chunk,
    distractor_is_valid,
    readability_score,
    token_f1,
    validate_stem,
)

WORD = re.compile(r"\b[A-Z][a-zA-Z-]{2,}(?:\s+[A-Z][a-zA-Z-]{2,}){0,2}\b")
BAD_CANDIDATE_STARTS = {
    "a",
    "an",
    "and",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "the",
    "to",
    "using",
    "with",
}
BAD_CANDIDATE_VERBS = {
    "develops",
    "developed",
    "maintains",
    "represents",
    "splits",
    "uses",
}
NOUN_PHRASE = re.compile(
    r"\b(?:[a-z][a-z-]*\s+){0,2}"
    r"(?:model|algorithm|language|system|method|frequency|token|network|"
    r"term|process|data|vector|document|embedding|query|classification)s?\b",
    re.I,
)
SENTENCE_START_FRAGMENTS = {"and", "because", "but", "or", "so", "which"}
SENTENCE_END_FRAGMENTS = {"and", "because", "but", "for", "of", "or", "to", "with"}
PRONOUN_OR_DEMONSTRATIVE_STARTS = {
    "this",
    "it",
    "they",
    "these",
    "that",
    "which",
}
VERB_OR_MODAL_STARTS = {
    "allows",
    "can",
    "could",
    "does",
    "do",
    "is",
    "may",
    "might",
    "must",
    "should",
    "was",
    "were",
    "will",
    "would",
}
TOKEN = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")
LLM_PROMPT_VERSION = "quiz-json-v3-evidence"
_LLM_RESPONSE_CACHE: dict[tuple[int, str, str], list[QuizQuestion]] = {}


class StructuredOutputError(ValueError):
    """Provider returned no valid Pydantic-validated JSON after one retry."""

    def __init__(self, message: str, *, parse_failures: int) -> None:
        super().__init__(message)
        self.parse_failures = parse_failures


class TruncatedOutputError(StructuredOutputError):
    """Provider exhausted its completion budget without complete JSON."""

    pass


def is_readable_statement(sentence: str) -> bool:
    """Conservative structural sanity check for a single complete statement."""
    stripped = sentence.strip()
    words = TOKEN.findall(stripped)
    if (
        len(words) < 5
        or "\n" in stripped
        or not stripped[0].isupper()
        or stripped[-1] not in ".!?"
        or "_____" in stripped
        or stripped.count(".") + stripped.count("!") + stripped.count("?") != 1
        or re.search(r"\b[A-Z]\.$", stripped) is not None
    ):
        return False
    return (
        words[0].casefold() not in SENTENCE_START_FRAGMENTS
        and words[-1].casefold() not in SENTENCE_END_FRAGMENTS
        and not re.search(r"\b(\w+)\s+\1\b", stripped, re.I)
    )


def build_false_statement(sentence: str, answer: str, replacement: str) -> str | None:
    """Swap an equal-length term/entity for a grammatical, readable false claim."""
    if not is_readable_statement(sentence):
        return None
    answer_words, replacement_words = TOKEN.findall(answer), TOKEN.findall(replacement)
    if not answer_words or len(answer_words) != len(replacement_words):
        return None
    match = re.search(re.escape(answer), sentence, re.I)
    if match is None or replacement.casefold() in sentence.casefold():
        return None
    changed = sentence[: match.start()] + replacement + sentence[match.end() :]
    # Preserve only the article attached to the replacement.
    article_pattern = re.compile(rf"\b(a|an)(\s+){re.escape(replacement)}\b", re.I)
    article_match = article_pattern.search(changed)
    if article_match:
        article = "an" if replacement[0].casefold() in "aeiou" else "a"
        if article_match.group(1)[0].isupper():
            article = article.capitalize()
        changed = (
            changed[: article_match.start()]
            + article
            + article_match.group(2)
            + replacement
            + changed[article_match.end() :]
        )
    if len(TOKEN.findall(changed)) != len(TOKEN.findall(sentence)):
        return None
    return changed if is_readable_statement(changed) else None


def extract_json_value(raw: str) -> Any:
    """Find and decode the first JSON object or array amid fences/preamble text."""
    text = re.sub(r"<think\b[^>]*>.*?</think\s*>", "", raw, flags=re.I | re.S)
    text = re.sub(r"```(?:json)?", "", text, flags=re.I).replace("```", "")
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and isinstance(value.get("questions"), list):
            return value["questions"]
        if isinstance(value, (dict, list)):
            return value
    raise ValueError("No JSON object or array was found in provider output.")


def normalize_question_item(item: Any) -> dict[str, Any]:
    """Map common provider aliases into the quiz Pydantic schema."""
    if not isinstance(item, dict):
        raise ValueError("Each quiz item must be a JSON object.")
    question = next(
        (item[key] for key in ("question", "stem", "prompt", "text") if key in item),
        None,
    )
    question = re.sub(
        r"^(?:short\s+answer|question)\s*:\s*", "", str(question or ""), flags=re.I
    )
    raw_type = (
        str(
            next(
                (
                    item[key]
                    for key in ("type", "question_type", "questionType", "kind")
                    if key in item
                ),
                "short_answer",
            )
        )
        .strip()
        .casefold()
        .replace("-", "_")
        .replace(" ", "_")
    )
    type_aliases = {
        "fill_blank": "fill_in_the_blank",
        "fill_in_blank": "fill_in_the_blank",
        "fillintheblank": "fill_in_the_blank",
        "truefalse": "true_false",
        "true/false": "true_false",
        "shortanswer": "short_answer",
        "multiplechoice": "multiple_choice",
    }
    question_type = type_aliases.get(raw_type, raw_type)
    evidence = str(item.get("evidence", item.get("source_sentence", ""))).strip()
    options = item.get("options", item.get("choices"))
    if isinstance(options, dict):
        options = [str(options[key]) for key in sorted(options)]
    letter_map = {key.upper(): str(item[key]) for key in "abcd" if key in item}
    letter_choices = [letter_map[key] for key in "ABCD" if key in letter_map]
    if options is None and letter_choices:
        options = letter_choices
    answer = next(
        (
            item[key]
            for key in (
                "correct_answer",
                "correctAnswer",
                "answer",
                "answer_key",
                "correct",
            )
            if key in item
        ),
        None,
    )
    if question_type == "true_false":
        options, answer = ["True", "False"], str(answer or "True").strip().capitalize()
    elif question_type == "multiple_choice" and options:
        answer_text = str(answer or "")
        letter = re.search(r"\b([A-D])\b", answer_text, re.I)
        if letter and letter_map:
            answer = letter_map.get(letter.group(1).upper(), answer)
        elif letter and isinstance(options, list):
            index = ord(letter.group(1).upper()) - ord("A")
            if index < len(options):
                answer = options[index]
        if isinstance(options, list):

            def clean_option(value: Any) -> str:
                result = re.sub(r"^[A-D][.)]\s*", "", str(value)).strip()
                parenthetical = re.search(r"\s*\([^()]*\)\s*$", result)
                if (
                    parenthetical
                    and parenthetical.group(0).strip(" ()").casefold()
                    not in evidence.casefold()
                ):
                    result = result[: parenthetical.start()].strip()
                return result

            options = [clean_option(value) for value in options]
            answer = re.sub(r"^[A-D][.)]\s*", "", str(answer or "")).strip()
            parenthetical = re.search(r"\s*\([^()]*\)\s*$", answer)
            if (
                parenthetical
                and parenthetical.group(0).strip(" ()").casefold()
                not in evidence.casefold()
            ):
                answer = answer[: parenthetical.start()].strip()
    return {
        "question": str(question or "").strip(),
        "type": question_type,
        "options": options
        if question_type in {"multiple_choice", "true_false"}
        else None,
        "correct_answer": str(answer or "").strip(),
        "evidence": evidence,
        "explanation": evidence,
        "difficulty": item.get("difficulty", "medium"),
    }


def _structured_provider_call(
    provider: Any,
    prompt: str,
    system_prompt: str,
    *,
    max_tokens: int | None = None,
) -> str:
    """Use a provider response schema API when one is exposed by Step 11."""
    schema = {
        "type": "array",
        "items": QuizQuestion.model_json_schema(),
    }
    for method_name in ("generate_structured", "generate_json"):
        method = getattr(provider, method_name, None)
        if method is None:
            continue
        parameters = inspect.signature(method).parameters
        accepts_kwargs = any(
            item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters.values()
        )
        kwargs: dict[str, Any] = {}
        if "system_prompt" in parameters:
            kwargs["system_prompt"] = system_prompt
        if "max_tokens" in parameters or accepts_kwargs:
            kwargs["max_tokens"] = max_tokens
        if "reasoning_effort" in parameters or accepts_kwargs:
            kwargs["reasoning_effort"] = "low"
        for key in ("response_schema", "schema", "json_schema"):
            if key in parameters:
                kwargs[key] = schema
                break
        else:
            if accepts_kwargs:
                kwargs["response_schema"] = schema
        if "response_format" in parameters:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "quiz_questions", "schema": schema},
            }
        return method(prompt, **kwargs)
    method = provider.generate
    parameters = inspect.signature(method).parameters
    accepts_kwargs = any(
        item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters.values()
    )
    for key in ("response_schema", "schema", "json_schema"):
        if key in parameters:
            return method(prompt, system_prompt, **{key: schema})
    if "response_format" in parameters:
        return method(
            prompt,
            system_prompt,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "quiz_questions", "schema": schema},
            },
        )
    if "json_mode" in parameters:
        return method(prompt, system_prompt, json_mode=True)
    if accepts_kwargs:
        return method(
            prompt,
            system_prompt,
            response_schema=schema,
            max_tokens=max_tokens,
            reasoning_effort="low",
        )
    return method(prompt, system_prompt)


def extract_candidates(
    text: str, entities: Sequence[dict[str, Any]] = (), key_terms: Sequence[str] = ()
) -> list[tuple[str, str]]:
    """Collect NER entities, key terms, and simple noun-phrase candidates."""
    key_values = {term.strip().casefold() for term in key_terms if term.strip()}
    candidates = [
        (str(entity.get("text", "")).strip(), str(entity.get("label", "TERM")))
        for entity in entities
    ]
    candidates.extend((term.strip(), "TERM") for term in key_terms)
    candidates.extend((match.group(), "TERM") for match in WORD.finditer(text))
    candidates.extend((match.group(), "TERM") for match in NOUN_PHRASE.finditer(text))
    try:
        from app.nlp.preprocessing import _spacy_model

        nlp = _spacy_model()
        if nlp is not None and nlp.has_pipe("parser"):
            candidates.extend(
                (phrase.text.strip(), "NOUN")
                for phrase in nlp(text).noun_chunks
                if 1 <= len(TOKEN.findall(phrase.text)) <= 4
            )
    except (ImportError, OSError, ValueError):
        pass
    seen: set[str] = set()
    result = []
    for value, kind in candidates:
        folded = value.casefold()
        words = TOKEN.findall(value)
        if not re.search(rf"(?<!\w){re.escape(value)}(?!\w)", text, re.I):
            continue
        is_trusted = folded in key_values or kind.casefold() not in {"term", "noun"}
        if (
            not value
            or not words
            or folded.split()[0] in BAD_CANDIDATE_STARTS
            or BAD_CANDIDATE_VERBS.intersection(folded.split())
            or (
                len(words) == 1
                and folded in (GENERIC_ANSWERS | STEM_STOPWORDS)
                and not is_trusted
            )
            or folded in seen
        ):
            continue
        seen.add(folded)
        result.append((value, kind))

    def candidate_priority(item: tuple[str, str]) -> tuple[int, int]:
        value, label = item
        length = len(TOKEN.findall(value))
        is_key_term = value.casefold() in key_values
        is_entity = label.casefold() not in {"term", "noun"}
        is_noun_phrase = label.casefold() == "noun"
        if is_key_term and length > 1:
            return (0, -length)
        if is_entity and length > 1:
            return (1, -length)
        if is_key_term and length == 1:
            return (2, -length)
        if is_entity:
            return (3, -length)
        if is_noun_phrase and length > 1:
            return (4, -length)
        return (5, -length)

    return sorted(result, key=candidate_priority)


def clean_chunk_text(text: str) -> str:
    """Remove common slide, bullet, and table artifacts before quiz generation."""
    cleaned_lines = []
    for raw_line in text.splitlines():
        if "|" in raw_line or re.search(r"\bConcept\s+Example\b", raw_line, re.I):
            continue
        if re.match(r"^\s*\d+[.)]\s+", raw_line) and '"' in raw_line:
            continue
        if re.search(r"\[\s*table\s*\d*\s*\]", raw_line, re.I):
            continue
        line = re.sub(r"\[\s*table\s*\d*\s*\]", " ", raw_line, flags=re.I)
        line = re.sub(r"[•●▪◦➜→➔⇒◆◇■□]+", " ", line)
        line = re.sub(r"^\s*(?:[-*]+|\d+[.)])\s*", "", line)
        line = re.sub(r"^\s*step\s*\d+\s*[:.)-]?\s*", "", line, flags=re.I)
        line = re.sub(
            r"\b(?:slide|page|lecture|chapter)\s*#?\s*\d+\b", " ", line, flags=re.I
        )
        line = line.replace(";", ". ")
        line = re.sub(r"\s+", " ", line).strip(" \t|;:")
        if (
            not line
            or re.fullmatch(r"\d+", line)
            or re.search(r"(?:^|\s)[A-D][.)]\s", line)
        ):
            continue
        words = TOKEN.findall(line)
        if len(words) < 6 and not re.search(r"[.!?]$", line):
            continue
        cleaned_lines.append(line)
    return " ".join(cleaned_lines)


def complete_source_sentences(text: str) -> list[str]:
    """Return complete, sentence-like source units suitable for one-question prompts."""
    result = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        sentence = re.sub(r"\s+", " ", sentence).strip()
        words = TOKEN.findall(sentence)
        if (
            len(words) < 8
            or len(words) > 35
            or not sentence[:1].isupper()
            or sentence[-1] not in ".!?"
            or not _contains_verb(sentence)
            or readability_score(sentence) < 1.0
            or sum(sentence.count(mark) for mark in ".!?_") > 1
            or words[0].casefold() in PRONOUN_OR_DEMONSTRATIVE_STARTS
            or words[0].casefold() in VERB_OR_MODAL_STARTS
            or not has_explicit_subject(sentence)
        ):
            continue
        result.append(sentence)
    return result


def has_explicit_subject(sentence: str) -> bool:
    try:
        from app.nlp.preprocessing import _spacy_model

        nlp = _spacy_model()
        if nlp is not None and nlp.has_pipe("parser"):
            return any(t.dep_ in {"nsubj", "nsubjpass"} for t in nlp(sentence))
    except (ImportError, OSError, ValueError):
        pass
    # Deterministic fallback for environments without a downloaded parser.
    return bool(re.match(r"^[A-Z][\w-]*(?:\s+[\w-]+){0,4}\s+", sentence))


def _contains_verb(text: str) -> bool:
    try:
        from app.nlp.preprocessing import _spacy_model

        nlp = _spacy_model()
        if nlp is not None and nlp.has_pipe("parser"):
            return any(token.pos_ in {"VERB", "AUX"} for token in nlp(text))
    except (ImportError, OSError):
        pass
    return bool(
        re.search(
            r"\b(?:am|are|be|been|being|can|could|did|does|do|had|has|have|is|may|might|must|shall|should|was|were|will|would|adds?|applies|called|contains?|converts?|creates?|describes?|develops?|enables?|explains?|generates?|includes?|involves?|learns?|means?|models?|occur|provides?|represents?|requires?|shows?|studies|supports?|uses?|works?|\w+(?:ed|ing|izes|ises))\b",
            text,
            re.I,
        )
    )


def _question_for_answer(sentence: str, answer: str) -> str | None:
    """Build a direct, sentence-grounded question for an object or complement."""
    try:
        from app.nlp.preprocessing import _spacy_model

        nlp = _spacy_model()
        if nlp is None or not nlp.has_pipe("parser"):
            return None
        match = re.search(re.escape(answer), sentence, flags=re.I)
        if match is None:
            return None
        doc = nlp(sentence)
        span = doc.char_span(match.start(), match.end(), alignment_mode="expand")
        if span is None:
            return None
        target = span.root
        if target.dep_ in {"amod", "compound"} and target.head.pos_ == "NOUN":
            target = target.head
        relation = target.dep_
        predicate = target.head.head if relation == "pobj" else target.head
        if predicate.pos_ not in {"VERB", "AUX"}:
            return None
        subjects = [
            token
            for token in predicate.children
            if token.dep_ in {"nsubj", "nsubjpass"}
        ]
        if not subjects:
            return None
        subject = subjects[0]
        subject_text = sentence[
            subject.left_edge.idx : subject.right_edge.idx + len(subject.right_edge)
        ]
        if relation in {"attr", "acomp", "oprd"}:
            question = f"What is {subject_text} described as?"
        else:
            modals = [
                token.text.lower()
                for token in predicate.children
                if token.dep_ in {"aux", "auxpass"}
                and token.lemma_.lower() not in {"do", "does", "did"}
            ]
            if modals:
                auxiliary = modals[0]
                base_verb = predicate.lemma_.lower()
            else:
                auxiliary = (
                    "did"
                    if predicate.tag_ == "VBD"
                    else ("does" if subject.tag_ in {"NN", "NNP"} else "do")
                )
                base_verb = predicate.lemma_.lower()
            preposition = f" {target.head.text}" if relation == "pobj" else ""
            question = f"What {auxiliary} {subject_text} {base_verb}{preposition}?"
        valid, _, _ = validate_stem(question)
        return question if valid else None
    except (ImportError, OSError, ValueError):
        return None


def select_distractors(
    answer: str,
    candidates: Sequence[tuple[str, str]],
    *,
    answer_type: str = "TERM",
    neighbours: Sequence[tuple[str, float, str]] = (),
    count: int = 3,
) -> list[str]:
    """Prefer same-type document terms and embedding neighbours; filter aliases."""
    ranked = [(value, kind, None) for value, kind in candidates]
    ranked.extend((value, kind, score) for value, score, kind in neighbours)
    result: list[str] = []
    for value, kind, score in ranked:
        if distractor_is_valid(
            value,
            answer,
            candidate_type=kind,
            answer_type=answer_type,
            similarity=score,
        ) and value.casefold() not in {item.casefold() for item in result}:
            result.append(value)
        if len(result) == count:
            break
    return result


def balance_true_false_questions(
    questions: Sequence[QuizQuestion],
) -> list[QuizQuestion]:
    """Keep available true/false items within the 30–70% true range."""
    true_items = [
        item
        for item in questions
        if item.type.value == "true_false" and item.correct_answer.casefold() == "true"
    ]
    false_items = [
        item
        for item in questions
        if item.type.value == "true_false" and item.correct_answer.casefold() == "false"
    ]
    if not false_items:
        return [item for item in questions if item.type.value != "true_false"]
    keep_true, keep_false = len(true_items), len(false_items)
    if keep_true > 7 * keep_false / 3:
        keep_true = (7 * keep_false) // 3
    elif keep_false > 7 * keep_true / 3 and keep_true:
        keep_false = (7 * keep_true) // 3
    selected = {id(item) for item in true_items[:keep_true] + false_items[:keep_false]}
    return [
        item
        for item in questions
        if item.type.value != "true_false" or id(item) in selected
    ]


class ClassicEngine:
    """Step 10 T5/NER based generation with conservative templates."""

    name = "classic"

    def __init__(
        self,
        generator: Callable[[str, str | None], str] | None = None,
        entity_extractor: Callable[[str], list[dict[str, Any]]] | None = None,
        qa_model: Callable[[str, str], str] | None = None,
        embedder: Callable[[Sequence[str]], Sequence[Sequence[float]]] | None = None,
    ) -> None:
        self.generator = generator or self._t5
        self.entity_extractor = entity_extractor or self._ner
        self.qa_model = qa_model or self._qa
        self.embedder = embedder
        self.last_rejections: Counter[str] = Counter()

    @staticmethod
    def _t5(text: str, answer: str | None) -> str:
        from app.services.transformer_inference import generate_question

        return generate_question(text, answer)

    @staticmethod
    def _ner(text: str) -> list[dict[str, Any]]:
        from app.services.transformer_inference import extract_entities

        return extract_entities(text)

    @staticmethod
    def _qa(question: str, text: str) -> str:
        from app.core.config import get_settings
        from app.services.transformer_inference import answer_chunk

        return str(
            answer_chunk(
                question, text, get_settings().transformer_no_answer_threshold
            )["answer"]
        )

    def generate(
        self,
        chunk: Any,
        *,
        topic: str = "General",
        difficulty: str | None = None,
        question_quota: int | None = None,
        type_cycle: Sequence[str] = (
            "fill_in_the_blank",
            "what_question",
            "true_false",
        ),
    ) -> list[QuizQuestion]:
        self.last_rejections.clear()
        text = clean_chunk_text(chunk.text)
        sentences = complete_source_sentences(text)
        entities = self.entity_extractor(text)
        key_terms = list(getattr(chunk, "key_terms", ()))
        candidates = extract_candidates(text, entities, key_terms)
        if not candidates:
            self.last_rejections["no_answer_candidates"] += 1
            return []
        counts = Counter(value.casefold() for value, _ in candidates)
        generated: list[QuizQuestion] = []
        used_sentences: set[str] = set()
        for offset, kind in enumerate(type_cycle):
            if len(generated) >= min(2, question_quota or 2):
                break
            if not candidates:
                break
            ordered_candidates = (
                candidates[offset % len(candidates) :]
                + candidates[: offset % len(candidates)]
            )
            selected = None
            for candidate, candidate_type in ordered_candidates:
                trusted = candidate_type.casefold() not in {"term", "noun"} or any(
                    candidate.casefold() == term.casefold() for term in key_terms
                )
                if (
                    len(TOKEN.findall(candidate)) == 1
                    and candidate.casefold() in (GENERIC_ANSWERS | STEM_STOPWORDS)
                    and not trusted
                ):
                    continue
                sentence_match = next(
                    (
                        item
                        for item in sentences
                        if re.search(
                            rf"(?<!\w){re.escape(candidate)}(?!\w)", item, re.I
                        )
                    ),
                    None,
                )
                if sentence_match and sentence_match.casefold() not in used_sentences:
                    selected = candidate, candidate_type, sentence_match
                    break
            if selected is None:
                continue
            answer, answer_type, sentence = selected
            used_sentences.add(sentence.casefold())
            if kind == "true_false":
                self._tf_count = getattr(self, "_tf_count", 0) + 1
                target, statement = "True", sentence
                replacement = next(
                    (
                        value
                        for value, label in candidates
                        if label == answer_type
                        and value.casefold() not in sentence.casefold()
                        and any(
                            value.casefold() in other.casefold()
                            for other in sentences
                            if other != sentence
                        )
                    ),
                    None,
                )
                false_statement = (
                    build_false_statement(sentence, answer, replacement)
                    if replacement
                    else None
                )
                if (
                    false_statement
                    and readability_score(false_statement) >= 1
                    and not any(
                        token_f1(false_statement, other) >= 0.92 for other in sentences
                    )
                ):
                    statement, target = false_statement, "False"
                elif replacement:
                    self.last_rejections["no_valid_false_statement"] += 1
                prompt = f"True or false: {statement}"
                options = ["True", "False"]
                generated.append(
                    QuizQuestion(
                        question=prompt,
                        type=kind,
                        options=options,
                        correct_answer=target,
                        evidence=sentence,
                        explanation=sentence,
                        source_chunk_id=chunk.id,
                        page=chunk.page,
                        difficulty=difficulty
                        or difficulty_for_chunk(
                            text,
                            answer,
                            classifier_label=getattr(chunk, "difficulty_label", None),
                            term_frequency=counts[answer.casefold()],
                        ),
                        engine=self.name,
                        topic=topic,
                    )
                )
                continue
            elif kind == "fill_in_the_blank":
                filled_sentence = re.sub(
                    rf"(?<!\w){re.escape(answer)}(?!\w)",
                    "_____",
                    sentence,
                    count=1,
                    flags=re.I,
                )
                if filled_sentence == sentence:
                    self.last_rejections["answer_not_in_sentence"] += 1
                    continue
                prompt = f"Fill in the blank: {filled_sentence}"
                target, options = answer, None
            else:
                if kind in {"short_answer", "what_question"}:
                    prompt = _question_for_answer(sentence, answer) or ""
                    if not prompt:
                        masked_sentence = re.sub(
                            rf"(?<!\w){re.escape(answer)}(?!\w)",
                            "_____",
                            sentence,
                            count=1,
                            flags=re.I,
                        )
                        prompt = f"Fill in the blank: {masked_sentence}"
                        kind = "fill_in_the_blank"
                else:
                    try:
                        prompt = self.generator(sentence, answer).strip()
                    except (FileNotFoundError, OSError):
                        self.last_rejections["generator_unavailable"] += 1
                        continue
                stem_ok, stem_reason, _ = validate_stem(prompt)
                if not stem_ok:
                    self.last_rejections[stem_reason] += 1
                    continue
                if not prompt or len(prompt.split()) < 6:
                    self.last_rejections["empty_or_short_stem"] += 1
                    continue
                target = answer
                options = None
                if kind == "multiple_choice":
                    distractors = select_distractors(
                        answer, candidates, answer_type=answer_type
                    )
                    embedder = self.embedder
                    if len(distractors) < 3 and embedder is None:
                        try:
                            from app.services.embeddings import get_embedding_service

                            embedder = get_embedding_service().embed_texts
                        except Exception:
                            embedder = None
                    if len(distractors) < 3 and embedder:
                        try:
                            vectors = embedder([answer, *(v for v, _ in candidates)])
                            neighbours = sorted(
                                (
                                    (
                                        v,
                                        sum(
                                            a * b
                                            for a, b in zip(
                                                vectors[0], vector, strict=True
                                            )
                                        ),
                                        t,
                                    )
                                    for (v, t), vector in zip(
                                        candidates, vectors[1:], strict=True
                                    )
                                ),
                                key=lambda item: item[1],
                                reverse=True,
                            )
                            distractors = select_distractors(
                                answer,
                                candidates,
                                answer_type=answer_type,
                                neighbours=neighbours,
                            )
                        except Exception:
                            pass
                    if len(distractors) < 3:
                        self.last_rejections["insufficient_distractors"] += 1
                        continue
                    options = [answer, *distractors[:3]]
            if kind == "what_question":
                kind = "short_answer"
            label = difficulty_for_chunk(
                text,
                target,
                classifier_label=getattr(chunk, "difficulty_label", None),
                term_frequency=counts[target.casefold()],
            )
            generated.append(
                QuizQuestion(
                    question=prompt,
                    type=kind,
                    options=options,
                    correct_answer=target,
                    evidence=sentence,
                    explanation=sentence,
                    source_chunk_id=chunk.id,
                    page=chunk.page,
                    difficulty=difficulty or label,
                    engine=self.name,
                    topic=topic,
                )
            )
        if not generated and sentences:
            self.last_rejections["no_complete_source_sentence"] += 1
        return generated


class LLMEngine:
    """Step 11 provider adapter requiring strict JSON output."""

    name = "llm"

    def __init__(
        self,
        provider: Any,
        *,
        min_delay_seconds: float | None = None,
        backoff_cap_seconds: float | None = None,
        max_requests: int | None = None,
        parse_retries: int = 2,
        input_token_limit: int | None = None,
        output_token_cap: int | None = None,
    ) -> None:
        from app.core.config import get_settings

        settings = get_settings()
        self.provider = provider
        self.input_token_limit = input_token_limit
        self.output_token_cap = output_token_cap or settings.groq_quiz_max_output_tokens
        self.last_parse_failures = 0
        self.min_delay_seconds = (
            settings.quiz_llm_min_delay_seconds
            if min_delay_seconds is None
            else min_delay_seconds
        )
        self.backoff_cap_seconds = (
            settings.quiz_llm_backoff_cap_seconds
            if backoff_cap_seconds is None
            else backoff_cap_seconds
        )
        self.max_requests = max_requests
        self.parse_retries = max(1, parse_retries)
        self.request_count = 0
        self.rate_limited = False
        self.max_requests_reached = False
        self.questions_returned = 0
        self.truncated_outputs = 0
        self._last_request_at: float | None = None
        self.requested_chunk_ids: set[int] = set()

    def generate(
        self,
        chunk: Any,
        *,
        topic: str = "General",
        difficulty: str | None = None,
        question_quota: int | None = None,
        type_cycle: Sequence[str] = (
            "multiple_choice",
            "true_false",
            "fill_in_the_blank",
            "short_answer",
        ),
    ) -> list[QuizQuestion]:
        quota = question_quota or 50
        chunk_id = int(chunk.id)
        type_names = tuple(
            kind.value if hasattr(kind, "value") else str(kind) for kind in type_cycle
        )
        cache_keys = [(chunk_id, kind, LLM_PROMPT_VERSION) for kind in type_names]
        if cache_keys and all(key in _LLM_RESPONSE_CACHE for key in cache_keys):
            cached = [
                question for key in cache_keys for question in _LLM_RESPONSE_CACHE[key]
            ]
            self.questions_returned += min(len(cached), quota)
            return cached[:quota]
        if chunk_id in self.requested_chunk_ids:
            return []
        self.requested_chunk_ids.add(chunk_id)
        source_text = str(chunk.text)
        system_prompt = (
            "Use ONLY the provided text, never outside knowledge. "
            "If it has no teachable facts, return []. Return JSON only."
        )
        prompt_prefix = (
            "Return a JSON array with no prose. Each item must satisfy this schema: "
            + json.dumps(QuizQuestion.model_json_schema())
            + ". Ignore unknown fields in your internal reasoning. Use keys "
            "question, type, options, correct_answer, evidence, explanation, "
            "and difficulty. "
            "Every evidence value must be one exact complete sentence copied "
            "from the provided text. Use it verbatim as explanation. "
            + f"Create exactly {quota} questions, with types "
            + f"{', '.join(type_cycle)}. Difficulty {difficulty or 'mixed'}. "
            + "Do not prefix stems with labels. Prefer specific document terms "
            "over generic one-word answers. True/false options must be exactly "
            "[True, False]. "
            + "Worked example: input: ‘A tokenizer splits text into words.’ "
            'output: [{"question":"Fill in the blank: A tokenizer splits '
            'text into _____.","type":"fill_in_the_blank","options":null,'
            '"correct_answer":"words","evidence":"A tokenizer splits text into words.",'
            '"explanation":"A tokenizer splits text into words.",'
            '"difficulty":"easy"}]. ' + f"Source chunk {chunk.id}, page {chunk.page}:\n"
        )
        if self.input_token_limit:
            fixed_tokens = self._estimate_tokens(prompt_prefix + system_prompt)
            source_budget = max(0, self.input_token_limit - fixed_tokens - 20)
            source_text = source_text[: source_budget * 4]
        prompt = prompt_prefix + source_text
        self.last_parse_failures = 0
        validation_errors: list[str] = []
        max_tokens = self.output_token_cap
        for attempt in range(self.parse_retries):
            attempt_prompt = prompt
            if attempt:
                attempt_prompt += (
                    "\nSTRICT RETRY: the prior response was invalid. Output exactly "
                    "one JSON array, with no markdown, fences, comments, or prose. "
                    "Every item must validate against the supplied schema."
                )
            raw = self._call_with_throttle(
                attempt_prompt, system_prompt, max_tokens=max_tokens
            )
            diagnostics = self._provider_diagnostics()
            if diagnostics.get("finish_reason") == "length" or not str(raw).strip():
                self.truncated_outputs += 1
                if attempt + 1 < self.parse_retries:
                    max_tokens = max(max_tokens + 200, 2000)
                    continue
                raise TruncatedOutputError(
                    "Provider output was truncated (finish_reason=length "
                    "or empty content).",
                    parse_failures=0,
                )
            try:
                data = extract_json_value(str(raw))
                if isinstance(data, dict):
                    data = [data]
                if not isinstance(data, list):
                    raise ValueError("Top-level JSON must be an object or array.")
                questions = [
                    QuizQuestion.model_validate(
                        {
                            **normalize_question_item(item),
                            "source_chunk_id": chunk.id,
                            "page": chunk.page,
                            "engine": "llm",
                            "topic": topic,
                            "difficulty": difficulty
                            or item.get("difficulty", "medium"),
                        }
                    )
                    for item in data
                ]
                for question in questions:
                    question.explanation = question.evidence
                questions = questions[:quota]
                provider_name = getattr(self.provider, "last_provider", "")
                if provider_name:
                    for question in questions:
                        question.provider = provider_name
                grouped = {
                    kind: [
                        question
                        for question in questions
                        if question.type.value == kind
                    ]
                    for kind in type_names
                }
                for key in cache_keys:
                    _LLM_RESPONSE_CACHE[key] = grouped[key[1]]
                self.questions_returned += len(questions)
                return questions
            except (ValueError, TypeError, KeyError) as error:
                self.last_parse_failures += 1
                validation_errors.append(str(error))
        raise StructuredOutputError(
            "Provider output failed JSON/Pydantic validation twice: "
            + "; ".join(validation_errors),
            parse_failures=self.last_parse_failures,
        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, (len(text) + 3) // 4)

    def _provider_diagnostics(self) -> dict[str, Any]:
        diagnostics = getattr(self.provider, "last_diagnostics", None)
        if diagnostics:
            return diagnostics
        provider_name = getattr(self.provider, "last_provider", None)
        providers = getattr(self.provider, "providers", ())
        return next(
            (
                getattr(provider, "last_diagnostics", {})
                for provider in providers
                if getattr(provider, "name", None) == provider_name
            ),
            {},
        )

    def _call_with_throttle(
        self, prompt: str, system_prompt: str, *, max_tokens: int
    ) -> str:
        from app.services.rag.providers import ProviderUnavailableError, RateLimitError

        backoff = min(1.0, self.backoff_cap_seconds)
        retries = 0
        while True:
            if (
                self.max_requests is not None
                and self.request_count >= self.max_requests
            ):
                self.max_requests_reached = True
                raise ProviderUnavailableError("Quiz LLM request budget exhausted.")
            if self._last_request_at is not None:
                delay = self.min_delay_seconds - (
                    time.monotonic() - self._last_request_at
                )
                if delay > 0:
                    time.sleep(delay)
            self.request_count += 1
            self._last_request_at = time.monotonic()
            try:
                return _structured_provider_call(
                    self.provider,
                    prompt,
                    system_prompt,
                    max_tokens=max_tokens,
                )
            except RateLimitError as error:
                if getattr(self.provider, "rate_limited", False):
                    self.rate_limited = True
                    raise
                retries += 1
                if retries > 2:
                    self.rate_limited = True
                    raise
                retry_after = getattr(error, "retry_after_seconds", None) or 0
                time.sleep(max(retry_after, min(backoff, self.backoff_cap_seconds)))
                backoff = min(max(backoff * 2, 1.0), self.backoff_cap_seconds)
