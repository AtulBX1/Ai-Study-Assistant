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
from app.routers import auth, classes, documents, lab, search, transformers

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
app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    cache=create_cache(settings),
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
app.include_router(documents.router)
app.include_router(classes.router)
app.include_router(lab.router)
app.include_router(search.router)
app.include_router(transformers.lab_router)
app.include_router(transformers.documents_router)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    """Report that the API process is responding."""
    return {"status": "ok"}
