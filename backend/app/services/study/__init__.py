"""Grounded study materials and spaced-repetition helpers."""

from app.services.study.exports import ExportBlock, ExportDocument, generate_export
from app.services.study.flashcards import generate_document_flashcards
from app.services.study.glossary import (
    find_evidence_sentence,
    grounded_custom_term,
    normalize_term,
    regenerate_glossary,
)
from app.services.study.multi_document import answer_across_documents, compare_documents
from app.services.study.notes import generate_chapter_notes, generate_cheat_sheet
from app.services.study.sm2 import schedule_review
from app.services.study.summaries import (
    DocumentSection,
    extract_sections,
    generate_document_summary,
    get_summary_job_status,
    is_content_chunk,
    start_summary_job,
    summarize_extractive,
    summarize_llm_section,
    summarize_t5,
)

__all__ = [
    "DocumentSection",
    "ExportBlock",
    "ExportDocument",
    "answer_across_documents",
    "compare_documents",
    "extract_sections",
    "find_evidence_sentence",
    "generate_chapter_notes",
    "generate_cheat_sheet",
    "generate_document_flashcards",
    "generate_export",
    "generate_document_summary",
    "get_summary_job_status",
    "grounded_custom_term",
    "is_content_chunk",
    "normalize_term",
    "regenerate_glossary",
    "schedule_review",
    "start_summary_job",
    "summarize_extractive",
    "summarize_llm_section",
    "summarize_t5",
]
