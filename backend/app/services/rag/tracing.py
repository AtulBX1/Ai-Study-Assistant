"""Optional Langfuse tracing without a runtime dependency requirement."""

import logging
from typing import Any

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


def trace_chat(
    *,
    question: str,
    answer: str,
    provider: str,
    mode: str,
    grounding_score: float,
    settings: Settings | None = None,
) -> None:
    """Send minimal generation metadata when Langfuse credentials are configured."""
    runtime_settings = settings or get_settings()
    public_key = runtime_settings.langfuse_public_key
    secret_key = runtime_settings.langfuse_secret_key
    if not public_key or not secret_key:
        return
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            host=runtime_settings.langfuse_host,
        )
        generation: Any = client.start_generation(
            name="rag-chat",
            input=question,
            output=answer,
            metadata={
                "provider": provider,
                "mode": mode,
                "grounding_score": grounding_score,
            },
        )
        if hasattr(generation, "end"):
            generation.end()
        if hasattr(client, "flush"):
            client.flush()
    except (ImportError, AttributeError, TypeError, ValueError, RuntimeError) as error:
        logger.debug("Optional Langfuse trace skipped: %s", error)
