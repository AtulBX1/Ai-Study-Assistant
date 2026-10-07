"""Named retriever registry and per-user/document-set index cache."""

import hashlib
from collections import OrderedDict
from collections.abc import Callable, Sequence
from threading import RLock
from typing import TypeVar

from app.retrieval.base import ChunkRecord, Retriever

RetrieverType = TypeVar("RetrieverType", bound=type[Retriever])
_REGISTRY: dict[str, type[Retriever]] = {}
_CACHE: OrderedDict[tuple[str, int, tuple[int, ...], str], Retriever] = OrderedDict()
_CACHE_LOCK = RLock()
_CACHE_CAPACITY = 32


def register_retriever(name: str) -> Callable[[RetrieverType], RetrieverType]:
    """Register a retriever class under a stable lowercase mode name."""

    def register(cls: RetrieverType) -> RetrieverType:
        if not name or name != name.lower():
            raise ValueError("Retriever names must be non-empty lowercase strings.")
        if name in _REGISTRY:
            raise ValueError(f"Retriever {name!r} is already registered.")
        _REGISTRY[name] = cls
        return cls

    return register


def _fingerprint(chunks: Sequence[ChunkRecord]) -> str:
    content = "\n".join(
        f"{chunk.chunk_id}:{chunk.document_id}:{chunk.page_start}:"
        f"{chunk.page_end}:{chunk.section or ''}:{chunk.text}"
        for chunk in chunks
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def get_retriever(
    name: str,
    user_id: int,
    chunks: Sequence[ChunkRecord],
) -> Retriever:
    """Get or build a cache-isolated retriever, rebuilding on content changes."""
    try:
        retriever_class = _REGISTRY[name]
    except KeyError as error:
        raise ValueError(f"Unknown retriever mode: {name}.") from error
    document_ids = tuple(sorted({chunk.document_id for chunk in chunks}))
    key = (name, user_id, document_ids, _fingerprint(chunks))
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            _CACHE.move_to_end(key)
            return cached
        retriever = retriever_class(chunks)
        _CACHE[key] = retriever
        while len(_CACHE) > _CACHE_CAPACITY:
            _CACHE.popitem(last=False)
        return retriever


from app.retrieval.bm25 import BM25Retriever  # noqa: E402,F401
from app.retrieval.tfidf import TfidfRetriever  # noqa: E402,F401
