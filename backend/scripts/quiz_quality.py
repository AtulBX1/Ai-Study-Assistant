"""Evaluate classic and LLM quiz generation against an ingested local PDF.

Run with: uv run --directory backend python scripts/quiz_quality.py --document-id ID
Private documents are never sent to an LLM provider.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import Chunk, Document, DocumentKeyTerm
from app.services.quiz.generation import (
    ClassicEngine,
    LLMEngine,
    StructuredOutputError,
    TruncatedOutputError,
    _contains_verb,
    clean_chunk_text,
    complete_source_sentences,
    extract_candidates,
)
from app.services.quiz.validation import (
    readability_score,
    token_f1,
    validate_generated,
)
from app.services.rag.providers import (
    GeminiProvider,
    GroqProvider,
    ProviderChain,
    ProviderError,
    ProviderUnavailableError,
    RateLimitError,
)

QUESTIONS_PER_CHUNK = 3
CLASSIC_QUESTION_QUOTA = 2
SAMPLED_CHUNKS = 199
QUESTION_TYPES = (
    "fill_in_the_blank",
    "what_question",
    "true_false",
)


def sample_chunks(chunks: list[Chunk], limit: int = SAMPLED_CHUNKS) -> list[Chunk]:
    """Rank content chunks, then sample evenly across pages and sections."""

    def quality(chunk: Chunk) -> tuple[int, int]:
        cleaned = clean_chunk_text(chunk.text or "")
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", cleaned)
            if len(sentence.split()) >= 6
            and sentence.rstrip().endswith((".", "!", "?"))
            and _contains_verb(sentence)
        ]
        words = sum(len(sentence.split()) for sentence in sentences)
        lines = [
            line.strip() for line in (chunk.text or "").splitlines() if line.strip()
        ]
        bullet_lines = sum(bool(re.match(r"^[•*-]", line)) for line in lines)
        if words < 40 or not sentences or (lines and bullet_lines / len(lines) > 0.6):
            return (0, 0)
        ranked_sentences = complete_source_sentences(cleaned)
        return (words + len(ranked_sentences) * 8, len(sentences))

    chunks = [chunk for chunk in chunks if quality(chunk)[0] > 0]
    ordered = sorted(
        chunks,
        key=lambda item: (
            item.page_start or item.page,
            item.page_end or item.page,
            item.section or "",
            -quality(item)[0],
            item.chunk_index,
        ),
    )
    target = min(limit, len(ordered))
    by_section: dict[str, list[Chunk]] = defaultdict(list)
    for chunk in ordered:
        by_section[chunk.section or "Unsectioned"].append(chunk)
    section_names = sorted(by_section)
    if len(section_names) > target:
        selected_names = [
            section_names[int((index + 0.5) * len(section_names) / target)]
            for index in range(target)
        ]
        allocations = {name: 1 for name in selected_names}
    else:
        allocations = {name: 1 for name in section_names}
        remaining = target - len(section_names)
        capacities = {name: len(by_section[name]) - 1 for name in section_names}
        total_capacity = sum(capacities.values())
        if remaining and total_capacity:
            shares = {
                name: remaining * capacities[name] / total_capacity
                for name in section_names
            }
            for name, share in shares.items():
                allocations[name] += min(capacities[name], int(share))
            left = target - sum(allocations.values())
            for name in sorted(
                section_names,
                key=lambda item: (shares[item] % 1, capacities[item]),
                reverse=True,
            ):
                if left <= 0:
                    break
                if allocations[name] < len(by_section[name]):
                    allocations[name] += 1
                    left -= 1
    selected: list[Chunk] = []
    for name, count in allocations.items():
        bucket = by_section[name]
        indices = {
            min(
                len(bucket) - 1,
                (
                    round(index * (len(bucket) - 1) / (count - 1))
                    if count > 1
                    else len(bucket) // 2
                ),
            )
            for index in range(count)
        }
        selected.extend(bucket[index] for index in sorted(indices))
    # If section allocation collapsed identical section names, enforce unique IDs.
    unique = {chunk.id: chunk for chunk in selected}
    return sorted(
        unique.values(),
        key=lambda item: (
            item.page_start or item.page,
            item.section or "",
            item.chunk_index,
        ),
    )


def require_minimum_chunks(document_id: int, chunk_count: int) -> None:
    """Refuse quality runs that cannot represent a document meaningfully."""
    if chunk_count < 20:
        raise ValueError(
            f"Refusing quality run: document {document_id} has {chunk_count} "
            "chunks; at least 20 are required."
        )


def diagnose_one_request(document_id: int) -> str:
    """Make one direct Groq request and print sanitized parse diagnostics."""
    from app.services.rag.safety import redact_secrets

    db = SessionLocal()
    provider: GroqProvider | None = None
    try:
        document = db.scalar(select(Document).where(Document.id == document_id))
        if document is None or document.is_private:
            raise ValueError("Diagnostic requires a ready, non-private document.")
        chunks = list(
            db.scalars(
                select(Chunk)
                .where(Chunk.doc_id == document_id)
                .order_by(Chunk.page_start, Chunk.chunk_index)
            )
        )
        terms_by_page: dict[int, list[str]] = defaultdict(list)
        for term in db.scalars(
            select(DocumentKeyTerm).where(DocumentKeyTerm.document_id == document_id)
        ):
            terms_by_page[term.page].append(term.term)
        eligible = []
        for chunk in chunks:
            chunk.key_terms = [
                term
                for page in range(
                    chunk.page_start or chunk.page,
                    (chunk.page_end or chunk.page) + 1,
                )
                for term in terms_by_page[page]
            ]
            text = clean_chunk_text(chunk.text)
            sentences = complete_source_sentences(text)
            if sentences and extract_candidates(text, key_terms=chunk.key_terms):
                eligible.append(chunk)
        if not eligible:
            raise ValueError("No eligible quiz chunk found for diagnostics.")
        chunk = next(
            (item for item in eligible if (item.page_start or item.page) == 92),
            eligible[0],
        )
        settings = get_settings()
        if not settings.allow_external_llm:
            raise ValueError("External LLM use is disabled.")
        provider = GroqProvider(
            model_name=settings.groq_quiz_model or settings.groq_model
        )
        engine = LLMEngine(
            provider,
            min_delay_seconds=20,
            max_requests=1,
            parse_retries=1,
            input_token_limit=settings.groq_quiz_input_token_limit,
            output_token_cap=settings.groq_quiz_max_output_tokens,
        )
        failure = None
        try:
            engine.generate(
                chunk,
                topic=chunk.section or "General",
                question_quota=3,
                type_cycle=QUESTION_TYPES,
            )
        except (StructuredOutputError, ProviderError, ProviderUnavailableError) as exc:
            failure = f"{type(exc).__name__}: {exc}"
        diagnostics = dict(provider.last_diagnostics)
        raw = redact_secrets(str(diagnostics.pop("raw_output", "")), [provider.api_key])
        diagnostics["provider"] = "groq"
        diagnostics["raw_output_first_400"] = raw[:400]
        diagnostics["request_count"] = engine.request_count
        diagnostics["provider_request_count"] = provider.request_count
        diagnostics["questions_returned"] = engine.questions_returned
        if failure:
            diagnostics["failure"] = redact_secrets(failure, [provider.api_key])
            _log_parse_failure(
                provider="groq",
                model=str(diagnostics.get("model") or "unknown"),
                raw=raw,
                finish_reason=diagnostics.get("finish_reason"),
                input_tokens=diagnostics.get("input_tokens"),
                completion_tokens=diagnostics.get("completion_tokens"),
                reasoning_tokens=diagnostics.get("reasoning_tokens"),
            )
        result = json.dumps(diagnostics, ensure_ascii=False)
        print(result)
        return result
    finally:
        db.close()


def _log_parse_failure(
    *,
    provider: str,
    model: str,
    raw: str,
    finish_reason: Any,
    input_tokens: Any,
    completion_tokens: Any,
    reasoning_tokens: Any,
    failure_type: str = "parse_failure",
    secrets: list[str | None] | None = None,
) -> None:
    """Append only the first five sanitized failed outputs for diagnosis."""
    from app.services.rag.safety import redact_secrets

    path = (
        Path(__file__).resolve().parents[2] / "docs" / "results" / "llm_parse_debug.md"
    )
    current = path.read_text(encoding="utf-8") if path.exists() else ""
    count = current.count("### Failure ")
    if count >= 5:
        return
    entry = (
        f"### Failure {count + 1} ({failure_type})\n\n"
        f"- Provider: {provider}\n- Model: {model}\n"
        f"- Finish reason: {finish_reason}\n- Input tokens: {input_tokens}\n"
        f"- Completion tokens: {completion_tokens}\n"
        f"- Reasoning tokens: {reasoning_tokens}\n\n"
        f"```text\n{redact_secrets(raw, secrets or [])[:300]}\n```\n\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(current + entry, encoding="utf-8")


def _resolve_llm(
    document: Document, max_requests: int = 12
) -> tuple[LLMEngine | None, str | None]:
    """Resolve the configured provider without routing private text externally."""
    if document.is_private:
        return None, "private_document"
    settings = get_settings()
    if not settings.allow_external_llm:
        return None, "external_provider_disabled"
    try:
        chain = ProviderChain(
            [
                GroqProvider(
                    model_name=settings.groq_quiz_model or settings.groq_model
                ),
                GeminiProvider(max_retries=1),
            ],
            context_budget=settings.groq_quiz_input_token_limit,
            failure_delay_seconds=20,
            max_requests=max_requests,
            fallback_only_on_cooldown=True,
        )
        return (
            LLMEngine(
                chain,
                min_delay_seconds=20,
                max_requests=max_requests,
                parse_retries=2,
                input_token_limit=settings.groq_quiz_input_token_limit,
                output_token_cap=settings.groq_quiz_max_output_tokens,
            ),
            None,
        )
    except (ProviderUnavailableError, ValueError):
        return None, "provider_unavailable"


def _is_duplicate(question: str, previous: list[str]) -> bool:
    return any(token_f1(question, item) >= 0.85 for item in previous)


def _log_llm_failure(engine: LLMEngine, failure_type: str) -> None:
    diagnostics = engine._provider_diagnostics()
    _log_parse_failure(
        provider=getattr(engine.provider, "last_provider", "groq"),
        model=str(diagnostics.get("model") or "unknown"),
        raw=str(diagnostics.get("raw_output", "")),
        finish_reason=diagnostics.get("finish_reason"),
        input_tokens=diagnostics.get("input_tokens"),
        completion_tokens=diagnostics.get("completion_tokens"),
        reasoning_tokens=diagnostics.get("reasoning_tokens"),
        failure_type=failure_type,
        secrets=[
            getattr(provider, "api_key", None)
            for provider in getattr(engine.provider, "providers", [])
        ],
    )


def _evaluate_engine(
    engine_name: str,
    engine: Any,
    chunks: list[Chunk],
    classic: ClassicEngine,
) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    seen: list[str] = []
    generated = validation_attempts = duplicate_count = parse_failures = 0
    provider_errors = 0
    provider_answers: Counter[str] = Counter()
    returned_type_counts: Counter[str] = Counter()
    rate_limited = False
    settings = get_settings()

    for chunk_index, chunk in enumerate(chunks):
        rotated_types = (
            QUESTION_TYPES[chunk_index % len(QUESTION_TYPES) :]
            + QUESTION_TYPES[: chunk_index % len(QUESTION_TYPES)]
        )
        try:
            question_quota = (
                CLASSIC_QUESTION_QUOTA
                if engine_name == "classic"
                else QUESTIONS_PER_CHUNK
            )
            batch = engine.generate(
                chunk,
                topic=chunk.section or "General",
                type_cycle=rotated_types,
                question_quota=question_quota,
            )
            if engine_name == "classic":
                reasons.update(classic.last_rejections)
            if engine_name == "llm":
                returned_type_counts.update(question.type.value for question in batch)
                provider_answers.update(
                    question.provider
                    or getattr(engine.provider, "last_provider", "unknown")
                    for question in batch
                )
        except TruncatedOutputError:
            reasons["truncated"] += 1
            _log_llm_failure(engine, "truncated")
            if getattr(engine.provider, "rate_limited", False):
                rate_limited = True
                break
            continue
        except StructuredOutputError as error:
            parse_failures += error.parse_failures
            reasons["llm_parse_failure"] += error.parse_failures
            _log_llm_failure(engine, "parse_failure")
            if getattr(engine.provider, "rate_limited", False):
                rate_limited = True
                break
            continue
        except RateLimitError:
            provider_errors += 1
            rate_limited = True
            prior_parse_failures = getattr(engine, "last_parse_failures", 0)
            parse_failures += prior_parse_failures
            reasons["llm_parse_failure"] += prior_parse_failures
            reasons["rate_limited"] += 1
            break
        except (ProviderError, ProviderUnavailableError):
            provider_errors += 1
            prior_parse_failures = getattr(engine, "last_parse_failures", 0)
            parse_failures += prior_parse_failures
            reasons["llm_parse_failure"] += prior_parse_failures
            reasons["provider_error"] += 1
            chain_exhausted = (
                getattr(getattr(engine, "provider", None), "max_requests", None)
                is not None
                and getattr(engine.provider, "request_count", 0)
                >= engine.provider.max_requests
            )
            if getattr(engine, "max_requests_reached", False) or chain_exhausted:
                reasons["max_requests_reached"] += 1
                break
            continue
        except (ValueError, OSError) as error:
            provider_errors += 1
            prior_parse_failures = getattr(engine, "last_parse_failures", 0)
            parse_failures += prior_parse_failures
            reasons["llm_parse_failure"] += prior_parse_failures
            reasons[f"generation_error:{type(error).__name__}"] += 1
            continue

        for question in batch:
            if _is_duplicate(question.question, seen):
                duplicate_count += 1
                rejected.append(
                    {
                        "question": question.question,
                        "answer": question.correct_answer,
                        "page": question.page,
                        "chunk": question.source_chunk_id,
                        "reason": "duplicate",
                    }
                )
                continue
            seen.append(question.question)
            generated += 1
            validation_attempts += 1
            source_text = (
                clean_chunk_text(chunk.text) if engine_name == "classic" else chunk.text
            )
            try:
                ok, reason = validate_generated(
                    question,
                    source_text,
                    qa_model=classic.qa_model,
                    round_trip_threshold=settings.quiz_round_trip_f1_threshold,
                    similarity=token_f1,
                    key_terms=getattr(chunk, "key_terms", ()),
                )
            except (FileNotFoundError, OSError):
                ok, reason = False, "qa_weights_unavailable"
            reasons[reason] += 1
            example = {
                "question": question.question,
                "answer": question.correct_answer,
                "page": question.page,
                "chunk": question.source_chunk_id,
                "reason": reason,
                "readability": readability_score(question.question),
                "type": question.type.value,
                "provider": question.provider,
                "evidence": question.evidence,
            }
            (accepted if ok else rejected).append(example)
        if engine_name == "llm" and getattr(engine.provider, "rate_limited", False):
            rate_limited = True
            break

    if engine_name == "classic":
        true_items = [
            item
            for item in accepted
            if item.get("type") == "true_false" and item["answer"].casefold() == "true"
        ]
        false_items = [
            item
            for item in accepted
            if item.get("type") == "true_false" and item["answer"].casefold() == "false"
        ]
        keep_true, keep_false = len(true_items), len(false_items)
        if not keep_false:
            keep_true = 0
        elif keep_true > 7 * keep_false / 3:
            keep_true = (7 * keep_false) // 3
        elif keep_false > 7 * keep_true / 3 and keep_true:
            keep_false = (7 * keep_true) // 3
        kept_ids = {
            id(item) for item in true_items[:keep_true] + false_items[:keep_false]
        }
        removed = [
            item
            for item in accepted
            if item.get("type") == "true_false" and id(item) not in kept_ids
        ]
        if removed:
            accepted = [item for item in accepted if item not in removed]
            reasons["quiz_true_false_balance"] += len(removed)
            reasons["accepted"] -= len(removed)
            rejected.extend(
                {**item, "reason": "quiz_true_false_balance"} for item in removed
            )
    return {
        "engine": engine_name,
        "sampled_chunks": len(chunks),
        "generated": generated,
        "attempts": validation_attempts,
        "duplicates": duplicate_count,
        "accepted": accepted,
        "rejected": rejected,
        "reasons": dict(reasons),
        "round_trip_failures": reasons["round_trip_failed"],
        "parse_failures": parse_failures,
        "provider_errors": provider_errors,
        "provider_answers": dict(provider_answers),
        "provider_responses": dict(
            getattr(getattr(engine, "provider", None), "response_counts", {})
        ),
        "returned_type_counts": dict(returned_type_counts),
        "provider_error_details": list(
            getattr(getattr(engine, "provider", None), "history", [])
        ),
        "provider_skipped": list(
            getattr(getattr(engine, "provider", None), "skipped", [])
        ),
        "pass_rate": (
            len(accepted) / generated
            if generated and not (engine_name == "llm" and generated < 20)
            else None
        ),
        "questions_returned": getattr(engine, "questions_returned", generated),
        "requests_used": getattr(
            getattr(engine, "provider", None),
            "request_count",
            getattr(engine, "request_count", 0),
        ),
        "rate_limited": rate_limited,
    }


def _engine_report(result: dict[str, Any]) -> list[str]:
    accepted_chunks = {item["chunk"] for item in result["accepted"]}
    accepted_pages = {item["page"] for item in result["accepted"]}
    type_counts = Counter(item["type"] for item in result["accepted"])
    boolean_counts = Counter(
        item["answer"] for item in result["accepted"] if item["type"] == "true_false"
    )
    boolean_total = sum(boolean_counts.values())
    true_share = (
        f"{100 * boolean_counts['true'] / boolean_total:.1f}% True"
        if boolean_total
        else "N/A (no true/false questions)"
    )
    provider_summary = json.dumps(result.get("provider_answers", {}), sort_keys=True)
    provider_response_summary = json.dumps(
        result.get("provider_responses", {}), sort_keys=True
    )
    rate = (
        "not measurable (<20 questions returned)"
        if result["engine"] == "llm" and result["questions_returned"] < 20
        else "N/A (no question candidates)"
    )
    if result["pass_rate"] is not None:
        rate = f"{result['pass_rate']:.1%}"
    lines = [
        f"## {result['engine']}",
        "",
        f"- Chunks sampled: {result['sampled_chunks']}",
        f"- Candidate outputs: {result['generated']}",
        f"- Validation attempts (duplicates excluded): {result['attempts']}",
        f"- Duplicate outputs: {result['duplicates']}",
        f"- Accepted: {len(result['accepted'])}; rejected: {len(result['rejected'])}",
        f"- Pass rate: {rate}",
        f"- Requests used: {result['requests_used']}",
        f"- Rate limited: {'yes' if result['rate_limited'] else 'no'}",
        f"- Questions returned: {result['questions_returned']}",
        f"- Provider answers: `{provider_summary}`",
        f"- Provider responses: `{provider_response_summary}`",
        f"- Question type mix (returned): `"
        f"{json.dumps(result.get('returned_type_counts', {}), sort_keys=True)}`",
        *[
            f"- Provider failure: {item.get('provider')} "
            f"{item.get('error_type')}: {item.get('message')}"
            for item in result.get("provider_error_details", [])
        ],
        *[
            f"- Provider skipped: {item.get('provider')} ({item.get('reason')})"
            for item in result.get("provider_skipped", [])
        ],
        f"- Round-trip failures: {result['round_trip_failures']}",
        f"- LLM parse failures: {result['parse_failures']}",
        f"- Rejection/error counts: `{json.dumps(result['reasons'], sort_keys=True)}`",
        f"- Accepted chunks/pages: {len(accepted_chunks)} chunks; "
        f"{len(accepted_pages)} pages",
        f"- Accepted by type: `{json.dumps(dict(type_counts), sort_keys=True)}`",
        f"- Accepted true/false counts: True {boolean_counts['true']}, "
        f"False {boolean_counts['false']}",
        f"- Final true/false balance: {true_share}",
        "",
        "### Accepted examples",
    ]
    lines.extend(
        [
            f"- p.{item['page']} (chunk {item['chunk']}): "
            f"{item['question']} -> {item['answer']} "
            f"(readability {item.get('readability', 0.0):.2f})"
            for item in result["accepted"]
        ]
        or ["- No accepted questions in this run."]
    )
    lines.extend(["", "### Rejected examples"])
    lines.extend(
        [
            f"- p.{item['page']} (chunk {item['chunk']}, {item['reason']}): "
            f"{item['question']} -> {item['answer']} "
            f"(readability {item.get('readability', 0.0):.2f})"
            for item in result["rejected"][:10]
        ]
        or ["- No question candidates were rejected in this run."]
    )
    return lines + [""]


def run(document_id: int, *, max_requests: int = 12) -> str:
    """Generate the two-engine quality report for a sufficiently large PDF."""
    db = SessionLocal()
    try:
        document = db.scalar(select(Document).where(Document.id == document_id))
        if document is None:
            raise ValueError(f"Document {document_id} was not found.")
        if document.status != "ready":
            raise ValueError(
                f"Document {document_id} is {document.status}, not ingested and ready."
            )
        chunks = list(
            db.scalars(
                select(Chunk)
                .where(Chunk.doc_id == document_id)
                .order_by(Chunk.page_start, Chunk.chunk_index)
            )
        )
        require_minimum_chunks(document_id, len(chunks))
        terms_by_page: dict[int, list[str]] = defaultdict(list)
        for term in db.scalars(
            select(DocumentKeyTerm).where(DocumentKeyTerm.document_id == document_id)
        ):
            terms_by_page[term.page].append(term.term)
        sampled = sample_chunks(chunks)
        for chunk in sampled:
            chunk.key_terms = [
                term
                for page in range(
                    chunk.page_start or chunk.page, (chunk.page_end or chunk.page) + 1
                )
                for term in terms_by_page[page]
            ]

        classic = ClassicEngine(
            embedder=lambda values: [
                [float(index == other) for other in range(len(values))]
                for index in range(len(values))
            ]
        )
        llm, unavailable_reason = _resolve_llm(document, max_requests)
        classic_result = _evaluate_engine("classic", classic, sampled, classic)
        page_chunks = [
            chunk
            for chunk in chunks
            if (chunk.page_start or chunk.page) <= 30
            and (chunk.page_end or chunk.page) >= 20
        ]
        if llm is None:
            llm_result = {
                "engine": "llm",
                "sampled_chunks": len(sampled),
                "generated": 0,
                "attempts": 0,
                "duplicates": 0,
                "accepted": [],
                "rejected": [],
                "reasons": {unavailable_reason or "provider_unavailable": 1},
                "round_trip_failures": 0,
                "parse_failures": 0,
                "provider_errors": 0,
                "provider_answers": {},
                "provider_responses": {},
                "returned_type_counts": {},
                "provider_error_details": [],
                "provider_skipped": [],
                "questions_returned": 0,
                "requests_used": 0,
                "rate_limited": False,
                "pass_rate": None,
            }
        else:
            llm_result = _evaluate_engine("llm", llm, sampled, classic)

        page_llm, _ = _resolve_llm(document, max_requests=8)
        if page_llm is not None and llm is not None:
            page_llm.requested_chunk_ids = llm.requested_chunk_ids
        page_candidates = sample_chunks(page_chunks, limit=8)
        if page_llm is not None:
            page_candidates = [
                chunk
                for chunk in page_candidates
                if chunk.id not in page_llm.requested_chunk_ids
            ]
            page_llm_result = _evaluate_engine(
                "llm", page_llm, page_candidates, classic
            )
            page_llm_questions = page_llm_result["accepted"]
        else:
            page_llm_questions = []
        page_classic_result = _evaluate_engine("classic", classic, page_chunks, classic)
        page_result_questions = list(page_llm_questions)
        page_seen = [item["question"] for item in page_result_questions]
        for item in page_classic_result["accepted"]:
            if len(page_result_questions) >= 10:
                break
            if not _is_duplicate(item["question"], page_seen):
                page_result_questions.append(item)
                page_seen.append(item["question"])

        lines = [
            "# Quiz quality report",
            "",
            f"Document: {document.title} (id {document.id}); "
            f"private: {document.is_private}",
            f"Indexed chunks: {len(chunks)}; sampled pages "
            f"{sorted({c.page for c in sampled})} across "
            f"{len({c.section for c in sampled})} sections.",
            f"Each LLM request asks for up to {QUESTIONS_PER_CHUNK} outputs; "
            f"the LLM request budget is {max_requests}.",
            "Duplicate outputs are reported separately and excluded from "
            "validation-attempt counts.",
            "Private text is never sent to an LLM provider. Both engines use "
            "the local QA round-trip check.",
            "",
        ]
        lines.extend(_engine_report(classic_result))
        lines.extend(
            [
                "## Pages 20-30 classic quiz check",
                "",
                f"Accepted: {len(page_result_questions)} questions from "
                f"{len(page_chunks)} chunks.",
                (
                    "10-question quiz passed."
                    if len(page_result_questions) >= 10
                    else (
                        f"only {len(page_result_questions)} passed; use the LLM engine."
                    )
                ),
                "",
                "Questions (LLM first, classic fallback):",
                *[
                    f"{i}. p.{item['page']} [{item['type']}] {item['question']} "
                    f"-> {item['answer']} (evidence: {item.get('evidence', '')})"
                    for i, item in enumerate(page_result_questions[:10], 1)
                ],
                "",
            ]
        )
        lines.extend(_engine_report(llm_result))
        notes = [
            "## Notes",
            "",
            "- Pass rates are automated validation rates, not a human rating "
            "of pedagogical quality.",
            "- LLM parse failures count each invalid response, including the "
            "strict retry; failed LLM outputs are not relabeled as classic.",
            "- A provider error or private source yields an unavailable LLM "
            "rate rather than a fallback score.",
            "- Up to ten accepted and ten rejected examples are included per "
            "engine; fewer appear when fewer passed through that path.",
        ]
        if llm_result["provider_errors"]:
            notes.append(
                f"- The LLM provider reported {llm_result['provider_errors']} "
                "request errors; its pass rate covers returned candidates only "
                "and should be read alongside the provider error count."
            )
        if llm_result["rate_limited"]:
            notes.append(
                f"- Rate limited, {llm_result['questions_returned']} questions "
                f"generated after {llm_result['requests_used']} requests; "
                "stopped early."
            )
        lines.extend(notes)
        report = "\n".join(lines) + "\n"
        path = (
            Path(__file__).resolve().parents[2] / "docs" / "results" / "quiz_quality.md"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
        return report
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--document-id", type=int, required=True)
    parser.add_argument("--max-requests", type=int, default=12)
    parser.add_argument(
        "--diagnose-one",
        action="store_true",
        help="make one Groq request and print safe diagnostics",
    )
    args = parser.parse_args()
    try:
        if args.diagnose_one:
            diagnose_one_request(args.document_id)
            return 0
        report = run(args.document_id, max_requests=args.max_requests)
    except ValueError as error:
        print(f"Quality run refused: {error}", file=sys.stderr)
        return 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    summary = [
        line
        for line in report.splitlines()
        if line.startswith(
            (
                "## ",
                "- Chunks sampled:",
                "- Candidate outputs:",
                "- Pass rate:",
                "- LLM parse failures:",
                "- Requests used:",
                "- Rate limited:",
                "- Questions returned:",
                "- Provider answers:",
                "- Provider responses:",
                "- Provider failure:",
                "- Provider skipped:",
                "- Question type mix (returned):",
                "- Accepted by type:",
                "- Accepted true/false counts:",
                "- Final true/false balance:",
                "- Rate limited,",
            )
        )
    ]
    examples = _accepted_report_lines(report, "llm")[:10]
    print(
        "\n".join(
            summary
            + ["", "Accepted LLM questions:"]
            + (examples or ["- No accepted LLM questions."])
        )
    )
    return 0


def _accepted_report_lines(report: str, engine_name: str = "llm") -> list[str]:
    """Extract accepted examples only for the short console summary."""
    selected: list[str] = []
    in_engine = False
    in_accepted = False
    for line in report.splitlines():
        if line == f"## {engine_name}":
            in_engine = True
            in_accepted = False
        elif line.startswith("## "):
            in_engine = False
            in_accepted = False
        elif in_engine and line == "### Accepted examples":
            in_accepted = True
        elif line.startswith("### "):
            in_accepted = False
        elif in_accepted and line.startswith("- p."):
            selected.append(line)
    return selected


if __name__ == "__main__":
    raise SystemExit(main())
