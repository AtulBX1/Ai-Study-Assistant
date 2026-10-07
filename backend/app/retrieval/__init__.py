"""Classical retrieval implementations and shared result types."""

from app.retrieval.base import ChunkRecord, RetrievalResult
from app.retrieval.registry import get_retriever, register_retriever

__all__ = [
    "ChunkRecord",
    "RetrievalResult",
    "get_retriever",
    "register_retriever",
]
