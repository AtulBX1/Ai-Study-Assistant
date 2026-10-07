"""Sentence-aware chunking tests."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import Chunk, Document, DocumentPage, User
from app.services.chunking import create_chunks, rebuild_document_chunks


def _page(
    number: int,
    text: str,
    headings: list[dict[str, str]] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(page_number=number, text=text, headings=headings or [])


def test_chunks_respect_sentences_overlap_and_metadata() -> None:
    pages = [
        _page(
            1,
            "Course Overview\nAlpha beta gamma delta. Epsilon zeta eta theta.",
            [{"text": "Course Overview"}],
        ),
        _page(2, "Iota kappa lambda mu."),
    ]

    chunks = create_chunks(17, pages, chunk_size=10, overlap=5)

    assert len(chunks) == 2
    assert chunks[0].text == "Alpha beta gamma delta. Epsilon zeta eta theta."
    assert chunks[1].text == "Epsilon zeta eta theta. Iota kappa lambda mu."
    assert [chunk.chunk_index for chunk in chunks] == [0, 1]
    assert (chunks[0].document_id, chunks[0].page_start, chunks[0].page_end) == (
        17,
        1,
        1,
    )
    assert chunks[1].page_start == 1
    assert chunks[1].page_end == 2
    assert chunks[0].section_title == "Course Overview"
    assert all(chunk.token_count <= 10 for chunk in chunks)


def test_long_sentence_splits_only_between_tokens() -> None:
    text = " ".join(f"word{index}" for index in range(11))

    chunks = create_chunks(1, [_page(1, text)], chunk_size=4, overlap=0)

    assert len(chunks) == 3
    assert [chunk.token_count for chunk in chunks] == [4, 4, 3]
    assert " ".join(chunk.text for chunk in chunks) == text
    assert all(chunk.text.split() for chunk in chunks)


@pytest.mark.parametrize(
    ("chunk_size", "overlap"),
    [(0, 0), (10, -1), (10, 10)],
)
def test_invalid_chunk_size_and_overlap_are_rejected(
    chunk_size: int, overlap: int
) -> None:
    with pytest.raises(ValueError):
        create_chunks(1, [], chunk_size, overlap)


def test_rechunk_replaces_persisted_chunks(db_session) -> None:
    user = User(
        email="chunk-owner@example.com",
        full_name="Chunk Owner",
        password_hash="unused",
    )
    db_session.add(user)
    db_session.flush()
    document = Document(owner_id=user.id, title="Notes", status="ready")
    db_session.add(document)
    db_session.flush()
    db_session.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            text=(
                "First sentence has several words. Second sentence has several words."
            ),
            headings=[],
        )
    )
    db_session.commit()

    first_chunks = rebuild_document_chunks(db_session, document.id, 20, 0)
    db_session.commit()
    old_ids = {chunk.id for chunk in first_chunks}
    smaller_chunks = rebuild_document_chunks(db_session, document.id, 5, 0)
    db_session.commit()

    assert len(smaller_chunks) > len(old_ids)
    assert [chunk.chunk_index for chunk in smaller_chunks] == list(
        range(len(smaller_chunks))
    )
    assert all(chunk.token_count <= 5 for chunk in smaller_chunks)
    assert len(
        list(db_session.scalars(select(Chunk).where(Chunk.doc_id == document.id)))
    ) == len(smaller_chunks)
