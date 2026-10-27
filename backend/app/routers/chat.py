"""Chat session management, streaming RAG queries, and feedback endpoints."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models import ChatSession, Message, User
from app.services.rag import RAGChatPipeline

router = APIRouter(prefix="/chat", tags=["chat"])
DatabaseSession = Annotated[Session, Depends(get_db)]
AuthenticatedUser = Annotated[User, Depends(get_current_user)]

pipeline_instance = RAGChatPipeline()


def get_rag_pipeline() -> RAGChatPipeline:
    return pipeline_instance


class CreateSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="New chat", max_length=255)


class SessionResponse(BaseModel):
    id: int
    title: str
    owner_id: int
    created_at: str
    updated_at: str


class MessagePayload(BaseModel):
    id: int
    session_id: int
    role: str
    content: str
    citations: list[dict[str, object]]
    grounding_score: float | None = None
    unsupported_sentences: list[str] = Field(default_factory=list)
    explanation: dict[str, object] = Field(default_factory=dict)
    provider: str | None = None
    latency_ms: float | None = None
    feedback: str | None = None
    feedback_reason: str | None = None
    created_at: str


class SessionDetailResponse(SessionResponse):
    messages: list[MessagePayload]


class PostMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=4000)
    mode: Literal["normal", "simple", "in-depth", "exam-style"] = "normal"
    language: Literal["English", "Hindi", "Punjabi"] = "English"
    doc_ids: list[int] | None = None


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feedback: Literal["thumbs_up", "thumbs_down"]
    reason: str | None = Field(default=None, max_length=1000)


def _get_owned_session(db: Session, session_id: int, user_id: int) -> ChatSession:
    chat_session = db.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.owner_id == user_id,
        )
    )
    if not chat_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found.",
        )
    return chat_session


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(
    request: CreateSessionRequest,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, object]:
    """Create a new chat session owned by the authenticated user."""
    session_obj = ChatSession(
        owner_id=user.id,
        title=request.title.strip() or "New chat",
    )
    db.add(session_obj)
    db.commit()
    db.refresh(session_obj)
    return {
        "id": session_obj.id,
        "title": session_obj.title,
        "owner_id": session_obj.owner_id,
        "created_at": session_obj.created_at.isoformat(),
        "updated_at": session_obj.updated_at.isoformat(),
    }


@router.get("/sessions")
def list_sessions(
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> list[dict[str, object]]:
    """List all chat sessions belonging to the current user."""
    sessions = list(
        db.scalars(
            select(ChatSession)
            .where(ChatSession.owner_id == user.id)
            .order_by(ChatSession.updated_at.desc())
        )
    )
    return [
        {
            "id": s.id,
            "title": s.title,
            "owner_id": s.owner_id,
            "created_at": s.created_at.isoformat(),
            "updated_at": s.updated_at.isoformat(),
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}")
def get_session(
    session_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, object]:
    """Retrieve chat session and message history."""
    chat_session = _get_owned_session(db, session_id, user.id)
    return {
        "id": chat_session.id,
        "title": chat_session.title,
        "owner_id": chat_session.owner_id,
        "created_at": chat_session.created_at.isoformat(),
        "updated_at": chat_session.updated_at.isoformat(),
        "messages": [
            {
                "id": m.id,
                "session_id": m.session_id,
                "role": m.role,
                "content": m.content,
                "citations": m.citations or [],
                "grounding_score": m.grounding_score,
                "unsupported_sentences": m.unsupported_sentences or [],
                "explanation": m.explanation or {},
                "provider": m.provider,
                "latency_ms": m.latency_ms,
                "feedback": m.feedback,
                "feedback_reason": m.feedback_reason,
                "created_at": m.created_at.isoformat(),
            }
            for m in chat_session.messages
        ],
    }


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: int,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> None:
    """Delete a chat session and all its messages."""
    chat_session = _get_owned_session(db, session_id, user.id)
    db.delete(chat_session)
    db.commit()


@router.post("/sessions/{session_id}/messages")
def post_message(
    session_id: int,
    request: PostMessageRequest,
    db: DatabaseSession,
    user: AuthenticatedUser,
    pipeline: Annotated[RAGChatPipeline, Depends(get_rag_pipeline)],
) -> StreamingResponse:
    """Post user question and stream the assistant's response via Server-Sent Events."""
    chat_session = _get_owned_session(db, session_id, user.id)

    # Automatically set session title if this is the first message
    if chat_session.title == "New chat":
        short_title = request.query[:40].strip()
        chat_session.title = short_title if short_title else "Chat"

    # Save user message
    user_msg = Message(
        session_id=chat_session.id,
        role="user",
        content=request.query,
    )
    db.add(user_msg)
    db.commit()

    # Stream the grounded response
    generator = pipeline.stream_chat(
        db=db,
        user_id=user.id,
        session_id=chat_session.id,
        query=request.query,
        mode=request.mode,
        language=request.language,
        doc_ids=request.doc_ids,
    )

    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/messages/{message_id}/feedback")
def submit_feedback(
    message_id: int,
    request: FeedbackRequest,
    db: DatabaseSession,
    user: AuthenticatedUser,
) -> dict[str, object]:
    """Submit thumbs up / down feedback with an optional reason."""
    msg = db.scalar(
        select(Message)
        .join(ChatSession, Message.session_id == ChatSession.id)
        .where(
            Message.id == message_id,
            ChatSession.owner_id == user.id,
        )
    )
    if not msg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Message not found.",
        )

    msg.feedback = request.feedback
    msg.feedback_reason = request.reason
    db.commit()
    db.refresh(msg)

    return {
        "message_id": msg.id,
        "feedback": msg.feedback,
        "reason": msg.feedback_reason,
    }
