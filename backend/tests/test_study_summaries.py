"""Acceptance tests for Step 13a-2: summaries, notes, and cheat sheets."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.models import (
    Document,
    DocumentPage,
    GlossaryTerm,
    User,
)
from app.services.rag.providers import RateLimitError
from app.services.study.summaries import (
    extract_sections,
    generate_document_summary,
    is_content_chunk,
    split_sentences,
    summarize_extractive,
)
from tests.conftest import access_token_for


@pytest.fixture(autouse=True)
def mock_missing_t5_weights(monkeypatch, tmp_path):
    """Ensure tests are strictly fake-only without loading real model weights."""
    dummy_dir = tmp_path / "fake_t5_weights"
    monkeypatch.setattr("app.services.study.summaries.T5_WEIGHTS_DIR", dummy_dir)


def _user(db_session, name: str) -> User:
    user = User(
        email=f"{name}@example.test",
        full_name=name,
        password_hash="unused",
    )
    db_session.add(user)
    db_session.flush()
    return user


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token_for(user.id)}"}


def _document(
    db_session,
    owner: User,
    title: str = "NLP Foundations",
    is_private: bool = False,
) -> Document:
    document = Document(
        owner_id=owner.id,
        title=title,
        status="ready",
        is_private=is_private,
    )
    db_session.add(document)
    db_session.flush()
    return document


class FakeSummaryLLMProvider:
    """Mock LLM provider returning predefined bullet points."""

    def __init__(
        self,
        name: str = "fake_llm",
        response_text: str = "",
        is_external: bool = True,
    ) -> None:
        self.name = name
        self.response_text = response_text
        self.is_external = is_external
        self.call_count = 0
        self.prompts: list[str] = []

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        self.call_count += 1
        self.prompts.append(prompt)
        return self.response_text

    def stream(self, prompt: str, system_prompt: str | None = None) -> Iterator[str]:
        self.call_count += 1
        self.prompts.append(prompt)
        yield self.response_text


class FlakyRateLimitingLLMProvider:
    """Provider that succeeds once, then raises RateLimitError."""

    def __init__(self, name: str = "flaky_llm", is_external: bool = True) -> None:
        self.name = name
        self.is_external = is_external
        self.call_count = 0

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        self.call_count += 1
        if self.call_count == 1:
            return (
                "- Point: Language models assign probabilities to token sequences. | "
                "Evidence: Language models assign probabilities to sequences of words."
            )
        raise RateLimitError("Mock 429 rate limit exceeded", retry_after_seconds=5)


# ACCEPTANCE TEST 1
def test_extractive_summary_verbatim_and_source_order(client, db_session):
    """1. With no model and no provider, the extractive engine returns a summary
    whose sentences all appear in the source text and are in source order.
    """
    owner = _user(db_session, "extractive-user")
    doc = _document(db_session, owner)

    s1 = (
        "Natural language processing combines computational linguistics with "
        "statistical models."
    )
    s2 = "Tokenization breaks a sequence of characters into meaningful syntactic units."
    s3 = (
        "Word representations map discrete vocabulary tokens into continuous "
        "vector spaces."
    )
    s4 = (
        "Transformers rely entirely on self-attention mechanisms to compute "
        "representations."
    )
    s5 = (
        "Evaluation metrics like BLEU and ROUGE quantify n-gram overlap "
        "against references."
    )

    db_session.add_all(
        [
            DocumentPage(document_id=doc.id, page_number=1, text=f"{s1} {s2} {s3}"),
            DocumentPage(document_id=doc.id, page_number=2, text=f"{s4} {s5}"),
        ]
    )
    db_session.commit()

    response = client.post(
        f"/study/documents/{doc.id}/summaries",
        headers=_headers(owner),
        json={"summary_type": "short", "engine": "extractive"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["engine_used"] == "extractive"

    all_source_text = f"{s1} {s2} {s3} {s4} {s5}"
    items = data["items"]
    assert 3 <= len(items) <= 5

    # Check that every sentence appears verbatim in the source text
    last_position = -1
    for item in items:
        sentence = item["text"]
        assert sentence in all_source_text
        # Verify source order
        pos = all_source_text.find(sentence)
        assert pos > last_position
        last_position = pos


def test_extractive_summary_keeps_lowercase_prose_and_skips_fragments():
    sentence = "tokenization separates a stream of text into meaningful language units."
    items = summarize_extractive(
        [(21, f"- Tokenization\nbroken <num> .\n{sentence}")],
        target_sentences=3,
    )
    assert [item["text"] for item in items] == [sentence]
    assert items[0]["page_start"] == items[0]["page_end"] == 21


def test_sentence_splitter_preserves_initials_in_source_sentences():
    sentences = split_sentences(
        'The question is "who wrote Harry Potter?" '
        'A language model can answer "J.K. Rowling." '
        "It can also cite the source."
    )
    assert len(sentences) == 3
    assert '"J.K. Rowling."' in sentences[1]


# ACCEPTANCE TEST 2
def test_t5_with_missing_weights_falls_back_to_extractive(
    client, db_session, monkeypatch, tmp_path
):
    """2. Requesting 't5' with missing weights falls back to extractive and says so."""
    owner = _user(db_session, "t5-fallback-user")
    doc = _document(db_session, owner)

    text = (
        "Statistical language models predict the next token given context. "
        "Recurrent neural networks process sequential data with hidden states. "
        "Gated units introduce reset and update gates to reduce vanishing gradients. "
        "Self-attention allows direct modeling regardless of token distance."
    )
    db_session.add(DocumentPage(document_id=doc.id, page_number=1, text=text))
    db_session.commit()

    # Point weights dir to a guaranteed missing path
    missing_dir = tmp_path / "nonexistent_t5_weights"
    monkeypatch.setattr("app.services.study.summaries.T5_WEIGHTS_DIR", missing_dir)

    response = client.post(
        f"/study/documents/{doc.id}/summaries",
        headers=_headers(owner),
        json={"summary_type": "short", "engine": "t5"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["engine_requested"] == "t5"
    assert data["engine_used"] == "extractive"
    assert "T5 weights not found" in data["fallback_reason"]
    assert "falling back to extractive engine" in data["fallback_reason"]


# ACCEPTANCE TEST 3
def test_llm_bullet_grounding_rejects_hallucinations(db_session):
    """3. An LLM bullet with missing evidence is rejected; valid is kept."""
    owner = _user(db_session, "llm-grounding-user")
    doc = _document(db_session, owner)

    valid_sentence = (
        "The attention mechanism enables the model to focus on relevant tokens."
    )
    section_text = (
        f"{valid_sentence} Positional encodings provide sequence ordering. "
        "Feedforward sublayers apply transformations across all positions."
    )
    db_session.add(DocumentPage(document_id=doc.id, page_number=1, text=section_text))
    db_session.commit()

    llm_output = (
        f"- Point: Attention allows focusing. | Evidence: {valid_sentence}\n"
        "- Point: Quantum powers attention. | Evidence: Quantum superposition."
    )
    fake_provider = FakeSummaryLLMProvider(response_text=llm_output)

    summary = generate_document_summary(
        db_session,
        document=doc,
        summary_type="detailed",
        engine="llm",
        provider=fake_provider,
    )

    items = summary.items
    # Exactly one item kept (the valid one)
    assert len(items) == 1
    assert items[0]["text"] == "Attention allows focusing."
    assert items[0]["evidence_sentence"] == valid_sentence
    assert items[0]["engine"] == "llm"


def test_llm_engine_uses_the_configured_provider_chain(db_session, monkeypatch):
    owner = _user(db_session, "provider-chain-user")
    doc = _document(db_session, owner)
    evidence = "Language models estimate token probabilities from context."
    db_session.add(DocumentPage(document_id=doc.id, page_number=1, text=evidence))
    db_session.commit()
    provider = FakeSummaryLLMProvider(
        response_text=(
            f"- Point: Models estimate token probabilities. | Evidence: {evidence}"
        )
    )

    class FakePipeline:
        def __init__(self, *, settings):
            self.provider = provider

    monkeypatch.setattr(
        "app.services.rag.pipeline.RAGChatPipeline",
        FakePipeline,
    )
    summary = generate_document_summary(
        db_session,
        document=doc,
        summary_type="short",
        engine="llm",
    )

    assert provider.call_count == 1
    assert summary.engine_used == "llm"
    assert summary.items[0]["engine"] == "llm"
    assert summary.items[0]["page_start"] == 1


# ACCEPTANCE TEST 4
def test_rate_limited_provider_returns_partial_plus_fallback_without_loop(db_session):
    """4. A rate-limited provider returns partial result plus fallback."""
    owner = _user(db_session, "rate-limit-user")
    doc = _document(db_session, owner)

    s1 = "Language models assign probabilities to sequences of words."
    s2 = "N-gram models approximate probabilities using the Markov assumption."
    s3 = "Vector embeddings capture semantic relationships between words."
    s4 = "Skip-gram architectures predict context words given a center word."

    db_session.add_all(
        [
            DocumentPage(
                document_id=doc.id,
                page_number=1,
                text=f"{s1} {s2}",
                headings=[{"text": "Section 1: Language Modeling"}],
            ),
            DocumentPage(
                document_id=doc.id,
                page_number=2,
                text=f"{s3} {s4}",
                headings=[{"text": "Section 2: Word Embeddings"}],
            ),
        ]
    )
    db_session.commit()

    provider = FlakyRateLimitingLLMProvider()
    summary = generate_document_summary(
        db_session,
        document=doc,
        summary_type="detailed",
        engine="llm",
        provider=provider,
    )

    assert provider.call_count == 2
    assert summary.engine_requested == "llm"
    assert summary.engine_used == "hybrid"
    assert "rate limited" in summary.fallback_reason.lower()

    # Section 1 should have LLM items; Section 2 should have fallen back to extractive
    sec1_items = [it for it in summary.items if it["engine"] == "llm"]
    sec2_items = [it for it in summary.items if it["engine"] == "extractive"]
    assert len(sec1_items) >= 1
    assert len(sec2_items) >= 1
    assert (
        sec1_items[0]["text"]
        == "Language models assign probabilities to token sequences."
    )


def test_detailed_and_chapter_summaries_keep_section_page_ranges(db_session):
    owner = _user(db_session, "section-summary-user")
    doc = _document(db_session, owner)
    first = "Statistical language models estimate token probabilities from context."
    second = "Word embeddings represent semantic relationships in continuous spaces."
    db_session.add_all(
        [
            DocumentPage(
                document_id=doc.id,
                page_number=3,
                text=first,
                headings=[{"text": "Language Models"}],
            ),
            DocumentPage(
                document_id=doc.id,
                page_number=7,
                text=second,
                headings=[{"text": "Word Embeddings"}],
            ),
        ]
    )
    db_session.commit()

    detailed = generate_document_summary(
        db_session,
        document=doc,
        summary_type="detailed",
        engine="extractive",
    )
    chapter_wise = generate_document_summary(
        db_session,
        document=doc,
        summary_type="chapter_wise",
        engine="extractive",
    )

    assert [item["page_start"] for item in detailed.items] == [3, 7]
    assert [item["page_end"] for item in detailed.items] == [3, 7]
    assert {item["engine"] for item in detailed.items} == {"extractive"}
    assert [item["title"] for item in chapter_wise.items] == [
        "Language Models",
        "Word Embeddings",
    ]
    assert [(item["page_start"], item["page_end"]) for item in chapter_wise.items] == [
        (3, 3),
        (7, 7),
    ]


# ACCEPTANCE TEST 5
def test_private_document_never_calls_external_provider(db_session):
    """5. Private-document requests never call the external provider."""
    owner = _user(db_session, "private-doc-user")
    doc = _document(db_session, owner, is_private=True)

    text = (
        "Internal company confidential notes regarding architecture design. "
        "Microservices communicate via gRPC with mutual TLS authentication. "
        "Database migrations execute automatically during blue-green deployment. "
        "All telemetry data is anonymized before ingestion into monitoring."
    )
    db_session.add(DocumentPage(document_id=doc.id, page_number=1, text=text))
    db_session.commit()

    external_provider = FakeSummaryLLMProvider(is_external=True)

    summary = generate_document_summary(
        db_session,
        document=doc,
        summary_type="short",
        engine="llm",
        provider=external_provider,
    )

    # Provider MUST NEVER be called for private documents
    assert external_provider.call_count == 0
    assert summary.engine_used == "extractive"
    assert "Private document cannot be sent" in summary.fallback_reason


# ACCEPTANCE TEST 6
def test_sections_headings_and_10_page_blocks_and_skip_outline(db_session):
    """6. Sections: headings used when present, otherwise 10-page blocks."""
    owner = _user(db_session, "sections-user")
    doc = _document(db_session, owner)

    # Part A: Heading-based segmentation
    p1 = DocumentPage(
        document_id=doc.id,
        page_number=1,
        text="Introduction to modern retrieval architectures and inverted indices.",
        headings=[{"text": "Chapter 1: Inverted Index"}],
    )
    p2 = DocumentPage(
        document_id=doc.id,
        page_number=2,
        text="Dense embedding representations map query and document passages.",
        headings=[{"text": "Chapter 2: Dense Vectors"}],
    )
    sections_headings = extract_sections([p1, p2])
    assert len(sections_headings) == 2
    assert sections_headings[0].title == "Chapter 1: Inverted Index"
    assert sections_headings[1].title == "Chapter 2: Dense Vectors"

    # Part B: 10-page blocks when no headings exist
    many_pages = [
        DocumentPage(
            document_id=doc.id,
            page_number=num,
            text=f"Page {num} content describing machine learning concepts.",
            headings=[],
        )
        for num in range(1, 26)
    ]
    sections_blocks = extract_sections(many_pages)
    assert len(sections_blocks) == 3
    assert sections_blocks[0].page_start == 1 and sections_blocks[0].page_end == 10
    assert sections_blocks[1].page_start == 11 and sections_blocks[1].page_end == 20
    assert sections_blocks[2].page_start == 21 and sections_blocks[2].page_end == 25

    # Part C: Outline / TOC chunk skipping
    toc_text = (
        "Table of Contents\n"
        "1. Introduction ..................... 1\n"
        "2. Background ....................... 5\n"
        "3. System Architecture ............. 12\n"
        "4. Experimental Evaluation ......... 20\n"
        "5. Concluding Remarks .............. 35\n"
    )
    assert is_content_chunk(toc_text) is False

    outline_with_short_prose = (
        "- Tokenization\n"
        "- Stemming\n"
        "Tokenization separates text into meaningful units for later processing."
    )
    assert is_content_chunk(outline_with_short_prose) is False

    prose_text = (
        "Natural language processing allows automated systems to understand text. "
        "Statistical methods rely on modeling lexical distributions. "
        "Neural models extend this capability through high-dimensional vectors."
    )
    assert is_content_chunk(prose_text) is True


def test_summary_records_are_regenerable_listable_deletable_and_owner_scoped(
    client, db_session
):
    owner = _user(db_session, "summary-owner")
    other = _user(db_session, "summary-other")
    doc = _document(db_session, owner)
    text = (
        "Statistical language models estimate token probabilities from context. "
        "Word embeddings represent semantic relationships in continuous spaces. "
        "Recurrent networks process sequences through hidden state updates. "
        "Attention mechanisms connect relevant positions across long sequences."
    )
    db_session.add(DocumentPage(document_id=doc.id, page_number=4, text=text))
    db_session.commit()

    path = f"/study/documents/{doc.id}/summaries"
    created = client.post(
        path,
        headers=_headers(owner),
        json={"summary_type": "short", "engine": "extractive"},
    )
    assert created.status_code == 201
    summary_id = created.json()["id"]

    cached = client.post(
        path,
        headers=_headers(owner),
        json={"summary_type": "short", "engine": "extractive"},
    )
    regenerated = client.post(
        path,
        headers=_headers(owner),
        json={
            "summary_type": "short",
            "engine": "extractive",
            "regenerate": True,
        },
    )
    assert cached.json()["id"] == summary_id
    assert regenerated.json()["id"] != summary_id

    listed = client.get(path, headers=_headers(owner))
    assert [item["id"] for item in listed.json()] == [
        regenerated.json()["id"],
        summary_id,
    ]
    assert client.get(path, headers=_headers(other)).status_code == 404
    assert (
        client.get(
            f"/study/summaries/{summary_id}", headers=_headers(other)
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/study/summaries/{summary_id}", headers=_headers(other)
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/study/summaries/{summary_id}", headers=_headers(owner)
        ).status_code
        == 204
    )


def test_async_summary_job_status_is_authenticated_and_owner_scoped(client, db_session):
    owner = _user(db_session, "async-summary-owner")
    other = _user(db_session, "async-summary-other")
    doc = _document(db_session, owner)
    db_session.add(
        DocumentPage(
            document_id=doc.id,
            page_number=1,
            text=(
                "Statistical language models estimate token probabilities from "
                "context. Word embeddings represent semantic relationships in "
                "continuous vector spaces."
            ),
        )
    )
    db_session.commit()

    response = client.post(
        f"/study/documents/{doc.id}/summaries",
        headers=_headers(owner),
        json={"summary_type": "short", "engine": "extractive", "run_async": True},
    )
    assert response.status_code == 201
    job_id = response.json()["job_id"]

    status = client.get(
        f"/study/summaries/jobs/{job_id}",
        headers=_headers(owner),
    )
    assert status.status_code == 200
    assert status.json()["status"] == "completed"
    assert status.json()["summary_id"] is not None
    assert (
        client.get(
            f"/study/summaries/jobs/{job_id}",
            headers=_headers(other),
        ).status_code
        == 404
    )


# ACCEPTANCE TEST 7
def test_notes_and_cheat_sheet_grounding_and_ownership_isolation(client, db_session):
    """7. Notes and cheat sheet contain citations and only document text."""
    owner = _user(db_session, "notes-owner")
    other = _user(db_session, "notes-intruder")
    doc = _document(db_session, owner, title="Deep Learning NLP")

    p1_text = (
        "Deep learning architectures process sequential token embeddings. "
        "For example, transformers apply self-attention to process tokens. "
        "Loss is computed using cross-entropy: L = -sum(y * log(p))."
    )
    db_session.add(
        DocumentPage(
            document_id=doc.id,
            page_number=1,
            text=p1_text,
            headings=[{"text": "Transformers"}],
        )
    )
    db_session.add(
        GlossaryTerm(
            owner_id=owner.id,
            document_id=doc.id,
            term="Self-Attention",
            term_key="self-attention",
            definition="A mechanism relating different sequence positions.",
            page=1,
            evidence_sentence="Self-attention relates positions.",
            source="custom",
            importance=1.0,
        )
    )
    db_session.commit()

    # 1. Check Chapter Notes format and grounding
    notes_response = client.get(
        f"/study/documents/{doc.id}/notes",
        headers=_headers(owner),
    )
    assert notes_response.status_code == 200
    notes_md = notes_response.text
    assert "# Chapter Notes: Deep Learning NLP" in notes_md
    assert "## Transformers (pp. 1-1)" in notes_md
    assert "**Self-Attention**:" in notes_md
    assert "[p. 1]" in notes_md
    assert "### Examples" in notes_md
    assert "For example, transformers apply self-attention" in notes_md
    assert "A mechanism relating different sequence positions." not in notes_md

    # 2. Check Cheat Sheet format and grounding
    cheat_response = client.get(
        f"/study/documents/{doc.id}/cheat-sheet",
        headers=_headers(owner),
    )
    assert cheat_response.status_code == 200
    cheat_md = cheat_response.text
    assert "# Cheat Sheet: Deep Learning NLP" in cheat_md
    assert "## Key Terms & Definitions" in cheat_md
    assert "**Self-Attention**:" in cheat_md
    assert "A mechanism relating different sequence positions." not in cheat_md
    assert (
        "For example, transformers apply self-attention to process tokens." in cheat_md
    )
    assert "## Formulas & Code" in cheat_md
    assert "L = -sum(y * log(p))" in cheat_md
    assert "## Key Facts" in cheat_md
    assert "[p. 1]" in cheat_md

    # 3. Verify Ownership Isolation: Other user gets 404
    other_notes = client.get(
        f"/study/documents/{doc.id}/notes",
        headers=_headers(other),
    )
    other_cheat = client.get(
        f"/study/documents/{doc.id}/cheat-sheet",
        headers=_headers(other),
    )
    other_summaries = client.get(
        f"/study/documents/{doc.id}/summaries",
        headers=_headers(other),
    )
    assert other_notes.status_code == 404
    assert other_cheat.status_code == 404
    assert other_summaries.status_code == 404
