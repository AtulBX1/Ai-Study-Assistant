"""Owner-scoped document queries."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models import Document, User
from app.schemas.documents import DocumentResponse

router = APIRouter(prefix="/documents", tags=["documents"])
DatabaseSession = Annotated[Session, Depends(get_db)]
AuthenticatedUser = Annotated[User, Depends(get_current_user)]


@router.get("", response_model=list[DocumentResponse])
def list_documents(db: DatabaseSession, user: AuthenticatedUser) -> list[Document]:
    """Return only documents owned by the authenticated user."""
    return list(
        db.scalars(
            select(Document).where(Document.owner_id == user.id).order_by(Document.id)
        )
    )


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> Document:
    """Fetch a document only when it belongs to the authenticated user."""
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.owner_id == user.id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return document
