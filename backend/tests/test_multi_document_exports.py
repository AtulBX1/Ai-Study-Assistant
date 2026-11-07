"""Fake-only acceptance coverage for multi-document study exports."""

from __future__ import annotations

import csv
import re
from datetime import date
from io import BytesIO, StringIO

import pymupdf
from docx import Document as WordDocument

from app.core.config import Settings
from app.models import (
    Chunk,
    Document,
    DocumentKeyTerm,
    DocumentPage,
    DocumentSummary,
    Flashcard,
    GlossaryTerm,
    Question,
    Quiz,
    StudyPlan,
    StudyPlanItem,
    User,
)
from app.routers.chat import get_rag_pipeline
from app.services.rag import AnswerCache, FakeProvider, RAGChatPipeline, RateLimiter
from app.services.rag.providers import ExtractiveProvider
from app.services.study.exports import generate_export
from tests.conftest import access_token_for


def _user(db_session, name: str) -> User:
    user = User(email=f"{name}@example.test", full_name=name, password_hash="unused")
    db_session.add(user)
    db_session.flush()
    return user


def _headers(user: User) -> dict[str, str]:
    token = access_token_for(user.id)
    return {"Authorization": f"Bearer {token}"}


def _document(
    db_session, owner: User, title: str, *, is_private: bool = False
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


def _chunk(db_session, document: Document, page: int, text: str) -> Chunk:
    chunk = Chunk(
        doc_id=document.id,
        page=page,
        page_start=page,
        page_end=page,
        section="Overview",
        text=text,
        token_count=len(text.split()),
        chunk_index=page,
    )
    db_session.add(chunk)
    db_session.flush()
    return chunk


def _fake_retriever(db, user_id, query, doc_ids=None, top_k=5):
    documents = {
        document.id: document
        for document in db.query(Document).filter(
            Document.owner_id == user_id,
            Document.id.in_(doc_ids or []),
        )
    }
    chunks = (
        db.query(Chunk)
        .filter(Chunk.doc_id.in_(documents))
        .order_by(Chunk.id)
        .limit(top_k)
        .all()
    )
    results = [
        {
            "chunk_id": chunk.id,
            "document_id": chunk.doc_id,
            "document_title": documents[chunk.doc_id].title,
            "page": chunk.page,
            "text": chunk.text,
            "is_private": documents[chunk.doc_id].is_private,
            "retrieval_score": 1.0,
        }
        for chunk in chunks
    ]
    return results, any(result["is_private"] for result in results)


class FakeExtractiveProvider(ExtractiveProvider):
    def answer_with_chunks(self, question, chunks):
        first = chunks[0]
        answer = f"Evidence [{first['document_title']}, p.{first['page']}]"
        return answer, [
            {
                "document_title": first["document_title"],
                "page": first["page"],
                "chunk_id": first["chunk_id"],
            }
        ]


class FakeEmbeddingService:
    def embed_texts(self, texts):
        return [[1.0, 0.0] for _ in texts]


def _pipeline(provider: FakeProvider) -> RAGChatPipeline:
    return RAGChatPipeline(
        provider=provider,
        extractive_provider=FakeExtractiveProvider(),
        rate_limiter=RateLimiter(requests_per_minute=100),
        cache=AnswerCache(),
        context_retriever=_fake_retriever,
        settings=Settings(
            allow_external_llm=True,
            rag_retrieval_confidence_threshold=0,
        ),
    )


def test_cross_document_answers_cite_each_source_and_reject_unowned_document(
    client, db_session
):
    owner = _user(db_session, "multi-owner")
    other_owner = _user(db_session, "multi-other")
    first = _document(db_session, owner, "First.pdf")
    second = _document(db_session, owner, "Second.pdf")
    foreign = _document(db_session, other_owner, "Foreign.pdf")
    first_chunk = _chunk(db_session, first, 3, "The first document describes TF-IDF.")
    second_chunk = _chunk(
        db_session, second, 7, "The second document describes Word2Vec."
    )
    db_session.flush()

    answer_text = "TF-IDF [First.pdf, p.3] and Word2Vec [Second.pdf, p.7]"
    provider = FakeProvider(response_text=answer_text)
    client.app.dependency_overrides[get_rag_pipeline] = lambda: _pipeline(provider)

    response = client.post(
        "/study/multi-document/qa",
        headers=_headers(owner),
        json={"question": "Compare the methods", "document_ids": [first.id, second.id]},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["answer"] == answer_text
    assert {
        (item["document_title"], item["page"], item["chunk_id"])
        for item in result["citations"]
    } == {
        ("First.pdf", 3, first_chunk.id),
        ("Second.pdf", 7, second_chunk.id),
    }
    assert provider.last_prompt is not None

    rejected = client.post(
        "/study/multi-document/qa",
        headers=_headers(owner),
        json={"question": "Read this", "document_ids": [first.id, foreign.id]},
    )
    assert rejected.status_code == 404


def test_cross_document_question_returns_selected_documents_not_found(
    client, db_session
):
    owner = _user(db_session, "empty-retriever")
    document = _document(db_session, owner, "Empty.pdf")
    provider = FakeProvider(response_text="must not be used")
    pipeline = _pipeline(provider)
    pipeline.context_retriever = lambda *args: ([], False)
    client.app.dependency_overrides[get_rag_pipeline] = lambda: pipeline

    response = client.post(
        "/study/multi-document/qa",
        headers=_headers(owner),
        json={"question": "Anything here?", "document_ids": [document.id]},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "not found in the selected documents"
    assert response.json()["citations"] == []
    assert provider.last_prompt is None


def test_private_document_uses_local_fallback_without_external_provider_or_trace(
    client, db_session, monkeypatch
):
    owner = _user(db_session, "private-multi")
    document = _document(db_session, owner, "Private.pdf", is_private=True)
    _chunk(db_session, document, 2, "Private study evidence appears here.")
    provider = FakeProvider(response_text="external should not receive private text")
    trace_calls = []
    monkeypatch.setattr(
        "app.services.rag.pipeline.trace_chat",
        lambda **kwargs: trace_calls.append(kwargs),
    )
    client.app.dependency_overrides[get_rag_pipeline] = lambda: _pipeline(provider)

    response = client.post(
        "/study/multi-document/qa",
        headers=_headers(owner),
        json={
            "question": "What is in this private document?",
            "document_ids": [document.id],
        },
    )

    assert response.status_code == 200
    assert provider.last_prompt is None
    assert "[Private.pdf, p.2]" in response.json()["answer"]
    assert trace_calls == []


def test_comparison_returns_terms_section_matches_and_self_only_shared_terms(
    client, db_session, monkeypatch
):
    from app.services.study import multi_document

    monkeypatch.setattr(multi_document, "get_embedding_service", FakeEmbeddingService)
    owner = _user(db_session, "comparison-owner")
    first = _document(db_session, owner, "A.pdf")
    second = _document(db_session, owner, "B.pdf")
    shared = "Attention"
    for document, term, page in (
        (first, shared, 1),
        (first, "Encoder", 2),
        (second, shared, 4),
        (second, "Decoder", 5),
    ):
        db_session.add(
            DocumentKeyTerm(
                document_id=document.id,
                term=term,
                label="KEYPHRASE",
                page=page,
                source="keyphrase",
            )
        )
    db_session.add_all(
        [
            DocumentPage(
                document_id=first.id,
                page_number=1,
                text="Attention lets a model focus on relevant tokens.",
            ),
            DocumentPage(
                document_id=second.id,
                page_number=4,
                text="Attention lets a model focus on relevant tokens.",
            ),
        ]
    )
    db_session.commit()

    comparison = client.post(
        "/study/documents/compare",
        headers=_headers(owner),
        json={"document_ids": [first.id, second.id]},
    )

    assert comparison.status_code == 200
    body = comparison.json()
    assert [item["term"] for item in body["shared_terms"]] == ["Attention"]
    assert [item["term"] for item in body["unique_to_a"]] == ["Encoder"]
    assert [item["term"] for item in body["unique_to_b"]] == ["Decoder"]
    match = body["matched_sections"][0]
    assert (match["page_start_a"], match["page_end_a"]) == (1, 1)
    assert (match["page_start_b"], match["page_end_b"]) == (4, 4)
    assert match["similarity"] == 1
    assert all("p." in bullet or "pp." in bullet for bullet in body["bullets"])

    self_comparison = client.post(
        "/study/documents/compare",
        headers=_headers(owner),
        json={"document_ids": [first.id, first.id]},
    )
    assert self_comparison.status_code == 200
    self_body = self_comparison.json()
    assert [item["term"] for item in self_body["shared_terms"]] == [
        "Attention",
        "Encoder",
    ]
    assert self_body["unique_to_a"] == []
    assert self_body["unique_to_b"] == []
    assert self_body["matched_sections"] == []


def test_pdf_and_docx_exports_for_notes_glossary_plan_and_quiz(client, db_session):
    owner = _user(db_session, "export-owner")
    document = _document(db_session, owner, "NLP Notes.pdf")
    db_session.add(
        DocumentPage(
            document_id=document.id,
            page_number=20,
            text=(
                "Attention is a mechanism that lets a model focus on relevant tokens. "
                "Transformers use attention to process sequences effectively."
            ),
        )
    )
    db_session.add(
        GlossaryTerm(
            owner_id=owner.id,
            document_id=document.id,
            term="Attention",
            term_key="attention",
            definition="A mechanism that lets a model focus on relevant tokens.",
            page=20,
            evidence_sentence=(
                "Attention is a mechanism that lets a model focus on relevant tokens."
            ),
            source="stored",
            importance=1,
        )
    )
    plan = StudyPlan(
        owner_id=owner.id,
        start_date=date(2026, 11, 1),
        exam_date=date(2026, 11, 8),
        daily_minutes=60,
        document_ids=[document.id],
    )
    quiz = Quiz(owner_id=owner.id, title="NLP Quiz", source_document_id=document.id)
    db_session.add_all([plan, quiz])
    db_session.flush()
    db_session.add(
        StudyPlanItem(
            plan_id=plan.id,
            scheduled_date=date(2026, 11, 2),
            activity_type="read_summary",
            topic="Attention",
            document_id=document.id,
            page_start=20,
            page_end=20,
            minutes=30,
        )
    )
    db_session.add(
        Question(
            quiz_id=quiz.id,
            type="short_answer",
            difficulty="easy",
            prompt="What does attention do?",
            options=None,
            answer="It focuses on relevant tokens.",
            explanation="It selects relevant sequence content.",
            topic="Attention",
            page=20,
        )
    )
    db_session.commit()

    for kind, item_id, heading in (
        ("notes", document.id, "Chapter Notes"),
        ("glossary", document.id, "Glossary"),
        ("plan", plan.id, "Study Plan"),
        ("quiz", quiz.id, "NLP Quiz"),
    ):
        pdf = client.get(
            f"/export/{kind}/{item_id}?format=pdf",
            headers=_headers(owner),
        )
        assert pdf.status_code == 200
        assert pdf.content.startswith(b"%PDF")
        assert re.search(rb"/Type\s*/Page\b", pdf.content)

        docx = client.get(
            f"/export/{kind}/{item_id}?format=docx",
            headers=_headers(owner),
        )
        assert docx.status_code == 200
        word = WordDocument(BytesIO(docx.content))
        text = "\n".join(paragraph.text for paragraph in word.paragraphs)
        text += "\n" + "\n".join(
            cell.text
            for table in word.tables
            for row in table.rows
            for cell in row.cells
        )
        assert heading in text
        if kind == "quiz":
            assert "Marking Scheme" not in text
    exam = client.get(
        f"/export/exam/{quiz.id}?format=docx",
        headers=_headers(owner),
    )
    assert exam.status_code == 200
    exam_word = WordDocument(BytesIO(exam.content))
    exam_text = "\n".join(paragraph.text for paragraph in exam_word.paragraphs)
    assert "Total marks: 1" in exam_text
    assert "Marking Scheme" in exam_text


def test_flashcard_csv_quotes_commas_and_quotes_and_includes_required_columns(
    db_session,
):
    owner = _user(db_session, "csv-owner")
    document = _document(db_session, owner, "Flashcards")
    db_session.add(
        Flashcard(
            owner_id=owner.id,
            document_id=document.id,
            front='A, "quoted" prompt',
            back="Answer, with detail",
            source_page=9,
        )
    )
    db_session.commit()

    content, media_type, filename = generate_export(
        db_session,
        owner_id=owner.id,
        kind="flashcards",
        item_id=document.id,
        format="csv",
    )

    rows = list(csv.reader(StringIO(content.decode("utf-8"))))
    assert rows == [
        ["front", "back", "page"],
        ['A, "quoted" prompt', "Answer, with detail", "9"],
    ]
    assert media_type.startswith("text/csv")
    assert filename.endswith(".csv")


def test_non_latin_exports_preserve_docx_text_and_note_pdf_substitution(db_session):
    owner = _user(db_session, "unicode-owner")
    document = _document(db_session, owner, "Hindi and Punjabi")
    non_latin = "हिन्दी ਪੰਜਾਬੀ"
    db_session.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            text=f"{non_latin} are supported study languages.",
        )
    )
    db_session.add(
        GlossaryTerm(
            owner_id=owner.id,
            document_id=document.id,
            term="हिन्दी",
            term_key="हिन्दी",
            definition=f"{non_latin} study text",
            page=1,
            evidence_sentence=f"{non_latin} study text",
            source="stored",
            importance=1,
        )
    )
    db_session.commit()

    pdf, _, _ = generate_export(
        db_session,
        owner_id=owner.id,
        kind="glossary",
        item_id=document.id,
        format="pdf",
    )
    docx, _, _ = generate_export(
        db_session,
        owner_id=owner.id,
        kind="glossary",
        item_id=document.id,
        format="docx",
    )

    assert pdf.startswith(b"%PDF")
    with pymupdf.open(stream=pdf, filetype="pdf") as pdf_document:
        pdf_text = "\n".join(page.get_text() for page in pdf_document)
    assert "font limitations" in pdf_text
    assert "[?]" in pdf_text
    word = WordDocument(BytesIO(docx))
    word_text = "\n".join(paragraph.text for paragraph in word.paragraphs)
    word_text += "\n" + "\n".join(
        cell.text for table in word.tables for row in table.rows for cell in row.cells
    )
    assert non_latin in word_text


def test_export_rejects_unknown_kind_format_and_other_users_item(client, db_session):
    owner = _user(db_session, "export-owner-check")
    other = _user(db_session, "export-other-check")
    document = _document(db_session, owner, "Owned.pdf")
    foreign = _document(db_session, other, "Foreign.pdf")
    db_session.commit()

    for path in (
        f"/export/unknown/{document.id}?format=pdf",
        f"/export/notes/{document.id}?format=zip",
    ):
        response = client.get(path, headers=_headers(owner))
        assert response.status_code == 400

    response = client.get(
        f"/export/notes/{foreign.id}?format=pdf",
        headers=_headers(owner),
    )
    assert response.status_code == 404


def test_maximum_selected_documents_is_configurable(client, db_session, monkeypatch):
    owner = _user(db_session, "limit-owner")
    documents = [_document(db_session, owner, f"{index}.pdf") for index in range(2)]
    settings = Settings(max_multi_document_count=1)
    monkeypatch.setattr("app.routers.study.get_settings", lambda: settings)

    response = client.post(
        "/study/multi-document/qa",
        headers=_headers(owner),
        json={
            "question": "Question",
            "document_ids": [document.id for document in documents],
        },
    )

    assert response.status_code == 413


def test_summary_export_uses_stored_summary_and_page_references(db_session):
    owner = _user(db_session, "summary-export")
    document = _document(db_session, owner, "Summarized.pdf")
    summary = DocumentSummary(
        document_id=document.id,
        owner_id=owner.id,
        summary_type="short",
        content="## Summary\n\n- Key result [p. 12]",
        page_start=12,
        page_end=14,
    )
    db_session.add(summary)
    db_session.commit()

    content, _, _ = generate_export(
        db_session,
        owner_id=owner.id,
        kind="summary",
        item_id=summary.id,
        format="docx",
    )

    word = WordDocument(BytesIO(content))
    text = "\n".join(paragraph.text for paragraph in word.paragraphs)
    assert "Summary - Summarized.pdf" in text
    assert "Pages 12-14" in text
    assert "[p. 12]" in text
