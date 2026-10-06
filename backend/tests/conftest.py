"""Shared isolated database and authentication fixtures."""

from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.config import get_settings
from app.core.database import Base, get_db
from app.main import app


@pytest.fixture
def test_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(test_engine: Engine) -> Generator[Session, None, None]:
    session_factory = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    session = session_factory()
    yield session
    session.close()


@pytest.fixture
def client(test_engine: Engine) -> Generator[TestClient, None, None]:
    session_factory = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    def override_get_db() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def access_token_for(user_id: int) -> str:
    """Create a short-lived signed test access token."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "typ": "access",
            "jti": "test-access-token",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        get_settings().jwt_secret_key,
        algorithm=get_settings().jwt_algorithm,
    )
