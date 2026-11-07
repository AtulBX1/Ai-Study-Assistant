"""Grounded document summaries with extractive, T5, and LLM fallback."""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import PROJECT_ROOT, get_settings
from app.models import Document, DocumentPage, DocumentSummary
from app.services.rag.providers import (
    LLMProvider,
    RateLimitError,
)

logger = logging.getLogger(__name__)

SummaryType = Literal["short", "detailed", "chapter_wise"]
EngineType = Literal["extractive", "t5", "llm"]

PROMPT_VERSION = "v1"
T5_WEIGHTS_DIR = PROJECT_ROOT / "models" / "transformers" / "t5-summarization"

_SENTENCE_SPLIT_REGEX = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\"')\]]))\s+")
_INITIALISM_REGEX = re.compile(r"\b(?:[A-Za-z]\.){2,}")
_BULLET_PREFIX_REGEX = re.compile(r"^[-*•\d+.)]\s*")
_TOC_LINE_REGEX = re.compile(
    r"(\.{3,}|_{3,}|\-{3,}|\t|\s{4,})\s*(?:page\s*)?\d+\s*$", re.IGNORECASE
)
OCR_PLACEHOLDER_REGEX = re.compile(r"<\s*num\s*>|\[table\b", re.IGNORECASE)
_STOPWORDS = {
    "a",
    "about",
    "above",
    "after",
    "again",
    "against",
    "all",
    "am",
    "an",
    "and",
    "any",
    "are",
    "aren't",
    "as",
    "at",
    "be",
    "because",
    "been",
    "before",
    "being",
    "below",
    "between",
    "both",
    "but",
    "by",
    "can't",
    "cannot",
    "could",
    "couldn't",
    "did",
    "didn't",
    "do",
    "does",
    "doesn't",
    "doing",
    "don't",
    "down",
    "during",
    "each",
    "few",
    "for",
    "from",
    "further",
    "had",
    "hadn't",
    "has",
    "hasn't",
    "have",
    "haven't",
    "having",
    "he",
    "he'd",
    "he'll",
    "he's",
    "her",
    "here",
    "here's",
    "hers",
    "herself",
    "him",
    "himself",
    "his",
    "how",
    "how's",
    "i",
    "i'd",
    "i'll",
    "i'm",
    "i've",
    "if",
    "in",
    "into",
    "is",
    "isn't",
    "it",
    "it's",
    "its",
    "itself",
    "let's",
    "me",
    "more",
    "most",
    "mustn't",
    "my",
    "myself",
    "no",
    "nor",
    "not",
    "of",
    "off",
    "on",
    "once",
    "only",
    "or",
    "other",
    "ought",
    "our",
    "ours",
    "ourselves",
    "out",
    "over",
    "own",
    "same",
    "shan't",
    "she",
    "she'd",
    "she'll",
    "she's",
    "should",
    "shouldn't",
    "so",
    "some",
    "such",
    "than",
    "that",
    "that's",
    "the",
    "their",
    "theirs",
    "them",
    "themselves",
    "then",
    "there",
    "there's",
    "these",
    "they",
    "they'd",
    "they'll",
    "they're",
    "they've",
    "this",
    "those",
    "through",
    "to",
    "too",
    "under",
    "until",
    "up",
    "very",
    "was",
    "wasn't",
    "we",
    "we'd",
    "we'll",
    "we're",
    "we've",
    "were",
    "weren't",
    "what",
    "what's",
    "when",
    "when's",
    "where",
    "where's",
    "which",
    "while",
    "who",
    "who's",
    "whom",
    "why",
    "why's",
    "with",
    "won't",
    "would",
    "wouldn't",
    "you",
    "you'd",
    "you'll",
    "you're",
    "you've",
    "your",
    "yours",
    "yourself",
    "yourselves",
}

# In-memory summary cache: key -> list of summary item dicts
_SUMMARY_CACHE: dict[str, list[dict[str, Any]]] = {}

# Background jobs status dictionary
_SUMMARY_JOBS: dict[str, dict[str, Any]] = {}


@dataclass
class DocumentSection:
    section_id: str
    title: str
    page_start: int
    page_end: int
    text: str
    pages: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class ScoredSentence:
    text: str
    page: int
    score: float
    original_index: int


def normalize_whitespace(text: str) -> str:
    """Normalize repeated whitespace and trim."""
    return " ".join(text.split())


def split_sentences(text: str) -> list[str]:
    """Split text into sentences while preserving original content."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    sentences: list[str] = []
    for line in lines:
        protected_line = _INITIALISM_REGEX.sub(
            lambda match: match.group().replace(".", "\x00"), line
        )
        parts = _SENTENCE_SPLIT_REGEX.split(protected_line)
        for part in parts:
            part = part.replace("\x00", ".").strip()
            if part:
                sentences.append(part)
    return sentences


def is_content_chunk(text: str) -> bool:
    """Check if chunk contains meaningful prose rather than outline/TOC style fragments.

    Skips bullet fragments and table-of-contents / outline style chunks that have
    fewer than 40 words of full sentences.
    """
    clean = text.strip()
    if not clean:
        return False

    lines = [line.strip() for line in clean.splitlines() if line.strip()]
    if not lines:
        return False

    toc_or_outline_markers = 0
    bullet_fragments = 0
    full_sentence_words = 0

    for line in lines:
        if _TOC_LINE_REGEX.search(line):
            toc_or_outline_markers += 1
            continue

        stripped_line = _BULLET_PREFIX_REGEX.sub("", line).strip()
        words = stripped_line.split()

        # A full sentence starts with uppercase and ends with sentence punctuation
        if len(words) >= 4 and stripped_line[-1] in ".!?":
            full_sentence_words += len(words)
        else:
            bullet_fragments += 1

    # Outline or table-of-contents style check
    is_outline_style = toc_or_outline_markers > 0 or (
        len(lines) > 2
        and (bullet_fragments + toc_or_outline_markers) / len(lines) >= 0.5
    )

    # If outline/TOC style, requires >= 40 words of full sentences to be content
    if is_outline_style and full_sentence_words < 40:
        return False

    return True


def extract_sections(
    pages: list[DocumentPage],
    page_start: int | None = None,
    page_end: int | None = None,
) -> list[DocumentSection]:
    """Segment document pages by headings if present, otherwise by 10-page blocks.

    Skips outline-style or non-content chunks.
    """
    if not pages:
        return []

    # Filter pages by page range
    filtered_pages = [
        p
        for p in pages
        if (page_start is None or p.page_number >= page_start)
        and (page_end is None or p.page_number <= page_end)
    ]
    if not filtered_pages:
        return []

    # Check for headings in the filtered pages
    headings_found: list[tuple[int, str]] = []  # (page_number, heading_text)
    for p in filtered_pages:
        if p.headings and isinstance(p.headings, list):
            for h in p.headings:
                if isinstance(h, dict) and "text" in h:
                    htext = str(h["text"]).strip()
                    # Filter out tiny or purely numeric headings
                    if len(htext) >= 3 and not htext.isdigit():
                        headings_found.append((p.page_number, htext))

    sections: list[DocumentSection] = []

    if headings_found:
        # Group by headings
        # Sort headings by page number
        headings_found.sort(key=lambda x: x[0])
        for idx, (h_page, h_text) in enumerate(headings_found):
            next_page = (
                headings_found[idx + 1][0]
                if idx + 1 < len(headings_found)
                else filtered_pages[-1].page_number + 1
            )
            # Pages belonging to this section
            sec_pages = [
                p for p in filtered_pages if h_page <= p.page_number < next_page
            ]
            if not sec_pages:
                continue

            sec_text = "\n\n".join(
                (p.cleaned_text or p.text or "").strip()
                for p in sec_pages
                if (p.cleaned_text or p.text or "").strip()
            )

            # Skip outline / non-content chunks
            if not is_content_chunk(sec_text):
                continue

            sec_id = f"sec_h_{h_page}_{idx}"
            sections.append(
                DocumentSection(
                    section_id=sec_id,
                    title=h_text,
                    page_start=sec_pages[0].page_number,
                    page_end=sec_pages[-1].page_number,
                    text=sec_text,
                    pages=[
                        (p.page_number, p.cleaned_text or p.text or "")
                        for p in sec_pages
                    ],
                )
            )

    # If no headings yielded content sections, partition into ~10-page blocks
    if not sections:
        block_size = 10
        total_p = len(filtered_pages)
        for i in range(0, total_p, block_size):
            chunk_pages = filtered_pages[i : i + block_size]
            sec_text = "\n\n".join(
                (p.cleaned_text or p.text or "").strip()
                for p in chunk_pages
                if (p.cleaned_text or p.text or "").strip()
            )

            if not is_content_chunk(sec_text):
                continue

            start_num = chunk_pages[0].page_number
            end_num = chunk_pages[-1].page_number
            title = (
                f"Pages {start_num}-{end_num}"
                if start_num != end_num
                else f"Page {start_num}"
            )
            sec_id = f"sec_block_{start_num}_{end_num}"
            sections.append(
                DocumentSection(
                    section_id=sec_id,
                    title=title,
                    page_start=start_num,
                    page_end=end_num,
                    text=sec_text,
                    pages=[
                        (p.page_number, p.cleaned_text or p.text or "")
                        for p in chunk_pages
                    ],
                )
            )

    return sections


def _tokenize_for_scoring(text: str) -> list[str]:
    """Tokenize and remove punctuation and stopwords."""
    words = re.findall(r"\b[a-zA-Z0-9_]{2,}\b", text.lower())
    return [w for w in words if w not in _STOPWORDS]


def summarize_extractive(
    section_pages: list[tuple[int, str]],
    target_sentences: int = 4,
) -> list[dict[str, Any]]:
    """Rank sentences using TF-IDF plus position weighting and remove near-duplicates.

    Maintains source text fidelity and source order.
    """
    # Candidate pool: (sentence_text, page_number, original_idx)
    candidates: list[tuple[str, int, int]] = []
    original_idx = 0

    for page_num, ptext in section_pages:
        sentences = split_sentences(ptext)
        for sent in sentences:
            clean_sent = sent.strip()
            # Clean leading bullet indicators if purely formatting
            if clean_sent.startswith(("- ", "* ", "• ")):
                clean_sent = clean_sent[2:].strip()

            words = clean_sent.split()
            # Filter bullet fragments, tiny fragments, or TOC lines
            if (
                len(words) < 5
                or clean_sent[-1] not in ".!?"
                or _TOC_LINE_REGEX.search(clean_sent)
                or OCR_PLACEHOLDER_REGEX.search(clean_sent)
            ):
                continue

            candidates.append((clean_sent, page_num, original_idx))
            original_idx += 1

    if not candidates:
        return []

    # If candidate pool is small, keep all in source order
    if len(candidates) <= target_sentences:
        return [
            {
                "text": text,
                "page_start": page,
                "page_end": page,
                "engine": "extractive",
                "evidence_sentence": None,
            }
            for text, page, _ in candidates
        ]

    # Calculate TF across candidate sentences
    all_tokens = [_tokenize_for_scoring(text) for text, _, _ in candidates]
    term_counts: Counter[str] = Counter()
    doc_freqs: Counter[str] = Counter()
    for tokens in all_tokens:
        term_counts.update(tokens)
        doc_freqs.update(set(tokens))

    total_sentences = len(candidates)
    scored: list[ScoredSentence] = []

    for idx, (text, page, orig_idx) in enumerate(candidates):
        tokens = all_tokens[idx]
        if not tokens:
            continue

        # TF-IDF sum normalized by sentence length
        tfidf_score = 0.0
        for token in tokens:
            tf = tokens.count(token)
            idf = math.log((total_sentences + 1.0) / (doc_freqs[token] + 1.0)) + 1.0
            tfidf_score += tf * idf
        tfidf_score = tfidf_score / (len(tokens) ** 0.8)

        # Position weight: lead sentences in section / paragraphs carry bonus
        position_weight = 1.0 + 0.4 * (1.0 - (idx / total_sentences))
        final_score = tfidf_score * position_weight

        scored.append(
            ScoredSentence(
                text=text,
                page=page,
                score=final_score,
                original_index=orig_idx,
            )
        )

    # Sort descending by score
    scored.sort(key=lambda x: x.score, reverse=True)

    # Near-duplicate filtering using token Jaccard similarity
    selected: list[ScoredSentence] = []
    for cand in scored:
        cand_tokens = set(_tokenize_for_scoring(cand.text))
        is_duplicate = False
        for existing in selected:
            exist_tokens = set(_tokenize_for_scoring(existing.text))
            if not cand_tokens or not exist_tokens:
                continue
            jaccard = len(cand_tokens & exist_tokens) / len(cand_tokens | exist_tokens)
            if jaccard > 0.55:
                is_duplicate = True
                break

        if not is_duplicate:
            selected.append(cand)
            if len(selected) >= target_sentences:
                break

    # Keep original source order
    selected.sort(key=lambda x: x.original_index)

    return [
        {
            "text": s.text,
            "page_start": s.page,
            "page_end": s.page,
            "engine": "extractive",
            "evidence_sentence": None,
        }
        for s in selected
    ]


def _filter_t5_repetitions(text: str) -> str:
    """Filter out repeated consecutive phrases or sentences in generation."""
    sentences = split_sentences(text)
    if not sentences:
        return text

    unique: list[str] = []
    seen: set[str] = set()
    for s in sentences:
        norm = normalize_whitespace(s).lower()
        if norm not in seen:
            seen.add(norm)
            unique.append(s)

    return " ".join(unique)


def summarize_t5(
    section_text: str,
    weights_path: Path | None = None,
) -> tuple[str | None, str | None]:
    """Generate abstractive summary using fine-tuned T5-small.

    Checks weight folder existence BEFORE importing torch/transformers.
    Returns (summary_text, fallback_message).
    """
    weights_dir = weights_path or T5_WEIGHTS_DIR
    config_file = weights_dir / "config.json"

    # Strict requirement: check weights existence BEFORE importing torch or transformers
    if not config_file.is_file():
        msg = (
            f"T5 weights not found at {weights_dir}; falling back to extractive engine."
        )
        return None, msg

    try:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    except ImportError as e:
        return (
            None,
            f"Transformer unavailable ({e}); falling back to extractive engine.",
        )

    try:
        tokenizer = AutoTokenizer.from_pretrained(
            str(weights_dir), local_files_only=True
        )
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = AutoModelForSeq2SeqLM.from_pretrained(
            str(weights_dir), local_files_only=True
        ).to(device)
        model.eval()

        input_text = "summarize: " + section_text.strip()
        encoded = tokenizer(
            input_text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
        ).to(device)

        with torch.inference_mode():
            output = model.generate(
                **encoded,
                max_new_tokens=128,
                no_repeat_ngram_size=3,
                num_beams=3,
                do_sample=False,
            )

        summary = tokenizer.decode(output[0], skip_special_tokens=True)
        cleaned_summary = _filter_t5_repetitions(summary)
        return cleaned_summary, None
    except Exception as exc:
        logger.warning(f"T5 generation error: {exc}")
        return None, f"T5 generation error ({exc}); falling back to extractive engine."


def _parse_llm_bullets(content: str) -> list[dict[str, str]]:
    """Parse bullet points containing text and evidence sentence."""
    bullets: list[dict[str, str]] = []
    lines = content.strip().splitlines()

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Strip bullet prefix
        line = _BULLET_PREFIX_REGEX.sub("", line).strip()

        # Check for Point: ... | Evidence: ...
        point_match = re.search(
            r"Point:\s*(.*?)(?=\|\s*Evidence:|$)", line, re.IGNORECASE
        )
        evidence_match = re.search(r"Evidence:\s*(.*)$", line, re.IGNORECASE)

        if point_match and evidence_match:
            point = point_match.group(1).strip()
            evidence = evidence_match.group(1).strip().strip("\"'")
            if point and evidence:
                bullets.append({"point": point, "evidence": evidence})
        elif " | " in line:
            parts = line.split(" | ", 1)
            bullets.append(
                {"point": parts[0].strip(), "evidence": parts[1].strip().strip("\"'")}
            )
        elif "(Evidence:" in line:
            point, _, ev = line.partition("(Evidence:")
            ev = ev.rstrip(")").strip().strip("\"'")
            bullets.append({"point": point.strip(), "evidence": ev})

    return bullets


def summarize_llm_section(
    section: DocumentSection,
    document: Document,
    provider: LLMProvider,
) -> tuple[list[dict[str, Any]], str | None]:
    """Generate grounded bullets using an LLM provider under ~1,500 token limit.

    Rejects bullets whose evidence is not found in the section text.
    Returns (items, error_reason).
    """
    # Privacy check: Never send private documents to an external provider
    if document.is_private and getattr(provider, "is_external", False):
        return [], "Private document cannot be sent to external LLM provider."

    # Cache check
    section_digest = sha256(section.text.encode("utf-8")).hexdigest()
    cache_key = (
        f"summary:{document.id}:{section.section_id}:{section_digest}:"
        f"llm:{PROMPT_VERSION}"
    )
    if cache_key in _SUMMARY_CACHE:
        return _SUMMARY_CACHE[cache_key], None

    # Limit section input to ~1,500 tokens (~5,000 chars)
    trimmed_text = section.text
    if len(trimmed_text) > 5000:
        # Take the most representative content sentences
        sents = split_sentences(trimmed_text)
        trimmed_text = " ".join(sents[:30])

    prompt = (
        f"Summarize section '{section.title}' into 2 to 4 bullet points.\n"
        "MANDATORY REQUIREMENT: Each bullet point MUST include an exact 'evidence' "
        "sentence copied verbatim from the text that directly supports the point.\n"
        "Format each bullet point on its own line exactly as:\n"
        "- Point: <summary point> | Evidence: <exact sentence copied from text>\n\n"
        f"Section Text:\n{trimmed_text}"
    )

    try:
        response_text = provider.generate(prompt)
    except RateLimitError as rle:
        raise rle
    except Exception as exc:
        return [], f"LLM provider error: {exc}"

    # Parse message content
    raw_bullets = _parse_llm_bullets(response_text)
    if not raw_bullets:
        return [], "LLM output did not contain valid bullet points with evidence."

    norm_section = normalize_whitespace(section.text).casefold()

    valid_items: list[dict[str, Any]] = []
    for bullet in raw_bullets:
        point = bullet["point"]
        evidence = bullet["evidence"]
        norm_evidence = normalize_whitespace(evidence).casefold()

        # Grounding check: reject bullet if evidence is not found in section
        if norm_evidence and norm_evidence in norm_section:
            # Find matching page for citation
            ev_page = section.page_start
            for p_num, p_text in section.pages:
                if norm_evidence in normalize_whitespace(p_text).casefold():
                    ev_page = p_num
                    break

            valid_items.append(
                {
                    "text": point,
                    "page_start": ev_page,
                    "page_end": ev_page,
                    "engine": "llm",
                    "evidence_sentence": evidence,
                }
            )
        else:
            logger.info(f"Rejected ungrounded LLM bullet: {point}")

    if valid_items:
        _SUMMARY_CACHE[cache_key] = valid_items
        return valid_items, None

    return [], "All LLM bullets failed grounding verification against the source text."


def generate_document_summary(
    db: Session,
    *,
    document: Document,
    summary_type: SummaryType = "short",
    engine: EngineType = "extractive",
    page_start: int | None = None,
    page_end: int | None = None,
    provider: LLMProvider | None = None,
    weights_path: Path | None = None,
) -> DocumentSummary:
    """Generate and persist a grounded summary with automatic fallback."""
    pages = list(
        db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == document.id)
            .order_by(DocumentPage.page_number)
        )
    )
    if not pages:
        raise ValueError(f"Document {document.id} has no pages to summarize.")

    llm_fallback_reason: str | None = None
    if engine == "llm" and provider is None:
        settings = get_settings()
        if settings.allow_external_llm:
            from app.services.rag.pipeline import RAGChatPipeline

            provider = RAGChatPipeline(settings=settings).provider
        else:
            llm_fallback_reason = "External LLM use is disabled."

    sections = extract_sections(pages, page_start=page_start, page_end=page_end)
    if not sections:
        # Fall back to raw text of all requested pages
        filtered_pages = [
            p
            for p in pages
            if (page_start is None or p.page_number >= page_start)
            and (page_end is None or p.page_number <= page_end)
        ]
        if not filtered_pages:
            raise ValueError("No pages found in the requested page range.")

        sec_text = "\n\n".join(
            (p.cleaned_text or p.text or "").strip()
            for p in filtered_pages
            if (p.cleaned_text or p.text or "").strip()
        )
        sections = [
            DocumentSection(
                section_id="fallback_full",
                title="Document Overview",
                page_start=filtered_pages[0].page_number,
                page_end=filtered_pages[-1].page_number,
                text=sec_text,
                pages=[
                    (p.page_number, p.cleaned_text or p.text or "")
                    for p in filtered_pages
                ],
            )
        ]

    # Map Step: summarize each section according to engine with ordered fallback
    # Engine order: requested engine -> next available (llm -> t5 -> extractive)
    initial_engine = engine
    active_engine = engine
    section_results: list[dict[str, Any]] = []
    overall_engine_used = engine
    fallback_reasons: list[str] = []

    for _sec_idx, sec in enumerate(sections):
        sec_items: list[dict[str, Any]] = []
        sec_engine_used = active_engine

        # 1. Try LLM if requested
        if active_engine == "llm":
            if provider is None:
                sec_engine_used = "extractive"
                fallback_reasons.append(
                    llm_fallback_reason or "No LLM provider available."
                )
                sec_items = summarize_extractive(sec.pages, target_sentences=3)
            else:
                try:
                    items, err = summarize_llm_section(sec, document, provider)
                    if items:
                        sec_items = items
                    else:
                        fallback_reasons.append(err or "LLM generation rejected.")
                        # Fallback to T5 or extractive
                        t5_text, t5_msg = summarize_t5(
                            sec.text, weights_path=weights_path
                        )
                        if t5_text:
                            sec_engine_used = "t5"
                            sec_items = [
                                {
                                    "text": t5_text,
                                    "page_start": sec.page_start,
                                    "page_end": sec.page_end,
                                    "engine": "t5",
                                    "evidence_sentence": None,
                                }
                            ]
                        else:
                            sec_engine_used = "extractive"
                            if t5_msg:
                                fallback_reasons.append(t5_msg)
                            sec_items = summarize_extractive(
                                sec.pages, target_sentences=3
                            )
                except RateLimitError as rle:
                    # Rate limit: return partial result and fall back (no loop)
                    fallback_reasons.append(
                        f"LLM rate limited: {rle}; falling back to extractive."
                    )
                    sec_engine_used = "extractive"
                    sec_items = summarize_extractive(sec.pages, target_sentences=3)
                    # Switch future sections to extractive as well
                    active_engine = "extractive"

        # 2. Try T5 if requested or fallen back to
        elif active_engine == "t5":
            t5_text, t5_msg = summarize_t5(sec.text, weights_path=weights_path)
            if t5_text:
                sec_items = [
                    {
                        "text": t5_text,
                        "page_start": sec.page_start,
                        "page_end": sec.page_end,
                        "engine": "t5",
                        "evidence_sentence": None,
                    }
                ]
            else:
                sec_engine_used = "extractive"
                fallback_reasons.append(
                    t5_msg or "T5 unavailable; falling back to extractive."
                )
                sec_items = summarize_extractive(sec.pages, target_sentences=3)

        # 3. Extractive (always available)
        else:
            sec_items = summarize_extractive(sec.pages, target_sentences=3)

        section_results.append(
            {
                "section_id": sec.section_id,
                "title": sec.title,
                "page_start": sec.page_start,
                "page_end": sec.page_end,
                "engine": sec_engine_used,
                "items": sec_items,
            }
        )

    # Determine overall engine used
    used_engines = {r["engine"] for r in section_results}
    if len(used_engines) == 1:
        overall_engine_used = used_engines.pop()
    else:
        overall_engine_used = (
            "hybrid" if len(used_engines) > 1 else list(used_engines)[0]
        )

    # Build final summary based on requested type
    final_items: list[dict[str, Any]] = []
    markdown_lines: list[str] = []

    actual_start = sections[0].page_start
    actual_end = sections[-1].page_end

    if summary_type == "short":
        # Map-Reduce: collect all candidate sentences across sections,
        # then select top 3-5 sentences total using extractive centrality
        all_section_items: list[dict[str, Any]] = []
        for sec_res in section_results:
            for item in sec_res["items"]:
                all_section_items.append(item)

        # Reduce step: select 3-5 sentences
        reduced = summarize_extractive(
            [(item["page_start"], item["text"]) for item in all_section_items],
            target_sentences=4,
        )
        for item in reduced:
            source_item = next(
                source
                for source in all_section_items
                if source["page_start"] == item["page_start"]
                and source["text"] == item["text"]
            )
            item.update(
                page_end=source_item.get("page_end", item["page_start"]),
                engine=source_item["engine"],
                evidence_sentence=source_item.get("evidence_sentence"),
            )
        if not reduced and all_section_items:
            reduced = [
                {
                    "text": item["text"],
                    "page_start": item["page_start"],
                    "page_end": item.get("page_end", item["page_start"]),
                    "engine": item["engine"],
                    "evidence_sentence": item.get("evidence_sentence"),
                }
                for item in all_section_items[:4]
            ]
        final_items = reduced

        markdown_lines.append(f"## Summary (pp. {actual_start}-{actual_end})\n")
        for item in final_items:
            markdown_lines.append(f"- {item['text']} [p. {item['page_start']}]")

    elif summary_type == "detailed":
        markdown_lines.append(
            f"## Detailed Summary (pp. {actual_start}-{actual_end})\n"
        )
        for sec_res in section_results:
            title = sec_res["title"]
            p_st, p_en = sec_res["page_start"], sec_res["page_end"]
            markdown_lines.append(f"### {title} (pp. {p_st}-{p_en})")
            for item in sec_res["items"]:
                final_items.append(item)
                ev = (
                    f' *(Evidence: "{item["evidence_sentence"]}")*'
                    if item.get("evidence_sentence")
                    else ""
                )
                markdown_lines.append(f"- {item['text']} [p. {item['page_start']}]{ev}")
            markdown_lines.append("")

    else:  # chapter_wise
        markdown_lines.append(
            f"## Chapter-Wise Summary (pp. {actual_start}-{actual_end})\n"
        )
        for sec_res in section_results:
            title = sec_res["title"]
            p_st, p_en = sec_res["page_start"], sec_res["page_end"]
            markdown_lines.append(f"### {title} (pp. {p_st}-{p_en})")
            sec_texts = [item["text"] for item in sec_res["items"]]
            combined = " ".join(sec_texts)
            final_items.append(
                {
                    "title": sec_res["title"],
                    "text": combined,
                    "page_start": sec_res["page_start"],
                    "page_end": sec_res["page_end"],
                    "engine": sec_res["engine"],
                    "evidence_sentence": None,
                }
            )
            markdown_lines.append(f"{combined}\n")

    content_markdown = "\n".join(markdown_lines).strip()
    fallback_reason_text = (
        " | ".join(dict.fromkeys(fallback_reasons)) if fallback_reasons else None
    )

    summary_record = DocumentSummary(
        document_id=document.id,
        owner_id=document.owner_id,
        summary_type=summary_type,
        engine_requested=initial_engine,
        engine_used=overall_engine_used,
        fallback_reason=fallback_reason_text,
        page_start=actual_start,
        page_end=actual_end,
        content=content_markdown,
        items=final_items,
        generation_metadata={
            "sections_count": len(sections),
            "generated_at": datetime.now(UTC).isoformat(),
            "fallback_reasons": fallback_reasons,
            "requested_page_start": page_start,
            "requested_page_end": page_end,
        },
    )
    db.add(summary_record)
    db.flush()
    return summary_record


def start_summary_job(
    job_id: str,
    db: Session,
    document_id: int,
    owner_id: int,
    summary_type: SummaryType,
    engine: EngineType,
    page_start: int | None,
    page_end: int | None,
) -> None:
    """Execute background summary generation and update job status."""
    _SUMMARY_JOBS[job_id] = {
        "status": "processing",
        "progress": 20,
        "summary_id": None,
        "error": None,
        "owner_id": owner_id,
    }
    try:
        document = db.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.owner_id == owner_id,
            )
        )
        if not document:
            _SUMMARY_JOBS[job_id] = {
                "status": "failed",
                "progress": 100,
                "summary_id": None,
                "error": "Document not found or ownership mismatch.",
                "owner_id": owner_id,
            }
            return

        summary = generate_document_summary(
            db,
            document=document,
            summary_type=summary_type,
            engine=engine,
            page_start=page_start,
            page_end=page_end,
        )
        db.commit()

        _SUMMARY_JOBS[job_id] = {
            "status": "completed",
            "progress": 100,
            "summary_id": summary.id,
            "error": None,
            "owner_id": owner_id,
        }
    except Exception as exc:
        db.rollback()
        logger.error(f"Async summary job {job_id} failed: {exc}", exc_info=True)
        _SUMMARY_JOBS[job_id] = {
            "status": "failed",
            "progress": 100,
            "summary_id": None,
            "error": str(exc),
            "owner_id": owner_id,
        }


def get_summary_job_status(job_id: str, owner_id: int) -> dict[str, Any] | None:
    """Retrieve a summary job's public status for its owning user."""
    status = _SUMMARY_JOBS.get(job_id)
    if status is None or status["owner_id"] != owner_id:
        return None
    return {key: value for key, value in status.items() if key != "owner_id"}
