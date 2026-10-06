"""SQLAlchemy engine construction for local SQLite and production databases."""

from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url

from app.core.config import Settings, get_settings


def create_database_engine(settings: Settings | None = None) -> Engine:
    """Build the configured SQLAlchemy engine for either runtime mode."""
    runtime_settings = settings or get_settings()
    runtime_settings.validate_database_backend()
    url = make_url(runtime_settings.database_url)
    connect_args = {}
    if url.get_backend_name() == "sqlite":
        if url.database not in (None, "", ":memory:"):
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        connect_args["check_same_thread"] = False
    return create_engine(url, connect_args=connect_args, pool_pre_ping=True)
