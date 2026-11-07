"""Exam paper assembly shared by the legacy and universal export endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.study.exports import ExportDocument


def build_exam_document(
    title: str,
    sections: dict[str, list[dict[str, Any]]],
    marks_per_question: int = 1,
    *,
    include_answers: bool = True,
) -> ExportDocument:
    """Build question, mark, and optional marking-scheme blocks."""
    from app.services.study.exports import ExportBlock, ExportDocument

    marks_total = 0
    blocks: list[ExportBlock] = []
    for section, questions in sections.items():
        blocks.append(ExportBlock(kind="heading", text=section, level=2))
        for index, item in enumerate(questions, 1):
            marks = item.get("marks", marks_per_question)
            if not isinstance(marks, int) or marks < 1:
                marks = marks_per_question
            marks_total += marks
            blocks.append(
                ExportBlock(
                    kind="paragraph",
                    text=f"{index}. {item['question']} [{marks} marks]",
                )
            )
            blocks.extend(
                ExportBlock(
                    kind="paragraph",
                    text=f"{chr(65 + choice)}. {option}",
                )
                for choice, option in enumerate(item.get("options") or [])
            )
    blocks.insert(
        0,
        ExportBlock(kind="paragraph", text=f"Total marks: {marks_total}"),
    )
    if include_answers:
        blocks.append(ExportBlock(kind="heading", text="Marking Scheme", level=1))
        for section, questions in sections.items():
            for index, item in enumerate(questions, 1):
                answer = item.get("correct_answer", "")
                explanation = item.get("explanation", "")
                text = f"{section} {index}: {answer}"
                if explanation:
                    text = f"{text} - {explanation}"
                blocks.append(ExportBlock(kind="paragraph", text=text))
    return ExportDocument(title=title, blocks=blocks)


def export_pdf(
    title: str,
    sections: dict[str, list[dict[str, Any]]],
    marks_per_question: int = 1,
) -> bytes:
    """Create an in-memory PDF exam paper with ReportLab."""
    from app.services.study.exports import export_pdf as render_pdf

    return render_pdf(build_exam_document(title, sections, marks_per_question))


def export_docx(
    title: str,
    sections: dict[str, list[dict[str, Any]]],
    marks_per_question: int = 1,
) -> bytes:
    """Create an in-memory Unicode DOCX exam paper with python-docx."""
    from app.services.study.exports import export_docx as render_docx

    return render_docx(build_exam_document(title, sections, marks_per_question))
