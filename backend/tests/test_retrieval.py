"""Classical retrieval relevance, registry, and cache tests."""

from app.retrieval import ChunkRecord, get_retriever


def _fixture_chunks() -> list[ChunkRecord]:
    return [
        ChunkRecord(
            chunk_id=1,
            document_id=10,
            text="Photosynthesis uses chlorophyll to convert sunlight into energy.",
            page_start=1,
            page_end=1,
            section="Biology",
        ),
        ChunkRecord(
            chunk_id=2,
            document_id=10,
            text="Volcanoes release magma, ash, and gases during an eruption.",
            page_start=2,
            page_end=2,
            section="Geology",
        ),
        ChunkRecord(
            chunk_id=3,
            document_id=11,
            text="Chlorophyll is a green pigment found in plants.",
            page_start=4,
            page_end=4,
            section="Plants",
        ),
    ]


def test_tfidf_retriever_ranks_relevant_chunk_and_filters_documents() -> None:
    retriever = get_retriever("tfidf", user_id=101, chunks=_fixture_chunks())

    results = retriever.retrieve("chlorophyll sunlight photosynthesis", [10], 2)

    assert results[0].chunk_id == 1
    assert results[0].document_id == 10
    assert results[0].page == 1
    assert results[0].section == "Biology"
    assert results[0].rank == 1
    assert all(result.document_id == 10 for result in results)


def test_bm25_retriever_ranks_relevant_chunk() -> None:
    retriever = get_retriever("bm25", user_id=102, chunks=_fixture_chunks())

    results = retriever.retrieve("chlorophyll sunlight photosynthesis", [10], 2)

    assert results
    assert results[0].chunk_id == 1
    assert results[0].score > 0


def test_retriever_cache_is_user_isolated_and_rebuilds_when_content_changes() -> None:
    chunks = _fixture_chunks()
    first = get_retriever("tfidf", user_id=103, chunks=chunks)
    same_user = get_retriever("tfidf", user_id=103, chunks=chunks)
    another_user = get_retriever("tfidf", user_id=104, chunks=chunks)
    updated = get_retriever(
        "tfidf",
        user_id=103,
        chunks=[*chunks, ChunkRecord(4, "new retrieval text", 10, 3, 3)],
    )

    assert first is same_user
    assert first is not another_user
    assert updated is not first
