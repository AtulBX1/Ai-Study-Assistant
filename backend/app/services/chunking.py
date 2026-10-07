"""Sentence- and section-aware chunk creation and persistence."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Chunk, DocumentPage
from app.nlp.preprocessing import normalize_text, regex_tokenize, sentence_segmentation

DEFAULT_CHUNK_SIZE = 400
DEFAULT_OVERLAP = 50
_WORD_PATTERN = re.compile(r"\S+")


@dataclass(frozen=True)
class ChunkContent:
    """Text plus its document, page, section, and ordering metadata."""

    document_id: int
    page_start: int
    page_end: int
    section_title: str | None
    chunk_index: int
    token_count: int
    text: str


@dataclass(frozen=True)
class _Sentence:
    text: str
    page: int
    section: str | None


def count_tokens(text: str) -> int:
    """Count lexical tokens with the Step 4 Unicode tokenizer."""
    return len(regex_tokenize(text))


def _split_long_sentence(sentence: str, limit: int) -> list[str]:
    words = _WORD_PATTERN.findall(sentence)
    pieces: list[str] = []
    current: list[str] = []
    for word in words:
        candidate = " ".join((*current, word))
        if current and count_tokens(candidate) > limit:
            pieces.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        pieces.append(" ".join(current))
    return pieces


def _sentences_for_page(
    page: DocumentPage, section: str | None
) -> tuple[list[_Sentence], str | None]:
    heading_names = {
        normalize_text(str(heading.get("text", "")))
        for heading in (page.headings or [])
        if heading.get("text")
    }
    sentences: list[_Sentence] = []
    for paragraph in re.split(r"\n\s*\n", page.text):
        for line in paragraph.splitlines():
            line = line.strip()
            if not line:
                continue
            if normalize_text(line.lstrip("# ").strip()) in heading_names:
                section = line.lstrip("# ").strip()[:255]
                continue
            for sentence in sentence_segmentation(line):
                if sentence:
                    sentences.append(_Sentence(sentence, page.page_number, section))
    return sentences, section


def create_chunks(
    document_id: int,
    pages: Sequence[DocumentPage],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[ChunkContent]:
    """Pack whole sentences into bounded chunks while retaining sentence overlap."""
    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1.")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size.")

    units: list[_Sentence] = []
    section: str | None = None
    for page in pages:
        page_sentences, section = _sentences_for_page(page, section)
        units.extend(
            _Sentence(piece, sentence.page, sentence.section)
            for sentence in page_sentences
            for piece in _split_long_sentence(sentence.text, chunk_size)
        )
    if not units:
        return []

    chunks: list[ChunkContent] = []
    current: list[_Sentence] = []

    def emit() -> None:
        if not current:
            return
        text = " ".join(unit.text for unit in current)
        chunks.append(
            ChunkContent(
                document_id=document_id,
                page_start=min(unit.page for unit in current),
                page_end=max(unit.page for unit in current),
                section_title=current[0].section,
                chunk_index=len(chunks),
                token_count=count_tokens(text),
                text=text,
            )
        )

    for unit in units:
        if current and unit.section != current[-1].section:
            emit()
            current = []
        candidate_count = count_tokens(
            " ".join(sentence.text for sentence in (*current, unit))
        )
        if current and candidate_count > chunk_size:
            emit()
            previous = current
            current = []
            overlap_tokens = 0
            for sentence in reversed(previous):
                sentence_tokens = count_tokens(sentence.text)
                if overlap_tokens + sentence_tokens > overlap:
                    break
                current.insert(0, sentence)
                overlap_tokens += sentence_tokens
            while (
                current
                and count_tokens(
                    " ".join(sentence.text for sentence in (*current, unit))
                )
                > chunk_size
            ):
                current.pop(0)
        current.append(unit)
    emit()
    return chunks


def rebuild_document_chunks(
    db: Session,
    document_id: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[Chunk]:
    """Replace stored chunks using the requested settings and return them."""
    pages = list(
        db.scalars(
            select(DocumentPage)
            .where(DocumentPage.document_id == document_id)
            .order_by(DocumentPage.page_number)
        )
    )
    content = create_chunks(document_id, pages, chunk_size, overlap)
    db.execute(delete(Chunk).where(Chunk.doc_id == document_id))
    chunks = [
        Chunk(
            doc_id=chunk.document_id,
            page=chunk.page_start,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            section=chunk.section_title,
            text=chunk.text,
            token_count=chunk.token_count,
            chunk_index=chunk.chunk_index,
        )
        for chunk in content
    ]
    db.add_all(chunks)
    db.flush()
    return chunks
