"""Rule-based chapter notes and one-page cheat sheets grounded in document pages."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, DocumentKeyTerm, DocumentPage, GlossaryTerm
from app.services.study.glossary import find_evidence_sentence
from app.services.study.summaries import (
    DocumentSection,
    extract_sections,
    split_sentences,
    summarize_extractive,
)

_EXAMPLE_REGEX = re.compile(
    r"\b(?:for\s+example|for\s+instance|e\.g\.|such\s+as|example:)\b",
    re.IGNORECASE,
)

_MATH_OR_CODE_REGEX = re.compile(
    r"(\b(?:def\s+\w+|import\s+\w+|return\b|class\s+\w+|lambda\b)\b|"
    r"[=><]\s*[\d\w\(\)\+\-\*\/\^]|"
    r"\\(?:frac|sum|int|sigma|alpha|theta|times|cdot)|"
    r"\b(?:argmax|argmin|softmax|loss|perplexity)\b|"
    r"[A-Z]\s*=\s*[\w\d])",
    re.IGNORECASE,
)

_FACT_INDICATORS = re.compile(
    r"\b(?:is\s+defined\s+as|refers\s+to|consists\s+of|means\s+that|"
    r"key\s+property|crucial|primary|fundamental|introduced\s+in)\b",
    re.IGNORECASE,
)


def generate_chapter_notes(
    db: Session,
    *,
    document: Document,
    page_start: int | None = None,
    page_end: int | None = None,
) -> str:
    """Generate chapter notes in Markdown with key terms, points, and citations."""
    pages = list(
        db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == document.id)
            .order_by(DocumentPage.page_number)
        )
    )
    if not pages:
        return f"# Chapter Notes: {document.title}\n\n*No content available.*"

    sections = extract_sections(pages, page_start=page_start, page_end=page_end)
    if not sections:
        # Fallback to single section covering requested pages
        filtered_pages = [
            p
            for p in pages
            if (page_start is None or p.page_number >= page_start)
            and (page_end is None or p.page_number <= page_end)
        ]
        if filtered_pages:
            sec_text = "\n\n".join(
                (p.cleaned_text or p.text or "").strip()
                for p in filtered_pages
                if (p.cleaned_text or p.text or "").strip()
            )
            sections = [
                DocumentSection(
                    section_id="notes_fallback",
                    title="Study Notes",
                    page_start=filtered_pages[0].page_number,
                    page_end=filtered_pages[-1].page_number,
                    text=sec_text,
                    pages=[
                        (p.page_number, p.cleaned_text or p.text or "")
                        for p in filtered_pages
                    ],
                )
            ]

    # Pre-fetch glossary terms for this document and owner
    glossary_terms = list(
        db.scalars(
            select(GlossaryTerm)
            .where(
                GlossaryTerm.document_id == document.id,
                GlossaryTerm.owner_id == document.owner_id,
            )
            .order_by(GlossaryTerm.importance.desc(), GlossaryTerm.page)
        )
    )

    # Pre-fetch key terms as fallback if glossary not yet populated
    doc_key_terms = list(
        db.scalars(
            select(DocumentKeyTerm)
            .where(DocumentKeyTerm.document_id == document.id)
            .order_by(DocumentKeyTerm.page)
        )
    )

    lines: list[str] = [f"# Chapter Notes: {document.title}\n"]

    for sec in sections:
        lines.append(f"## {sec.title} (pp. {sec.page_start}-{sec.page_end})\n")

        # 1. Key terms for this section
        sec_terms = [
            t for t in glossary_terms if sec.page_start <= t.page <= sec.page_end
        ]

        if not sec_terms:
            # Fallback to DocumentKeyTerms
            raw_terms = [
                kt for kt in doc_key_terms if sec.page_start <= kt.page <= sec.page_end
            ]
            seen_raw: set[str] = set()
            for kt in raw_terms:
                norm_t = kt.term.lower().strip()
                if norm_t not in seen_raw:
                    seen_raw.add(norm_t)
                    # Find grounded definition sentence on that page
                    p_text = next((pt for pn, pt in sec.pages if pn == kt.page), "")
                    def_sent = (
                        find_evidence_sentence(p_text, kt.term) or p_text.split(".")[0]
                    )
                    lines.append(f"- **{kt.term}**: {def_sent.strip()} [p. {kt.page}]")
                if len(seen_raw) >= 4:
                    break
        else:
            for t in sec_terms[:5]:
                lines.append(f"- **{t.term}**: {t.definition.strip()} [p. {t.page}]")

        lines.append("\n### Main Points\n")

        # 2. Main points (top extractive sentences)
        main_points = summarize_extractive(sec.pages, target_sentences=3)
        for pt in main_points:
            lines.append(f"- {pt['text']} [p. {pt['page_start']}]")

        # 3. Examples found in the text
        lines.append("\n### Examples\n")
        example_sentences: list[tuple[int, str]] = []
        for p_num, p_text in sec.pages:
            sents = split_sentences(p_text)
            for s in sents:
                s_strip = s.strip()
                if _EXAMPLE_REGEX.search(s_strip) and len(s_strip.split()) >= 6:
                    example_sentences.append((p_num, s_strip))
                if len(example_sentences) >= 3:
                    break
            if len(example_sentences) >= 3:
                break

        if example_sentences:
            for p_num, ex in example_sentences:
                lines.append(f'- "{ex}" [p. {p_num}]')
        else:
            lines.append("*(No explicit examples marked in this section text)*")

        lines.append("\n---\n")

    return "\n".join(lines).strip()


def generate_cheat_sheet(
    db: Session,
    *,
    document: Document,
    page_start: int | None = None,
    page_end: int | None = None,
) -> str:
    """Generate a one-page cheat sheet in Markdown: terms, formulas, and facts."""
    pages = list(
        db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == document.id)
            .order_by(DocumentPage.page_number)
        )
    )
    if not pages:
        return f"# Cheat Sheet: {document.title}\n\n*No content available.*"

    filtered_pages = [
        p
        for p in pages
        if (page_start is None or p.page_number >= page_start)
        and (page_end is None or p.page_number <= page_end)
    ]
    if not filtered_pages:
        return f"# Cheat Sheet: {document.title}\n\n*No content in selected range.*"

    p_min = filtered_pages[0].page_number
    p_max = filtered_pages[-1].page_number
    header_range = f"(pp. {p_min}-{p_max})" if p_min != p_max else f"(p. {p_min})"

    # 1. Top Terms with one-line definitions
    glossary_terms = list(
        db.scalars(
            select(GlossaryTerm)
            .where(
                GlossaryTerm.document_id == document.id,
                GlossaryTerm.owner_id == document.owner_id,
                GlossaryTerm.page >= p_min,
                GlossaryTerm.page <= p_max,
            )
            .order_by(GlossaryTerm.importance.desc(), GlossaryTerm.page)
        )
    )

    term_lines: list[str] = []
    seen_terms: set[str] = set()

    for gt in glossary_terms:
        norm = gt.term.lower().strip()
        if norm not in seen_terms:
            seen_terms.add(norm)
            # Ensure one-line definition
            first_sent = gt.definition.strip().splitlines()[0]
            if len(first_sent) > 160:
                first_sent = first_sent[:157] + "..."
            term_lines.append(f"- **{gt.term}**: {first_sent} [p. {gt.page}]")
        if len(term_lines) >= 8:
            break

    # If no glossary terms, query key terms
    if not term_lines:
        key_terms = list(
            db.scalars(
                select(DocumentKeyTerm)
                .where(
                    DocumentKeyTerm.document_id == document.id,
                    DocumentKeyTerm.page >= p_min,
                    DocumentKeyTerm.page <= p_max,
                )
                .order_by(DocumentKeyTerm.page)
            )
        )
        for kt in key_terms:
            norm = kt.term.lower().strip()
            if norm not in seen_terms:
                seen_terms.add(norm)
                # Find definition sentence from matching page
                p_text = next(
                    (
                        p.cleaned_text or p.text or ""
                        for p in filtered_pages
                        if p.page_number == kt.page
                    ),
                    "",
                )
                def_sent = find_evidence_sentence(p_text, kt.term) or (
                    p_text.split(".")[0] if p_text else ""
                )
                first_sent = def_sent.strip().splitlines()[0] if def_sent else kt.term
                term_lines.append(f"- **{kt.term}**: {first_sent} [p. {kt.page}]")
            if len(term_lines) >= 8:
                break

    # 2. Formulas or code-like lines
    formula_lines: list[str] = []
    seen_formulas: set[str] = set()

    for p in filtered_pages:
        raw_lines = (p.cleaned_text or p.text or "").splitlines()
        for rline in raw_lines:
            rline_clean = rline.strip()
            if not rline_clean or len(rline_clean) < 4:
                continue

            if _MATH_OR_CODE_REGEX.search(rline_clean):
                norm_f = rline_clean.lower()
                if norm_f not in seen_formulas:
                    seen_formulas.add(norm_f)
                    formula_lines.append(f"{rline_clean}  # [p. {p.page_number}]")
            if len(formula_lines) >= 6:
                break
        if len(formula_lines) >= 6:
            break

    # 3. Short list of key facts
    fact_candidates: list[tuple[int, str]] = []
    for p in filtered_pages:
        sents = split_sentences(p.cleaned_text or p.text or "")
        for s in sents:
            s_clean = s.strip()
            if _FACT_INDICATORS.search(s_clean) and len(s_clean.split()) >= 6:
                fact_candidates.append((p.page_number, s_clean))
            if len(fact_candidates) >= 10:
                break
        if len(fact_candidates) >= 10:
            break

    # If few specific indicator sentences, use top extractive sentences across pages
    if len(fact_candidates) < 4:
        extractive_sents = summarize_extractive(
            [(p.page_number, p.cleaned_text or p.text or "") for p in filtered_pages],
            target_sentences=5,
        )
        for es in extractive_sents:
            fact_candidates.append((es["page_start"], es["text"]))

    # Deduplicate and take top 5
    fact_lines: list[str] = []
    seen_facts: set[str] = set()
    for p_num, fact in fact_candidates:
        norm = fact.lower().strip()
        if norm not in seen_facts:
            seen_facts.add(norm)
            fact_lines.append(f"- {fact} [p. {p_num}]")
        if len(fact_lines) >= 5:
            break

    # Build Markdown
    output: list[str] = [
        f"# Cheat Sheet: {document.title} {header_range}\n",
        "## Key Terms & Definitions\n",
    ]
    if term_lines:
        output.extend(term_lines)
    else:
        output.append("*(No terms defined in this range)*")

    output.append("\n## Formulas & Code\n")
    if formula_lines:
        output.append("```text")
        output.extend(formula_lines)
        output.append("```")
    else:
        output.append(
            "*(No explicit mathematical formulas or code snippets identified)*"
        )

    output.append("\n## Key Facts\n")
    if fact_lines:
        output.extend(fact_lines)
    else:
        output.append("*(No key facts extracted)*")

    return "\n".join(output).strip()
