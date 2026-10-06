"""Authenticated preprocessing lab endpoints."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models import Document, DocumentPage, User
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
