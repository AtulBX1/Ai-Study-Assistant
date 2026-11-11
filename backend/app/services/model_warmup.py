"""Non-blocking background initialization for local inference models."""

import logging
import threading

from app.core.config import get_settings
from app.services.embeddings import get_embedding_service
from app.services.reranker import get_cross_encoder_reranker
from app.services.transformer_inference import _load_qa

logger = logging.getLogger(__name__)


def _warm_models() -> None:
    loaders = (
        ("embedding", lambda: get_embedding_service()._load_model()),
        ("reranker", lambda: get_cross_encoder_reranker()._load_model()),
        ("qa", _load_qa),
    )
    for model_name, load_model in loaders:
        try:
            load_model()
            logger.info("Warmed local %s model", model_name)
        except Exception:
            logger.exception("Could not warm local %s model", model_name)


def start_model_warmup() -> threading.Thread | None:
    """Start model loading in a daemon thread unless explicitly disabled."""
    if get_settings().skip_model_warmup:
        logger.info("Local model warm-up is disabled")
        return None
    thread = threading.Thread(
        target=_warm_models,
        name="local-model-warmup",
        daemon=True,
    )
    thread.start()
    return thread
