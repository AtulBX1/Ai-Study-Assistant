"""Password hashing and signed JWT helpers."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import HTTPException, status

from app.core.config import Settings, get_settings

password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a password using Argon2id."""
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password without exposing Argon2 parsing errors."""
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_token(
    user_id: int,
    token_type: str,
    expires_in: timedelta,
    settings: Settings | None = None,
) -> tuple[str, str, datetime]:
    """Create a signed JWT and return it with its ID and expiry."""
    config = settings or get_settings()
    config.validate_auth_settings()
    issued_at = datetime.now(UTC)
    expires_at = issued_at + expires_in
    token_id = str(uuid4())
    claims = {
        "sub": str(user_id),
        "typ": token_type,
        "jti": token_id,
        "iat": issued_at,
        "exp": expires_at,
    }
    return (
        jwt.encode(claims, config.jwt_secret_key, algorithm=config.jwt_algorithm),
        token_id,
        expires_at,
    )


def decode_token(token: str, expected_type: str) -> dict[str, object]:
    """Verify a JWT signature, expiry, and intended token type."""
    config = get_settings()
    config.validate_auth_settings()
    try:
        claims = jwt.decode(
            token,
            config.jwt_secret_key,
            algorithms=[config.jwt_algorithm],
            options={"require": ["sub", "typ", "jti", "iat", "exp"]},
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    if claims.get("typ") != expected_type:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return claims


def access_token_subject(token: str) -> str | None:
    """Return a verified access-token subject for rate-limit bucketing."""
    try:
        return str(decode_token(token, "access")["sub"])
    except HTTPException:
        return None
