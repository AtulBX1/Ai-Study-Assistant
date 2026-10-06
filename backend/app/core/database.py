"""SQLAlchemy engine construction for local SQLite and production databases."""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import Settings, get_settings


class Base(DeclarativeBase):
    """Base class shared by all SQLAlchemy models."""


def normalize_database_url(database_url: str) -> URL:
    """Use the installed psycopg 3 driver for standard PostgreSQL URLs."""
    url = make_url(database_url)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url


def create_database_engine(settings: Settings | None = None) -> Engine:
    """Build the configured SQLAlchemy engine for either runtime mode."""
    runtime_settings = settings or get_settings()
    runtime_settings.validate_database_backend()
    url = normalize_database_url(runtime_settings.database_url)
    connect_args = {}
    if url.get_backend_name() == "sqlite":
        if url.database not in (None, "", ":memory:"):
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        connect_args["check_same_thread"] = False
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)


engine = create_database_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a database session for one request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
