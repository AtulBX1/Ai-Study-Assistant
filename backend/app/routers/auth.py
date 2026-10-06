"""Registration and JWT authentication endpoints."""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import create_token, decode_token, hash_password, verify_password
from app.models import RefreshToken, User
from app.models.entities import utc_now
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(prefix="/auth", tags=["authentication"])
DatabaseSession = Annotated[Session, Depends(get_db)]


def user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
    )


def issue_tokens(db: Session, user: User) -> TokenResponse:
    settings = get_settings()
    access_token, _, _ = create_token(
        user.id,
        "access",
        timedelta(minutes=settings.access_token_minutes),
        settings,
    )
    refresh_token, token_id, expires_at = create_token(
        user.id,
        "refresh",
        timedelta(days=settings.refresh_token_days),
        settings,
    )
    db.add(
        RefreshToken(
            jti=token_id,
            user_id=user.id,
            expires_at=expires_at,
        )
    )
    db.commit()
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=user_response(user),
    )


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(payload: RegisterRequest, db: DatabaseSession) -> TokenResponse:
    """Create a student account and return its initial tokens."""
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Email is already registered.")
    user = User(
        email=payload.email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role="student",
    )
    db.add(user)
    try:
        db.flush()
        result = issue_tokens(db, user)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Email is already registered."
        ) from exc
    return result


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DatabaseSession) -> TokenResponse:
    """Authenticate a user and issue an access/refresh token pair."""
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return issue_tokens(db, user)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, db: DatabaseSession) -> TokenResponse:
    """Rotate a valid refresh token and revoke its previous instance."""
    claims = decode_token(payload.refresh_token, "refresh")
    token_id = str(claims["jti"])
    token_record = db.scalar(
        select(RefreshToken).where(RefreshToken.jti == token_id).with_for_update()
    )
    user = db.get(User, int(str(claims["sub"])))
    if (
        token_record is None
        or token_record.revoked_at is not None
        or user is None
        or token_record.user_id != user.id
    ):
        raise HTTPException(status_code=401, detail="Refresh token is not active.")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="User is unavailable.")
    token_record.revoked_at = utc_now()
    return issue_tokens(db, user)


@router.post("/logout")
def logout(payload: LogoutRequest, db: DatabaseSession) -> dict[str, str]:
    """Revoke a refresh token so it can no longer renew access."""
    claims = decode_token(payload.refresh_token, "refresh")
    token_record = db.get(RefreshToken, str(claims["jti"]))
    if (
        token_record is None
        or token_record.revoked_at is not None
        or token_record.user_id != int(str(claims["sub"]))
    ):
        raise HTTPException(status_code=401, detail="Refresh token is not active.")
    token_record.revoked_at = utc_now()
    db.commit()
    return {"status": "logged_out"}
