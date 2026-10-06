"""PDF validation and page-oriented ingestion."""

from io import BytesIO
from statistics import median
from typing import Any

import pdfplumber
import pymupdf
import pytesseract
from PIL import Image
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Document, DocumentPage, DocumentStatusEvent
from app.nlp.preprocessing import normalize_text
from app.services.file_storage import FileStorage


class InvalidPDFError(ValueError):
    """A PDF upload is empty, malformed, encrypted, or exceeds configured limits."""


class UnsupportedPDFError(InvalidPDFError):
    """The uploaded content does not identify itself as a PDF."""


class PDFPageLimitError(InvalidPDFError):
    """The uploaded PDF exceeds the configured page limit."""


def _record_state(
    db: Session,
    document: Document,
    status: str,
    progress: int,
    error_message: str | None = None,
) -> None:
    document.status = status
    document.progress = progress
    document.error_message = error_message
    db.add(
        DocumentStatusEvent(
            document_id=document.id,
            status=status,
            progress=progress,
            error_message=error_message,
        )
    )
    db.commit()


def inspect_pdf(content: bytes, max_pages: int) -> int:
    """Verify PDF content and encryption, then return its page count."""
    if not content:
        raise InvalidPDFError("The uploaded PDF is empty.")
    if b"%PDF-" not in content[:1024]:
        raise UnsupportedPDFError("The uploaded file is not a valid PDF.")
    try:
        with pymupdf.open(stream=content, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise InvalidPDFError("Encrypted PDFs are not supported.")
            page_count = pdf.page_count
            if page_count < 1:
                raise InvalidPDFError("The PDF contains no pages.")
            if page_count > max_pages:
                raise PDFPageLimitError(
                    f"The PDF has {page_count} pages; the limit is {max_pages}."
                )
            return page_count
    except InvalidPDFError:
        raise
    except (pymupdf.FileDataError, RuntimeError, ValueError) as error:
        raise InvalidPDFError("The uploaded PDF is corrupt or unreadable.") from error


def sanitize_filename(filename: str) -> str:
    """Strip path components, control characters, and header-sensitive characters."""
    basename = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    cleaned = "".join(
        character
        for character in basename
        if character.isprintable() and character not in {'"', "'", "\r", "\n"}
    )
    cleaned = cleaned.strip(" .")
    return (cleaned or "document.pdf")[:255]


def _extract_headings(page: pymupdf.Page) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    sizes: list[float] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            text = "".join(span["text"] for span in line["spans"]).strip()
            if not text:
                continue
            size = max(float(span["size"]) for span in line["spans"])
            bold = any(
                bool(span["flags"] & 16) or "bold" in span["font"].lower()
                for span in line["spans"]
            )
            spans.append({"text": text, "font_size": size, "bold": bold})
            sizes.append(size)

    if not sizes:
        return []
    body_size = median(sizes)
    return [
        span
        for span in spans
        if span["font_size"] >= max(body_size * 1.2, body_size + 1.5)
        or (span["bold"] and span["font_size"] >= body_size)
    ]


def _render_table_text(tables: list[list[list[str | None]]]) -> str:
    rendered: list[str] = []
    for index, table in enumerate(tables, start=1):
        rows = [
            " | ".join((cell or "").strip() for cell in row)
            for row in table
            if any(cell and cell.strip() for cell in row)
        ]
        if rows:
            rendered.append(f"[Table {index}]\n" + "\n".join(rows))
    return "\n\n".join(rendered)


def _ocr_page(page: pymupdf.Page) -> str:
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    return pytesseract.image_to_string(image).strip()


def ingest_document(
    document_id: int,
    db: Session,
    file_storage: FileStorage,
) -> None:
    """Extract page text, headings, tables, and OCR into persistent page records."""
    document = db.get(Document, document_id)
    if document is None:
        raise ValueError(f"Document {document_id} no longer exists.")
    if document.storage_key is None:
        raise ValueError("The document has no stored PDF file.")

    try:
        _record_state(db, document, "extracting", 5)

        content = file_storage.get(document.storage_key)
        with pymupdf.open(stream=content, filetype="pdf") as pdf:
            document.page_count = pdf.page_count
            extracted = [
                {
                    "text": page.get_text("text").strip(),
                    "headings": _extract_headings(page),
                }
                for page in pdf
            ]
            db.commit()

            _record_state(db, document, "processing", 40)

            db.execute(
                delete(DocumentPage).where(DocumentPage.document_id == document_id)
            )
            db.commit()
            with pdfplumber.open(BytesIO(content)) as table_pdf:
                total_pages = len(extracted)
                for index, (pdf_page, page_data) in enumerate(
                    zip(table_pdf.pages, extracted, strict=True), start=1
                ):
                    tables = [
                        [[cell for cell in row] for row in table]
                        for table in (pdf_page.extract_tables() or [])
                    ]
                    text = page_data["text"]
                    ocr_status = "not_needed"
                    if len("".join(text.split())) < 40:
                        try:
                            ocr_text = _ocr_page(pdf[index - 1])
                            if ocr_text:
                                text = "\n".join(
                                    part for part in (text, ocr_text) if part
                                )
                                ocr_status = "completed"
                            else:
                                ocr_status = "no_text_found"
                        except pytesseract.TesseractNotFoundError:
                            ocr_status = "ocr_unavailable"

                    table_text = _render_table_text(tables)
                    if table_text:
                        text = "\n\n".join(part for part in (text, table_text) if part)

                    db.add(
                        DocumentPage(
                            document_id=document_id,
                            page_number=index,
                            text=text,
                            cleaned_text=normalize_text(text),
                            headings=page_data["headings"],
                            tables=tables,
                            ocr_status=ocr_status,
                        )
                    )
                    _record_state(
                        db,
                        document,
                        "processing",
                        40 + round(index / total_pages * 40),
                    )

        _record_state(db, document, "indexing", 90)
        _record_state(db, document, "ready", 100)
    except Exception as error:
        db.rollback()
        failed_document = db.scalar(select(Document).where(Document.id == document_id))
        if failed_document is not None:
            _record_state(
                db,
                failed_document,
                "failed",
                100,
                f"Ingestion failed: {error}",
            )
        raise
