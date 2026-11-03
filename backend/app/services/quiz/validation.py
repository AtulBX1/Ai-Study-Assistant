"""Grounding, similarity, and structural checks for generated questions."""

import re
from collections import Counter
from collections.abc import Callable, Iterable

from app.services.quiz.schemas import QuizQuestion

TOKEN = re.compile(r"[a-z0-9]+", re.I)
STEM_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "did",
    "do",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
}
GENERIC_ANSWERS = {
    "adapt",
    "cat",
    "easily",
    "humans",
    "machine",
    "may",
    "need",
    "require",
    "sentence",
    "step",
    "system",
    "thing",
    "understand",
    "use",
    "using",
    "text",
    "word",
    "words",
}
OPTION_PATTERN = re.compile(r"(?:^|\s)[A-D][.)]\s")
ARTIFACT_PATTERN = re.compile(
    r"(?:\[\s*table\s*\d*\s*\]|[•●▪◦➜→➔⇒]|\b(?:slide|page|examples?)\s*\d+\b)",
    re.I,
)
VERB_HINTS = {
    "add",
    "are",
    "be",
    "become",
    "can",
    "contain",
    "create",
    "develop",
    "does",
    "do",
    "encode",
    "extract",
    "find",
    "generate",
    "has",
    "have",
    "help",
    "is",
    "learn",
    "make",
    "maintain",
    "mean",
    "need",
    "occur",
    "provide",
    "preserve",
    "represent",
    "require",
    "use",
    "was",
    "were",
    "work",
}


def _is_verb_token(token: str) -> bool:
    """Recognize common inflected verbs in the no-model CI fallback."""
    word = token.casefold()
    forms = {word}
    if word.endswith("ies") and len(word) > 3:
        forms.add(word[:-3] + "y")
    if word.endswith("es") and len(word) > 2:
        forms.add(word[:-2])
    if word.endswith("s") and len(word) > 1:
        forms.add(word[:-1])
    return any(
        form in VERB_HINTS or form.endswith(("ed", "ing", "ize", "ise"))
        for form in forms
    )


def readability_score(stem: str) -> float:
    """Score whether the displayed question has a subject and a verb."""
    text = re.sub(
        r"^(?:true or false|fill in the blank):\s*", "", stem.strip(), flags=re.I
    )
    if TOKEN.findall(text.casefold())[:1] in (["because"], ["although"], ["while"]):
        return 0.0
    if re.search(r"\bto\s+[\w-]*(?:ing|ed)\b|[\w]+-$", text, re.I):
        return 0.0
    question_tokens = TOKEN.findall(text.casefold())
    if (
        len(question_tokens) > 3
        and question_tokens[0]
        in {
            "what",
            "which",
            "who",
            "how",
        }
        and question_tokens[1] in {"can", "could", "did", "do", "does", "will", "would"}
    ):
        main_verb = next(
            (
                index
                for index, token in enumerate(question_tokens[2:], start=2)
                if _is_verb_token(token)
            ),
            None,
        )
        if main_verb is not None and any(
            token not in STEM_STOPWORDS and token not in VERB_HINTS
            for token in question_tokens[2:main_verb]
        ):
            return 1.0
    clauses = [part.strip() for part in text.split(";") if part.strip()]
    if len(clauses) > 1:
        return min(readability_score(part) for part in clauses)
    try:
        from app.nlp.preprocessing import _spacy_model

        nlp = _spacy_model()
        if nlp is not None and nlp.has_pipe("parser"):
            doc = nlp(text)
            has_subject = any(
                token.dep_ in {"nsubj", "nsubjpass", "expl"} for token in doc
            )
            has_verb = any(token.pos_ in {"VERB", "AUX"} for token in doc)
            return (int(has_subject) + int(has_verb)) / 2
    except (ImportError, OSError):
        pass
    tokens = TOKEN.findall(text.casefold())
    if not tokens:
        return 0.0
    verb_index = next(
        (index for index, token in enumerate(tokens) if _is_verb_token(token)),
        None,
    )
    has_verb = verb_index is not None
    if not has_verb:
        return 0.0
    wh_words = {"what", "which", "who", "whom", "whose", "when", "where", "why", "how"}
    auxiliaries = {
        "am",
        "are",
        "can",
        "could",
        "did",
        "do",
        "does",
        "is",
        "may",
        "might",
        "was",
        "were",
        "will",
        "would",
    }
    if tokens[0] in wh_words and len(tokens) > 1 and tokens[1] in auxiliaries:
        if tokens[1] in {"do", "does", "did", "can", "could", "will", "would"}:
            main_verb_index = next(
                (
                    index
                    for index, token in enumerate(tokens[2:], start=2)
                    if _is_verb_token(token)
                ),
                len(tokens),
            )
            subject_region = tokens[2:main_verb_index]
            has_subject = any(
                token not in STEM_STOPWORDS and token not in VERB_HINTS
                for token in subject_region
            )
        else:
            has_subject = tokens[0] in {"what", "who", "which"}
    else:
        # For WH-questions (e.g., "Which foundation maintains...?"),
        # check if there's a subject among tokens before the verb.
        # Also check if the second token can be a subject.
        has_subject = any(
            token not in STEM_STOPWORDS and token not in VERB_HINTS
            for token in tokens[:verb_index]
        )
        if not has_subject and len(tokens) > 1 and tokens[0] in wh_words:
            # For WH-questions, the second token or later can be the subject
            for i in range(1, len(tokens)):
                if tokens[i] not in STEM_STOPWORDS and tokens[i] not in VERB_HINTS:
                    has_subject = True
                    break
    return (int(has_subject) + int(has_verb)) / 2


def validate_stem(stem: str) -> tuple[bool, str, float]:
    """Apply structural, artifact, and readability checks to a question stem."""
    value = stem.strip()
    if OPTION_PATTERN.search(value):
        return False, "stem_contains_options", 0.0
    if ARTIFACT_PATTERN.search(value):
        return False, "stem_contains_slide_artifacts", 0.0
    if value.count("?") > 1:
        return False, "stem_multiple_questions", 0.0
    if len(TOKEN.findall(value)) < 6:
        return False, "stem_too_short", 0.0
    terminal = value.rstrip("\"'”’)]")
    if terminal.endswith("?"):
        if not re.match(
            (
                r"^(what|which|who|whom|whose|when|where|why|how|is|are|can|"
                r"do|does|did|true or false)\b"
            ),
            value,
            re.I,
        ):
            return False, "stem_not_a_question", 0.0
    elif terminal.endswith((".", "!")):
        if sum(terminal.count(mark) for mark in ".!?") != 1:
            return False, "stem_not_single_sentence", 0.0
    else:
        return False, "stem_incomplete_sentence", 0.0
    score = readability_score(value)
    if score < 1.0:
        return False, "low_readability", score
    return True, "readable", score


def token_f1(left: str, right: str) -> float:
    """Multiset token F1, robust to casing and punctuation."""
    a, b = (
        Counter(TOKEN.findall(left.casefold())),
        Counter(TOKEN.findall(right.casefold())),
    )
    overlap = sum((a & b).values())
    if not overlap:
        return 0.0
    precision, recall = overlap / sum(a.values()), overlap / sum(b.values())
    return 2 * precision * recall / (precision + recall)


def embedding_similarity(left: str, right: str) -> float:
    """Use the local sentence encoder, falling back to token overlap if unavailable."""
    try:
        from app.services.embeddings import get_embedding_service

        first, second = get_embedding_service().embed_texts([left, right])
        return sum(a * b for a, b in zip(first, second, strict=True))
    except Exception:
        return token_f1(left, right)


def answer_in_source(answer: str, source: str) -> bool:
    """Check that the intended answer is grounded in its cited source chunk."""
    return " ".join(answer.casefold().split()) in " ".join(source.casefold().split())


def distractor_is_valid(
    candidate: str,
    answer: str,
    *,
    candidate_type: str | None = None,
    answer_type: str | None = None,
    similarity: float | None = None,
) -> bool:
    """Reject aliases, substring variants, cross-type terms, and near duplicates."""
    candidate, answer = candidate.strip().casefold(), answer.strip().casefold()
    if (
        not candidate
        or candidate == answer
        or candidate in answer
        or answer in candidate
    ):
        return False
    if candidate_type and answer_type and candidate_type != answer_type:
        return False
    return similarity is None or similarity < 0.88


def difficulty_for_chunk(
    text: str,
    answer: str,
    *,
    classifier_label: str | None = None,
    term_frequency: int = 1,
) -> str:
    """Blend the trained chunk label with answer length, rarity, and reasoning."""
    sentences = [item for item in re.split(r"(?<=[.!?])\s+", text) if item.strip()]
    reasoning = sum(
        bool(re.search(r"\b(because|therefore|however|thus|since)\b", item, re.I))
        for item in sentences
    )
    score = {"easy": 0, "medium": 1, "hard": 2}.get(classifier_label or "", 1)
    score += (
        int(len(answer.split()) >= 4) + int(term_frequency <= 1) + int(reasoning >= 2)
    )
    score = max(0, min(2, score))
    return ("easy", "medium", "hard")[score]


def validate_generated(
    question: QuizQuestion,
    source: str,
    *,
    qa_model: Callable[[str, str], str],
    round_trip_threshold: float = 0.65,
    prior_questions: Iterable[str] = (),
    similarity: Callable[[str, str], float] | None = None,
    key_terms: Iterable[str] = (),
    named_entities: Iterable[str] = (),
) -> tuple[bool, str]:
    """Reject unsupported, ambiguous, duplicate, or QA-inconsistent questions."""

    def normalize(value: str) -> str:
        return " ".join(value.split())

    evidence = normalize(question.evidence)
    if not evidence:
        return False, "evidence_missing"
    source_sentences = re.split(r"(?<=[.!?])\s+", normalize(source))
    if not any(evidence == sentence.strip() for sentence in source_sentences):
        return False, "evidence_not_in_source"
    if normalize(question.explanation) != evidence:
        return False, "explanation_not_evidence"
    stem_valid, stem_reason, _ = validate_stem(question.question)
    if (
        not stem_valid
        and stem_reason == "stem_too_short"
        and question.type.value == "short_answer"
        and re.fullmatch(r"What does .+ stand for\?", question.question.strip(), re.I)
        and len(TOKEN.findall(question.correct_answer)) >= 2
    ):
        stem_valid, stem_reason = True, "accepted"
    if not stem_valid:
        return False, stem_reason
    normalized_answer = question.correct_answer.strip().casefold()
    if any(
        phrase in question.question.casefold()
        for phrase in ("in the source sentence", "source sentence", "the text says")
    ):
        return False, "template_leakage"
    trusted_terms = {
        value.strip().casefold() for value in (*key_terms, *named_entities)
    }
    if (
        len(TOKEN.findall(normalized_answer)) == 1
        and normalized_answer in (GENERIC_ANSWERS | STEM_STOPWORDS)
        and normalized_answer not in trusted_terms
    ):
        try:
            from app.services.transformer_inference import extract_entities

            trusted_terms.update(
                str(item.get("text", "")).casefold()
                for item in extract_entities(source)
            )
        except (ImportError, FileNotFoundError, OSError, RuntimeError):
            pass
        if normalized_answer not in trusted_terms:
            return False, "generic_answer"
    is_boolean = question.type.value == "true_false"
    if not is_boolean and not answer_in_source(question.correct_answer, source):
        return False, "answer_not_in_source"
    if not is_boolean:
        source_sentences = re.split(r"(?<=[.!?])\s+", source)
        answer_sentences = [
            sentence
            for sentence in source_sentences
            if answer_in_source(question.correct_answer, sentence)
        ]
        stem_words = {
            word.casefold()
            for word in TOKEN.findall(question.question)
            if word.casefold() not in STEM_STOPWORDS
        }
        if not any(
            stem_words.intersection(word.casefold() for word in TOKEN.findall(sentence))
            for sentence in answer_sentences
        ):
            return False, "answer_context_mismatch"
    normalized = question.question.casefold().strip()
    for previous in prior_questions:
        score = (
            similarity(normalized, previous.casefold())
            if similarity
            else token_f1(normalized, previous)
        )
        if score >= 0.85:
            return False, "duplicate"
    if question.type.value == "fill_in_the_blank":
        if not answer_in_source(question.correct_answer, source):
            return False, "answer_not_in_source"
        return True, "accepted"
    if is_boolean:
        if not re.match(r"^True or false:\s+.+[.!?]$", question.question, re.I):
            return False, "unreadable_true_false"
        claim = question.question.split(":", 1)[1].strip()
        if question.engine == "llm":
            try:
                from app.nlp.preprocessing import _spacy_model

                doc = _spacy_model()(claim)
                if not any(
                    token.dep_ in {"nsubj", "nsubjpass", "csubj"} for token in doc
                ):
                    return False, "true_false_missing_subject"
                if not any(token.pos_ in {"VERB", "AUX"} for token in doc):
                    return False, "true_false_missing_verb"
            except (ImportError, OSError, RuntimeError):
                return False, "true_false_spacy_unavailable"
        elif readability_score(claim) < 1:
            return False, "unreadable_true_false"
        supported = any(
            token_f1(claim, sentence) >= 0.65
            for sentence in re.split(r"(?<=[.!?])\s+", source)
        )
        if question.correct_answer.casefold() == "false" and supported:
            return False, "false_statement_supported"
        if question.correct_answer.casefold() == "true" and not supported:
            return False, "true_statement_unsupported"
        return True, "accepted"
    predicted = qa_model(question.question, source)
    if token_f1(predicted, question.correct_answer) < round_trip_threshold:
        return False, "round_trip_failed"
    return True, "accepted"
