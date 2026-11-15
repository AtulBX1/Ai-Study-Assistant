"""FastAPI application entry point."""

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.cache import create_cache
from app.core.config import get_settings
from app.logging_config import configure_logging
from app.middleware import RateLimitMiddleware, RequestIdMiddleware
from app.routers import (
    analytics,
    auth,
    chat,
    documents,
    lab,
    public_tests,
    quizzes,
    rag_playground,
    search,
    study,
    syllabus,
    transformers,
)
from app.services.feature_ai import ai_status
from app.services.model_warmup import start_model_warmup
from app.services.rag.providers import provider_cooldown_status

settings = get_settings()
settings.validate_database_backend()
settings.validate_auth_settings()
configure_logging(settings.backend_log_level)
logger = logging.getLogger(__name__)


def _upgrade_local_database(database_url: str) -> str:
    """Apply all local migrations and return the resulting revision."""
    from alembic.config import Config
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    from alembic import command

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    parsed_url = make_url(database_url)
    if parsed_url.drivername.startswith("sqlite"):
        database_path = parsed_url.database
        if database_path and database_path != ":memory:":
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(config, "head")
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            revisions = (
                connection.execute(text("SELECT version_num FROM alembic_version"))
                .scalars()
                .all()
            )
        return ",".join(revisions) or "base"
    finally:
        engine.dispose()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Migrate local databases on application startup, then warm models."""
    logger.info("Backend application starting")
    if settings.backend == "local" and "pytest" not in sys.modules:
        revision = _upgrade_local_database(settings.database_url)
        logger.info("Local database migrated to revision %s", revision)
    start_model_warmup()
    yield
    logger.info("Backend application stopping")


app = FastAPI(
    title="AI Study Assistant API",
    version="0.1.0",
    lifespan=lifespan,
)
rate_limit_cache = create_cache(settings)
app.state.rate_limit_cache = rate_limit_cache
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    cache=rate_limit_cache,
    settings=settings,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)


@app.get("/system/ai-status", tags=["system"])
async def system_ai_status() -> dict:
    """Expose provider readiness without credentials."""
    return ai_status(settings)


app.include_router(analytics.router)
app.include_router(documents.router)
app.include_router(lab.router)
app.include_router(rag_playground.router)
app.include_router(search.router)
app.include_router(chat.router)
app.include_router(quizzes.router)
app.include_router(public_tests.router)
app.include_router(study.router)
app.include_router(syllabus.router)
app.include_router(study.export_router)
app.include_router(transformers.lab_router)
app.include_router(transformers.documents_router)


@app.get("/health", tags=["health"])
async def health() -> dict:
    """Report process health and key-free LLM provider readiness."""
    names = [
        name.strip().lower()
        for name in settings.llm_provider_chain.split(",")
        if name.strip()
    ]
    return {
        "status": "ok",
        "llm": {
            "active_chain": names,
            "providers": {
                name: {
                    "configured": name != "groq" or bool(settings.groq_api_key),
                    "cooldown_until": provider_cooldown_status(name),
                }
                for name in names
            },
        },
    }
