"""Authenticated endpoints for Unit V transformer experiments and inference."""

import json
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models import Chunk, Document, DocumentKeyTerm, User
from app.nlp.preprocessing import extract_keywords
from app.retrieval import ChunkRecord, get_retriever
from app.routers.lab import _document_pages, _page_text
from app.services import transformer_inference as inference

lab_router = APIRouter(prefix="/lab", tags=["transformer lab"])
documents_router = APIRouter(prefix="/documents", tags=["documents"])
DatabaseSession = Annotated[Session, Depends(get_db)]
AuthenticatedUser = Annotated[User, Depends(get_current_user)]
MAX_TEXT_CHARS = 20_000
MAX_DOC_IDS = 100
MAX_RETRIEVAL_RESULTS = 20
ROOT = Path(__file__).resolve().parents[3]
MODEL_ROOT = ROOT / "models" / "transformers"


class ExtractiveQARequest(BaseModel):
    """Bounded retrieval-augmented extractive QA request."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2_000)
    doc_ids: list[int] | None = Field(default=None, max_length=MAX_DOC_IDS)
    mode: Literal["tfidf", "bm25", "word2vec", "dense", "hybrid"] = "hybrid"
    k: int = Field(default=5, ge=1, le=MAX_RETRIEVAL_RESULTS)

    @field_validator("doc_ids")
    @classmethod
    def validate_doc_ids(cls, values: list[int] | None) -> list[int] | None:
        if values is not None and (
            any(value < 1 for value in values) or len(set(values)) != len(values)
        ):
            raise ValueError("doc_ids must contain unique positive IDs.")
        return values

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question cannot be blank.")
        return value


class PageRangeRequest(BaseModel):
    """A document page interval for NER and summarization."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, min_length=1, max_length=MAX_TEXT_CHARS)
    document_id: int | None = Field(default=None, gt=0)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_source(self) -> "PageRangeRequest":
        if (self.text is None) == (self.document_id is None):
            raise ValueError("Provide exactly one of text or document_id.")
        if self.text is not None and not self.text.strip():
            raise ValueError("text cannot be blank.")
        if self.text is not None and (
            self.page_start is not None or self.page_end is not None
        ):
            raise ValueError("Page ranges can only be used with document_id.")
        if (
            self.page_start is not None
            and self.page_end is not None
            and self.page_end < self.page_start
        ):
            raise ValueError("page_end must be greater than or equal to page_start.")
        return self


class TransformerSummaryRequest(PageRangeRequest):
    """A source and supported transformer decoding strategy."""

    decoding: Literal["greedy", "beam"] = "greedy"


class QuestionGenerationRequest(BaseModel):
    """A source chunk or bounded text and an optional answer span."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: int | None = Field(default=None, gt=0)
    text: str | None = Field(default=None, min_length=1, max_length=MAX_TEXT_CHARS)
    answer: str | None = Field(default=None, min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def validate_source(self) -> "QuestionGenerationRequest":
        if (self.chunk_id is None) == (self.text is None):
            raise ValueError("Provide exactly one of chunk_id or text.")
        return self


def _owned_document_ids(
    db: Session, user_id: int, requested_ids: list[int] | None
) -> list[int]:
    query = select(Document.id).where(Document.owner_id == user_id)
    if requested_ids is not None:
        if not requested_ids:
            return []
        query = query.where(Document.id.in_(requested_ids))
    document_ids = list(db.scalars(query.order_by(Document.id)))
    if requested_ids is not None and set(document_ids) != set(requested_ids):
        raise HTTPException(status_code=404, detail="Document not found.")
    return document_ids


def _page_source(
    request: PageRangeRequest, db: Session, user: User
) -> tuple[list[tuple[int | None, str]], dict[str, Any]]:
    if request.text is not None:
        return [(None, request.text)], {"type": "provided_text"}
    pages = _document_pages(
        db,
        request.document_id,
        user.id,
        request.page_start,
        request.page_end,
    )
    texts = _page_text(pages)
    return (
        [(page.page_number, text) for page, text in zip(pages, texts, strict=True)],
        {
            "document_id": request.document_id,
            "pages": [page.page_number for page in pages],
        },
    )


def _inference_error(error: Exception) -> HTTPException:
    if isinstance(error, FileNotFoundError):
        return HTTPException(status_code=503, detail=str(error))
    if isinstance(error, ValueError):
        return HTTPException(status_code=422, detail=str(error))
    if isinstance(error, RuntimeError):
        if "out of memory" in str(error).lower():
            inference.clear_gpu_memory()
            return HTTPException(
                status_code=503,
                detail="CUDA out of memory; reduce batch_size or max_seq_len.",
            )
        return HTTPException(status_code=503, detail=str(error))
    raise error


@lab_router.post("/qa/extractive")
def extractive_qa(
    request: ExtractiveQARequest,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Retrieve only owned document chunks and predict the strongest answer span."""
    document_ids = _owned_document_ids(db, user.id, request.doc_ids)
    chunks = (
        list(
            db.scalars(
                select(Chunk)
                .join(Document, Chunk.doc_id == Document.id)
                .where(
                    Document.owner_id == user.id,
                    Chunk.doc_id.in_(document_ids),
                )
                .order_by(Chunk.doc_id, Chunk.chunk_index, Chunk.id)
            )
        )
        if document_ids
        else []
    )
    if not chunks:
        return {
            "answer": "no answer found",
            "confidence": 0.0,
            "chunk_id": None,
            "document_id": None,
            "page": None,
            "start_offset": None,
            "end_offset": None,
            "retrieved_chunks": 0,
        }
    records = [
        ChunkRecord(
            chunk_id=chunk.id,
            text=chunk.text,
            document_id=chunk.doc_id,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            section=chunk.section,
            vector_id=chunk.vector_id,
        )
        for chunk in chunks
    ]
    try:
        retriever = get_retriever(request.mode, user.id, records)
        candidates = retriever.retrieve(request.question, document_ids, request.k)
        threshold = get_settings().transformer_no_answer_threshold
        answers = [
            (
                inference.answer_chunk(request.question, chunk.text, threshold),
                chunk,
            )
            for chunk in candidates
        ]
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        raise _inference_error(error) from error
    found = [item for item in answers if item[0]["found"]]
    if not found:
        return {
            "answer": "no answer found",
            "confidence": max((item[0]["confidence"] for item in answers), default=0.0),
            "chunk_id": None,
            "document_id": None,
            "page": None,
            "start_offset": None,
            "end_offset": None,
            "retrieved_chunks": len(candidates),
        }
    answer, chunk = max(found, key=lambda item: item[0]["confidence"])
    return {
        **answer,
        "chunk_id": chunk.chunk_id,
        "document_id": chunk.document_id,
        "page": chunk.page,
        "retrieved_chunks": len(candidates),
        "retriever": request.mode,
    }


@lab_router.post("/ner")
def named_entities(
    request: PageRangeRequest,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Return page-scoped NER entities with source offsets."""
    sources, source = _page_source(request, db, user)
    results = []
    try:
        for page, text in sources:
            results.append(
                {
                    "page": page,
                    "entities": inference.extract_entities(text),
                }
            )
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        raise _inference_error(error) from error
    return {"source": source, "pages": results}


@documents_router.post("/{document_id}/key-terms")
def document_key_terms(
    document_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
    method: Annotated[str, Query(pattern="^(tfidf|yake|rake)$")] = "tfidf",
    top_n: Annotated[int, Query(ge=1, le=100)] = 10,
) -> dict[str, Any]:
    """Combine Step 4 keyphrases with NER and persist glossary-ready terms."""
    pages = _document_pages(db, document_id, user.id)
    texts = _page_text(pages)
    rows: list[DocumentKeyTerm] = []
    output: list[dict[str, Any]] = []
    try:
        for page, text in zip(pages, texts, strict=True):
            entities = inference.extract_entities(text)
            keyphrases = extract_keywords([text], method, top_n)
            page_phrases = [
                phrase for phrase in keyphrases if phrase.get("document") == 0
            ]
            page_terms: list[dict[str, Any]] = []
            for entity in entities:
                term = {
                    "term": entity["text"],
                    "label": entity["label"],
                    "page": page.page_number,
                    "start_offset": entity["start_offset"],
                    "end_offset": entity["end_offset"],
                    "source": "ner",
                }
                page_terms.append(term)
            for phrase in page_phrases:
                term = {
                    "term": str(phrase.get("phrase", phrase.get("term", ""))),
                    "label": "KEYPHRASE",
                    "page": page.page_number,
                    "start_offset": None,
                    "end_offset": None,
                    "source": "keyphrase",
                }
                page_terms.append(term)
            rows.extend(
                DocumentKeyTerm(document_id=document_id, **term) for term in page_terms
            )
            output.extend(page_terms)
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        raise _inference_error(error) from error
    db.execute(
        delete(DocumentKeyTerm).where(DocumentKeyTerm.document_id == document_id)
    )
    db.add_all(rows)
    db.commit()
    return {
        "document_id": document_id,
        "keyphrase_method": method,
        "stored_terms": len(rows),
        "terms": output,
    }


@lab_router.post("/summarize/transformer")
def transformer_summary(
    request: TransformerSummaryRequest,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Generate a bounded T5 summary with page citations for document inputs."""
    sources, source = _page_source(request, db, user)
    text = "\n\n".join(item[1] for item in sources)
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Selected text exceeds the {MAX_TEXT_CHARS}-character limit.",
        )
    try:
        summary = inference.summarize_text(text, request.decoding)
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        raise _inference_error(error) from error
    return {
        "summary": summary,
        "decoding": request.decoding,
        "source": source,
    }


@lab_router.post("/question-generation")
def question_generation(
    request: QuestionGenerationRequest,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Generate a T5 question from bounded text or an owned document chunk."""
    source: dict[str, Any]
    if request.chunk_id is not None:
        chunk = db.scalar(
            select(Chunk)
            .join(Document, Chunk.doc_id == Document.id)
            .where(
                Chunk.id == request.chunk_id,
                Document.owner_id == user.id,
            )
        )
        if chunk is None:
            raise HTTPException(status_code=404, detail="Chunk not found.")
        text = chunk.text
        source = {
            "chunk_id": chunk.id,
            "document_id": chunk.doc_id,
            "page": chunk.page,
        }
    else:
        text = request.text
        source = {"type": "provided_text"}
    if text is None or len(text) > MAX_TEXT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Question-generation text exceeds {MAX_TEXT_CHARS} characters.",
        )
    try:
        question = inference.generate_question(text, request.answer)
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        raise _inference_error(error) from error
    return {"question": question, "source": source}


@lab_router.get("/tokenizers")
def tokenizer_comparison(
    user: AuthenticatedUser,
    text: Annotated[str, Query(min_length=1, max_length=2_000)],
) -> dict[str, Any]:
    """Compare BPE, WordPiece, and SentencePiece on the exact supplied text."""
    try:
        return {"text": text, "tokenizers": inference.tokenizer_lab(text)}
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        raise _inference_error(error) from error


@lab_router.get("/attention")
def transformer_attention(
    user: AuthenticatedUser,
    sentence: Annotated[str, Query(min_length=1, max_length=1_000)],
) -> dict[str, Any]:
    """Return DistilBERT self-attention as layer/head matrices."""
    try:
        return inference.attention_weights(sentence)
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        raise _inference_error(error) from error


@lab_router.get("/positional-encoding")
def positional_encoding(
    user: AuthenticatedUser,
    length: Annotated[int, Query(ge=1, le=512)] = 32,
    dimension: Annotated[int, Query(ge=1, le=1024)] = 64,
) -> dict[str, Any]:
    """Return the sinusoidal position-encoding matrix for a requested shape."""
    try:
        values = inference.sinusoidal_encoding(length, dimension)
    except ValueError as error:
        raise _inference_error(error) from error
    return {"length": length, "dimension": dimension, "values": values}


@lab_router.get("/transformers/results")
def transformer_results(user: AuthenticatedUser) -> dict[str, Any]:
    """Return locally persisted transformer evaluation tables."""
    path = MODEL_ROOT / "evaluation.json"
    if not path.is_file():
        raise HTTPException(
            status_code=503,
            detail=(
                "Transformer evaluations are not available yet; "
                "train Step 10 models first."
            ),
        )
    return json.loads(path.read_text(encoding="utf-8"))
