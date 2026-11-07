"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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
    classes,
    documents,
    lab,
    quizzes,
    rag_playground,
    search,
    study,
    transformers,
)
from app.services.rag.providers import provider_cooldown_status

settings = get_settings()
settings.validate_database_backend()
settings.validate_auth_settings()
configure_logging(settings.backend_log_level)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Log application startup and shutdown."""
    logger.info("Backend application starting")
    yield
    logger.info("Backend application stopping")


app = FastAPI(
    title="AI Study Assistant API",
    version="0.1.0",
    lifespan=lifespan,
)
rate_limit_cache = create_cache(settings)
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
app.include_router(analytics.router)
app.include_router(documents.router)
app.include_router(classes.router)
app.include_router(lab.router)
app.include_router(rag_playground.router)
app.include_router(search.router)
app.include_router(chat.router)
app.include_router(quizzes.router)
app.include_router(study.router)
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
