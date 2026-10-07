"""Authenticated preprocessing lab endpoints."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models import Chunk, Document, DocumentPage, User
from app.nlp.embeddings_classic import (
    EmbeddingModel,
    EmbeddingUnavailableError,
    OutOfVocabularyError,
    cosine_similarity,
    keyed_vectors,
    most_similar,
    project_vectors,
    solve_analogy,
    train_word2vec,
)
from app.nlp.preprocessing import (
    MAX_INPUT_CHARS,
    detect_language,
    extract_keywords,
    generate_ngrams,
    normalize_text,
    preprocess_text,
    regex_tokenize,
    vectorize_documents,
)
from app.retrieval.registry import invalidate_retriever_cache

router = APIRouter(prefix="/lab", tags=["preprocessing lab"])
DatabaseSession = Annotated[Session, Depends(get_db)]
AuthenticatedUser = Annotated[User, Depends(get_current_user)]


class PreprocessRequest(BaseModel):
    """Text or an owner-scoped document page range to preprocess."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, max_length=MAX_INPUT_CHARS)
    document_id: int | None = Field(default=None, gt=0)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    steps: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_source(self) -> "PreprocessRequest":
        if (self.text is None) == (self.document_id is None):
            raise ValueError("Provide exactly one of text or document_id.")
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


def _document_pages(
    db: Session,
    document_id: int,
    user_id: int,
    page_start: int | None = None,
    page_end: int | None = None,
) -> list[DocumentPage]:
    """Return an owner's selected extracted pages or a visible API error."""
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.owner_id == user_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    query = select(DocumentPage).where(DocumentPage.document_id == document_id)
    if page_start is not None:
        query = query.where(DocumentPage.page_number >= page_start)
    if page_end is not None:
        query = query.where(DocumentPage.page_number <= page_end)
    pages = list(db.scalars(query.order_by(DocumentPage.page_number)))
    if not pages:
        raise HTTPException(
            status_code=409,
            detail="The document has no extracted pages in the requested range.",
        )
    return pages


def _page_text(pages: list[DocumentPage]) -> list[str]:
    texts = [page.cleaned_text or normalize_text(page.text) for page in pages]
    if sum(len(text) for text in texts) > MAX_INPUT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=f"Selected text exceeds the {MAX_INPUT_CHARS}-character limit.",
        )
    return texts


def _source_text(
    request: PreprocessRequest, db: Session, user: User
) -> tuple[str, list[int]]:
    if request.text is not None:
        return request.text, []
    pages = _document_pages(
        db,
        request.document_id,
        user.id,
        request.page_start,
        request.page_end,
    )
    texts = _page_text(pages)
    return "\n\n".join(texts), [page.page_number for page in pages]


@router.post("/preprocess")
def preprocess(
    request: PreprocessRequest,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Return every requested preprocessing result for text or selected pages."""
    text, page_numbers = _source_text(request, db, user)
    try:
        output = preprocess_text(text, request.steps or None)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "language": detect_language(text),
        "pages": page_numbers,
        "steps": output,
    }


def _document_texts(
    document_id: int,
    db: Session,
    user: User,
) -> tuple[list[DocumentPage], list[str]]:
    pages = _document_pages(db, document_id, user.id)
    return pages, _page_text(pages)


@router.get("/ngrams")
def document_ngrams(
    document_id: Annotated[int, Query(gt=0)],
    db: DatabaseSession,
    user: AuthenticatedUser,
    n: Annotated[int, Query(ge=1, le=3)] | None = None,
) -> dict[str, Any]:
    """Return per-page n-gram frequencies for an owned document."""
    pages, texts = _document_texts(document_id, db, user)
    frequencies = [
        {
            "page": page.page_number,
            **generate_ngrams(regex_tokenize(text), n),
        }
        for page, text in zip(pages, texts, strict=True)
    ]
    return {"document_id": document_id, "n": n, "pages": frequencies}


@router.get("/tfidf-terms")
def document_tfidf_terms(
    document_id: Annotated[int, Query(gt=0)],
    db: DatabaseSession,
    user: AuthenticatedUser,
    top_n: Annotated[int, Query(ge=1, le=100)] = 10,
) -> dict[str, Any]:
    """Return a per-page BoW/TF-IDF view and the top terms for an owned document."""
    pages, texts = _document_texts(document_id, db, user)
    output = vectorize_documents(texts, top_n)
    return {
        "document_id": document_id,
        "pages": [
            {
                "page": page.page_number,
                "terms": output["top_terms"][index],
                "bow": output["bow"][index] if output["bow"] else {},
            }
            for index, page in enumerate(pages)
        ],
        "vocabulary": output["vocabulary"],
    }


@router.get("/keyphrases")
def document_keyphrases(
    document_id: Annotated[int, Query(gt=0)],
    db: DatabaseSession,
    user: AuthenticatedUser,
    method: Annotated[str, Query(pattern="^(tfidf|yake|rake)$")] = "tfidf",
    top_n: Annotated[int, Query(ge=1, le=100)] = 10,
) -> dict[str, Any]:
    """Extract ranked key terms or phrases from each page in an owned document."""
    pages, texts = _document_texts(document_id, db, user)
    phrases = extract_keywords(texts, method, top_n)
    for phrase in phrases:
        phrase["page"] = pages[phrase.pop("document")].page_number
    return {"document_id": document_id, "method": method, "keyphrases": phrases}


class Word2VecTrainRequest(BaseModel):
    """Bounded Word2Vec parameters for an owned document."""

    model_config = ConfigDict(extra="forbid")

    document_id: int = Field(gt=0)
    architecture: Literal["cbow", "skipgram"]
    vector_size: int = Field(default=100, ge=10, le=500)
    window: int = Field(default=5, ge=1, le=20)
    min_count: int = Field(default=1, ge=1, le=100)
    epochs: int = Field(default=20, ge=1, le=500)
    negative: int = Field(default=5, ge=1, le=20)
    seed: int = Field(default=42, ge=0, le=2_147_483_647)


def _owned_document(db: Session, document_id: int, user_id: int) -> Document:
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.owner_id == user_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document


def _embedding_vectors(
    model: EmbeddingModel,
    user: User,
    document_id: int | None,
):
    try:
        return keyed_vectors(model, user.id, document_id)
    except EmbeddingUnavailableError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (OSError, RuntimeError) as error:
        raise HTTPException(
            status_code=503,
            detail=f"Unable to load {model} embeddings: {error}",
        ) from error


def _embedding_error(error: Exception) -> HTTPException:
    if isinstance(error, OutOfVocabularyError):
        return HTTPException(
            status_code=404,
            detail={"message": str(error), "suggestion": error.suggestion},
        )
    return HTTPException(status_code=422, detail=str(error))


@router.post("/word2vec/train")
def train_document_word2vec(
    request: Word2VecTrainRequest,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, Any]:
    """Train one owner-scoped CBOW or Skip-Gram model on document chunks."""
    _owned_document(db, request.document_id, user.id)
    chunks = list(
        db.scalars(
            select(Chunk)
            .where(Chunk.doc_id == request.document_id)
            .order_by(Chunk.chunk_index, Chunk.id)
        )
    )
    if not chunks:
        raise HTTPException(
            status_code=409,
            detail="The document has no chunks to train on. Rechunk it first.",
        )
    from app.retrieval.base import ChunkRecord

    records = [
        ChunkRecord(
            chunk_id=chunk.id,
            document_id=chunk.doc_id,
            text=chunk.text,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            section=chunk.section,
        )
        for chunk in chunks
    ]
    try:
        result = train_word2vec(
            records,
            user.id,
            request.document_id,
            request.architecture,
            vector_size=request.vector_size,
            window=request.window,
            min_count=request.min_count,
            epochs=request.epochs,
            negative=request.negative,
            seed=request.seed,
        )
    except ImportError as error:
        raise HTTPException(
            status_code=503,
            detail="Word2Vec requires the gensim dependency.",
        ) from error
    except RuntimeError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if result["saved"]:
        invalidate_retriever_cache("word2vec", user.id, request.document_id)
    return {"document_id": request.document_id, **result}


@router.get("/embeddings/similar")
def embeddings_similar(
    document_id: Annotated[int, Query(gt=0)],
    word: Annotated[str, Query(min_length=1, max_length=100)],
    user: AuthenticatedUser,
    db: DatabaseSession,
    model: Annotated[EmbeddingModel, Query()] = "glove",
    topn: Annotated[int, Query(ge=1, le=100)] = 10,
) -> dict[str, Any]:
    """Return nearest terms, checking document ownership even for GloVe."""
    _owned_document(db, document_id, user.id)
    vectors = _embedding_vectors(model, user, document_id)
    try:
        similar = most_similar(vectors, word, topn)
    except (OutOfVocabularyError, ValueError) as error:
        raise _embedding_error(error) from error
    return {
        "document_id": document_id,
        "model": model,
        "word": word,
        "similar": similar,
    }


@router.get("/embeddings/similarity")
def embeddings_similarity(
    w1: Annotated[str, Query(min_length=1, max_length=100)],
    w2: Annotated[str, Query(min_length=1, max_length=100)],
    db: DatabaseSession,
    user: AuthenticatedUser,
    model: Annotated[EmbeddingModel, Query()] = "glove",
    document_id: Annotated[int, Query(gt=0)] | None = None,
) -> dict[str, Any]:
    """Return cosine similarity; local models require an owned document ID."""
    if document_id is not None:
        _owned_document(db, document_id, user.id)
    vectors = _embedding_vectors(model, user, document_id)
    try:
        score = cosine_similarity(vectors, w1, w2)
    except (OutOfVocabularyError, ValueError) as error:
        raise _embedding_error(error) from error
    return {"model": model, "w1": w1, "w2": w2, "cosine_similarity": score}


@router.get("/embeddings/analogy")
def embeddings_analogy(
    a: Annotated[str, Query(min_length=1, max_length=100)],
    b: Annotated[str, Query(min_length=1, max_length=100)],
    c: Annotated[str, Query(min_length=1, max_length=100)],
    db: DatabaseSession,
    user: AuthenticatedUser,
    model: Annotated[EmbeddingModel, Query()] = "glove",
    document_id: Annotated[int, Query(gt=0)] | None = None,
    topn: Annotated[int, Query(ge=1, le=100)] = 10,
) -> dict[str, Any]:
    """Solve a - b + c using a selected embedding vocabulary."""
    if document_id is not None:
        _owned_document(db, document_id, user.id)
    vectors = _embedding_vectors(model, user, document_id)
    try:
        candidates = solve_analogy(vectors, a, b, c, topn)
    except (OutOfVocabularyError, ValueError) as error:
        raise _embedding_error(error) from error
    return {
        "model": model,
        "expression": f"{a} - {b} + {c}",
        "candidates": candidates,
    }


@router.get("/embeddings/compare")
def embeddings_compare(
    word: Annotated[str, Query(min_length=1, max_length=100)],
    document_id: Annotated[int, Query(gt=0)],
    db: DatabaseSession,
    user: AuthenticatedUser,
    topn: Annotated[int, Query(ge=1, le=100)] = 5,
) -> dict[str, Any]:
    """Show available Word2Vec and GloVe neighbours side by side."""
    _owned_document(db, document_id, user.id)
    comparison: dict[str, Any] = {}
    for model in ("cbow", "skipgram", "glove"):
        try:
            vectors = _embedding_vectors(model, user, document_id)
            comparison[model] = {"similar": most_similar(vectors, word, topn)}
        except HTTPException as error:
            comparison[model] = {"message": error.detail, "similar": []}
        except (OutOfVocabularyError, ValueError) as error:
            comparison[model] = {"message": str(error), "similar": []}
    return {"document_id": document_id, "word": word, "models": comparison}


@router.get("/embeddings/projection")
def embeddings_projection(
    document_id: Annotated[int, Query(gt=0)],
    model: Annotated[EmbeddingModel, Query()],
    db: DatabaseSession,
    user: AuthenticatedUser,
    method: Annotated[str, Query(pattern="^(pca|tsne|umap)$")] = "pca",
    dims: Annotated[int, Query(ge=2, le=3)] = 2,
    top_n: Annotated[int, Query(ge=2, le=1000)] = 100,
) -> dict[str, Any]:
    """Project frequent embedding terms and attach deterministic KMeans labels."""
    _owned_document(db, document_id, user.id)
    vectors = _embedding_vectors(model, user, document_id)
    try:
        output = project_vectors(vectors, method, dims, top_n)
    except RuntimeError as error:
        raise HTTPException(status_code=501, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "document_id": document_id,
        "model": model,
        "method": method,
        "dims": dims,
        **output,
    }
