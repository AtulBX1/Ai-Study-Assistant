"""In-memory PDF, DOCX, and CSV exports for stored study materials."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from io import BytesIO, StringIO
from typing import Any, Literal
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Document,
    DocumentSummary,
    Flashcard,
    GlossaryTerm,
    Question,
    Quiz,
    StudyPlan,
    StudyPlanItem,
)
from app.services.study.notes import generate_chapter_notes, generate_cheat_sheet

PDF_MEDIA_TYPE = "application/pdf"
DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
CSV_MEDIA_TYPE = "text/csv; charset=utf-8"


@dataclass(frozen=True)
class ExportBlock:
    """A portable text or table block used by the document renderers."""

    kind: Literal["heading", "paragraph", "bullet", "table"]
    text: str = ""
    level: int = 1
    rows: list[list[str]] = field(default_factory=list)


@dataclass(frozen=True)
class ExportDocument:
    """A titled document made of renderer-independent blocks."""

    title: str
    blocks: list[ExportBlock]


def _markdown_blocks(markdown: str) -> list[ExportBlock]:
    blocks: list[ExportBlock] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line or line == "---":
            continue
        if line.startswith("#"):
            level = min(len(line) - len(line.lstrip("#")), 3)
            blocks.append(
                ExportBlock(
                    kind="heading",
                    text=line.lstrip("#").strip(),
                    level=max(1, level),
                )
            )
        elif line.startswith(("- ", "* ", "• ")):
            blocks.append(ExportBlock(kind="bullet", text=line[2:].strip()))
        else:
            blocks.append(ExportBlock(kind="paragraph", text=line))
    return blocks


def _owned_document(db: Session, document_id: int, owner_id: int) -> Document:
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.owner_id == owner_id,
        )
    )
    if document is None:
        raise LookupError("Study material not found.")
    return document


def _document_export(
    db: Session,
    *,
    owner_id: int,
    kind: str,
    item_id: int,
    page_start: int | None,
    page_end: int | None,
) -> ExportDocument:
    document = _owned_document(db, item_id, owner_id)
    if page_start is not None and page_end is not None and page_start > page_end:
        raise ValueError("page_start must not exceed page_end.")
    if kind == "notes":
        markdown = generate_chapter_notes(
            db,
            document=document,
            page_start=page_start,
            page_end=page_end,
        )
        title = f"Chapter Notes - {document.title}"
    elif kind == "cheat-sheet":
        markdown = generate_cheat_sheet(
            db,
            document=document,
            page_start=page_start,
            page_end=page_end,
        )
        title = f"Cheat Sheet - {document.title}"
    else:
        terms = list(
            db.scalars(
                select(GlossaryTerm)
                .where(
                    GlossaryTerm.document_id == document.id,
                    GlossaryTerm.owner_id == owner_id,
                )
                .order_by(GlossaryTerm.page, GlossaryTerm.term_key)
            )
        )
        rows = [["Term", "Definition", "Page"]]
        rows.extend([term.term, term.definition, f"p.{term.page}"] for term in terms)
        return ExportDocument(
            title=f"Glossary - {document.title}",
            blocks=[
                ExportBlock(kind="heading", text="Glossary"),
                ExportBlock(kind="table", rows=rows),
            ],
        )
    return ExportDocument(title=title, blocks=_markdown_blocks(markdown))


def _summary_export(db: Session, *, owner_id: int, summary_id: int) -> ExportDocument:
    summary = db.scalar(
        select(DocumentSummary).where(
            DocumentSummary.id == summary_id,
            DocumentSummary.owner_id == owner_id,
        )
    )
    if summary is None:
        raise LookupError("Study material not found.")
    document = db.scalar(
        select(Document).where(
            Document.id == summary.document_id,
            Document.owner_id == owner_id,
        )
    )
    title = f"Summary - {document.title}" if document else "Document Summary"
    blocks = _markdown_blocks(summary.content)
    if summary.page_start is not None and summary.page_end is not None:
        blocks.insert(
            0,
            ExportBlock(
                kind="paragraph",
                text=f"Pages {summary.page_start}-{summary.page_end}",
            ),
        )
    return ExportDocument(title=title, blocks=blocks)


def _plan_export(db: Session, *, owner_id: int, plan_id: int) -> ExportDocument:
    plan = db.scalar(
        select(StudyPlan).where(
            StudyPlan.id == plan_id,
            StudyPlan.owner_id == owner_id,
        )
    )
    if plan is None:
        raise LookupError("Study material not found.")
    document_titles = {
        document.id: document.title
        for document in db.scalars(
            select(Document).where(
                Document.owner_id == owner_id,
                Document.id.in_(plan.document_ids or []),
            )
        )
    }
    items = list(
        db.scalars(
            select(StudyPlanItem)
            .where(StudyPlanItem.plan_id == plan.id)
            .order_by(StudyPlanItem.scheduled_date, StudyPlanItem.id)
        )
    )
    rows = [["Date", "Activity", "Topic", "Minutes", "Source pages"]]
    for item in items:
        pages = (
            f"{document_titles[item.document_id]} pp.{item.page_start}-{item.page_end}"
            if item.document_id in document_titles
            and item.page_start is not None
            and item.page_end is not None
            else ""
        )
        rows.append(
            [
                item.scheduled_date.isoformat(),
                item.activity_type.replace("_", " ").title(),
                item.topic,
                str(item.minutes),
                pages,
            ]
        )
    blocks = [
        ExportBlock(
            kind="paragraph",
            text=(
                f"Exam date: {plan.exam_date.isoformat()} | "
                f"Daily target: {plan.daily_minutes} minutes"
            ),
        ),
        ExportBlock(kind="table", rows=rows),
    ]
    if plan.omitted_topics:
        blocks.append(ExportBlock(kind="heading", text="Omitted Topics", level=2))
        blocks.extend(
            ExportBlock(
                kind="bullet",
                text=(
                    f"{topic.get('topic', 'Topic')} "
                    f"[pp.{topic.get('page_start', '?')}-"
                    f"{topic.get('page_end', '?')}]"
                ),
            )
            for topic in plan.omitted_topics
        )
    return ExportDocument(title="Study Plan", blocks=blocks)


def _quiz_export(
    db: Session,
    *,
    owner_id: int,
    quiz_id: int,
    include_answers: bool,
) -> ExportDocument:
    quiz = db.scalar(select(Quiz).where(Quiz.id == quiz_id, Quiz.owner_id == owner_id))
    if quiz is None:
        raise LookupError("Study material not found.")
    questions = list(
        db.scalars(
            select(Question).where(Question.quiz_id == quiz.id).order_by(Question.id)
        )
    )
    sections: dict[str, list[Question]] = {}
    for question in questions:
        sections.setdefault(question.type.replace("_", " ").title(), []).append(
            question
        )
    export_sections: dict[str, list[dict[str, Any]]] = {}
    for section, section_questions in sections.items():
        export_sections[section] = []
        for question in section_questions:
            options = question.options
            if isinstance(options, dict):
                choices = options.get("choices", [])
            elif isinstance(options, list):
                choices = options
            else:
                choices = []
            marks = options.get("marks", 1) if isinstance(options, dict) else 1
            if not isinstance(marks, int) or marks < 1:
                marks = 1
            export_sections[section].append(
                {
                    "question": f"{question.prompt} [p.{question.page}]",
                    "options": [
                        choice for choice in choices if isinstance(choice, str)
                    ],
                    "correct_answer": f"{question.answer} [p.{question.page}]",
                    "explanation": question.explanation or "",
                    "marks": marks,
                }
            )
    report = quiz.generation_report if isinstance(quiz.generation_report, dict) else {}
    default_marks = report.get("marks_per_question", 1)
    if not isinstance(default_marks, int) or default_marks < 1:
        default_marks = 1
    from app.services.quiz.exam_export import build_exam_document

    return build_exam_document(
        quiz.title,
        export_sections,
        default_marks,
        include_answers=include_answers,
    )


def _safe_filename(title: str, extension: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", title).strip("-.")[:100]
    return f"{stem or 'study-material'}.{extension}"


def _pdf_safe_text(text: str) -> tuple[str, bool]:
    sanitized: list[str] = []
    replaced = False
    for character in text:
        try:
            if ord(character) < 32 and character not in "\n\r\t":
                raise UnicodeEncodeError("cp1252", character, 0, 1, "control")
            character.encode("cp1252")
        except UnicodeEncodeError:
            sanitized.append("[?]")
            replaced = True
        else:
            sanitized.append(character)
    return "".join(sanitized), replaced


def _paragraph_text(text: str, *, pdf: bool = False) -> tuple[str, bool]:
    from xml.sax.saxutils import escape

    safe_text, replaced = _pdf_safe_text(text) if pdf else (text, False)
    return escape(safe_text).replace("\n", "<br/>"), replaced


def export_pdf(document: ExportDocument) -> bytes:
    """Render a paginated PDF in memory using ReportLab."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    output = BytesIO()
    pdf = SimpleDocTemplate(
        output,
        pagesize=letter,
        title=document.title,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=0.65 * inch,
        bottomMargin=0.65 * inch,
    )
    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "ExportBody", parent=styles["BodyText"], alignment=TA_LEFT, leading=14
    )
    table_style = ParagraphStyle(
        "ExportTable", parent=body_style, fontSize=8, leading=10
    )
    story = []
    replaced = False

    def paragraph(text: str, style: ParagraphStyle) -> Paragraph:
        nonlocal replaced
        safe_text, was_replaced = _paragraph_text(text, pdf=True)
        replaced = replaced or was_replaced
        return Paragraph(safe_text, style)

    story.append(paragraph(document.title, styles["Title"]))
    story.append(Spacer(1, 8))
    for block in document.blocks:
        if block.kind == "heading":
            story.append(paragraph(block.text, styles[f"Heading{block.level}"]))
        elif block.kind == "bullet":
            story.append(paragraph(f"- {block.text}", body_style))
        elif block.kind == "table":
            rows = [
                [paragraph(cell, table_style) for cell in row] for row in block.rows
            ]
            if rows:
                column_width = pdf.width / len(rows[0])
                table = Table(
                    rows,
                    colWidths=[column_width] * len(rows[0]),
                    repeatRows=1,
                    hAlign="LEFT",
                )
                table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF7")),
                            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 5),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                            ("TOPPADDING", (0, 0), (-1, -1), 4),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                        ]
                    )
                )
                story.append(table)
                story.append(Spacer(1, 6))
        else:
            story.append(paragraph(block.text, body_style))
            story.append(Spacer(1, 4))
    if replaced:
        story.append(
            paragraph(
                "Note: PDF font limitations replaced unsupported characters with [?].",
                body_style,
            )
        )
    pdf.build(story)
    return output.getvalue()


def export_docx(document: ExportDocument) -> bytes:
    """Render a Unicode-preserving DOCX in memory using python-docx."""
    from docx import Document as WordDocument

    word_document = WordDocument()
    word_document.add_heading(document.title, level=0)
    for block in document.blocks:
        if block.kind == "heading":
            word_document.add_heading(block.text, level=min(block.level, 3))
        elif block.kind == "bullet":
            word_document.add_paragraph(block.text, style="List Bullet")
        elif block.kind == "table":
            if block.rows:
                table = word_document.add_table(
                    rows=1, cols=len(block.rows[0]), style="Table Grid"
                )
                for cell, text in zip(table.rows[0].cells, block.rows[0], strict=True):
                    cell.text = text
                for row in block.rows[1:]:
                    cells = table.add_row().cells
                    for cell, text in zip(cells, row, strict=True):
                        cell.text = text
        else:
            word_document.add_paragraph(block.text)
    output = BytesIO()
    word_document.save(output)
    return output.getvalue()


def generate_export(
    db: Session,
    *,
    owner_id: int,
    kind: str,
    item_id: int,
    format: str,
    page_start: int | None = None,
    page_end: int | None = None,
    include_answers: bool = False,
) -> tuple[bytes, str, str]:
    """Load an owned study item and return in-memory bytes, MIME type and name."""
    normalized_kind = kind.casefold().replace("_", "-")
    if normalized_kind == "summaries":
        normalized_kind = "summary"
    if normalized_kind in {"study-plan", "plans"}:
        normalized_kind = "plan"
    if normalized_kind not in {
        "notes",
        "cheat-sheet",
        "summary",
        "glossary",
        "plan",
        "quiz",
        "exam",
        "flashcards",
    }:
        raise ValueError("Unknown export kind.")
    if format not in {"pdf", "docx", "csv"}:
        raise ValueError("Unknown export format.")
    if normalized_kind == "flashcards":
        if format != "csv":
            raise ValueError("Flashcards can only be exported as CSV.")
        document = _owned_document(db, item_id, owner_id)
        cards = list(
            db.scalars(
                select(Flashcard)
                .where(
                    Flashcard.document_id == document.id,
                    Flashcard.owner_id == owner_id,
                )
                .order_by(Flashcard.id)
            )
        )
        csv_buffer = StringIO(newline="")
        writer = csv.writer(csv_buffer)
        writer.writerow(["front", "back", "page"])
        writer.writerows(
            [card.front, card.back, card.source_page or ""] for card in cards
        )
        return (
            csv_buffer.getvalue().encode("utf-8"),
            CSV_MEDIA_TYPE,
            _safe_filename(document.title + "-flashcards", "csv"),
        )
    if format == "csv":
        raise ValueError("CSV export is only available for flashcards.")

    if normalized_kind in {"notes", "cheat-sheet", "glossary"}:
        content = _document_export(
            db,
            owner_id=owner_id,
            kind=normalized_kind,
            item_id=item_id,
            page_start=page_start,
            page_end=page_end,
        )
    elif normalized_kind == "summary":
        content = _summary_export(db, owner_id=owner_id, summary_id=item_id)
    elif normalized_kind == "plan":
        content = _plan_export(db, owner_id=owner_id, plan_id=item_id)
    else:
        content = _quiz_export(
            db,
            owner_id=owner_id,
            quiz_id=item_id,
            include_answers=include_answers or normalized_kind == "exam",
        )

    if format == "pdf":
        return export_pdf(content), PDF_MEDIA_TYPE, _safe_filename(content.title, "pdf")
    return export_docx(content), DOCX_MEDIA_TYPE, _safe_filename(content.title, "docx")


def content_disposition(filename: str) -> str:
    """Build a safe attachment header with an ASCII fallback and UTF-8 name."""
    fallback = re.sub(r"[^A-Za-z0-9._-]", "-", filename) or "study-material"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"
