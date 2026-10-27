"""Lightweight, local-only grounding checks and answer explanations."""

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import Settings, get_settings

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'-]*")
_SENTENCE = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")
_STOP_WORDS = frozenset(
    "a an and are as at be been being but by for from had has have he her him his "
    "i in is it its of on or our she that the their them they this those to was "
    "we were what when where which who with you your".split()
)


def split_sentences(text: str) -> list[str]:
    """Split answer text without requiring NLP resources."""
    return [
        match.group().strip()
        for match in _SENTENCE.finditer(text)
        if match.group().strip()
    ]


def _terms(text: str) -> list[str]:
    return [
        token.casefold()
        for token in _TOKEN.findall(text)
        if token.casefold() not in _STOP_WORDS and len(token) > 1
    ]


def _highlight(sentence: str, chunk_text: str) -> dict[str, int] | None:
    """Return source-local offsets spanning the overlapping answer keywords."""
    answer_terms = set(_terms(sentence))
    matches = [
        (match.start(), match.end())
        for match in _TOKEN.finditer(chunk_text)
        if match.group().casefold() in answer_terms
    ]
    if not matches:
        return None
    return {"start": matches[0][0], "end": matches[-1][1]}


@lru_cache(maxsize=1)
def _local_sentence_encoder(model_root: str, model_name: str) -> Any | None:
    """Load the existing embedding model only when its complete local cache exists."""
    root = Path(model_root).expanduser()
    cache_name = "models--" + model_name.replace("/", "--")
    snapshots = root / cache_name / "snapshots"
    candidates = sorted(snapshots.iterdir(), reverse=True) if snapshots.is_dir() else []
    model_path = next(
        (path for path in candidates if (path / "model.safetensors").is_file()), None
    )
    if model_path is None:
        return None
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(str(model_path), device="cpu", local_files_only=True)


def sentence_similarity_pairs(
    sentences: list[str], chunks: list[dict[str, Any]], settings: Settings | None = None
) -> list[list[float]]:
    """Compute cosine similarity using local sentence embeddings when available."""
    runtime_settings = settings or get_settings()
    texts = [str(chunk.get("text", "")) for chunk in chunks]
    try:
        model = _local_sentence_encoder(
            runtime_settings.hf_home, runtime_settings.embedding_model_name
        )
        if model is None:
            return [[0.0 for _ in texts] for _ in sentences]
        vectors = model.encode(
            [*sentences, *texts],
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        answer_vectors = vectors[: len(sentences)]
        chunk_vectors = vectors[len(sentences) :]
        return [
            [max(0.0, float(answer @ evidence)) for evidence in chunk_vectors]
            for answer in answer_vectors
        ]
    except (ImportError, OSError, RuntimeError, ValueError):
        # Offline/CI without embedding artifacts uses the keyword signal only.
        return [[0.0 for _ in texts] for _ in sentences]


def evaluate_grounding(
    answer: str,
    chunks: list[dict[str, Any]],
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Score answer sentences and explain which retrieved evidence supports them."""
    runtime_settings = settings or get_settings()
    clean_answer = re.sub(r"\s*\[[^\]]+,\s*p\.?\d+\]", "", answer)
    sentences = split_sentences(clean_answer)
    sentences = [sentence for sentence in sentences if sentence]
    pairwise = sentence_similarity_pairs(sentences, chunks, runtime_settings)
    threshold = runtime_settings.rag_grounding_sentence_threshold
    supported_sentences: list[dict[str, Any]] = []
    unsupported: list[str] = []
    chunk_usage: dict[int, list[dict[str, Any]]] = {
        index: [] for index in range(len(chunks))
    }
    highlights: dict[int, list[dict[str, int]]] = {
        index: [] for index in range(len(chunks))
    }

    for sentence_index, sentence in enumerate(sentences):
        answer_terms = set(_terms(sentence))
        best_index: int | None = None
        best_similarity = 0.0
        best_overlap = 0.0
        best_support = False
        for chunk_index, chunk in enumerate(chunks):
            text = str(chunk.get("text", ""))
            evidence_terms = set(_terms(text))
            overlap = (
                len(answer_terms & evidence_terms) / len(answer_terms)
                if answer_terms
                else 0.0
            )
            similarity = pairwise[sentence_index][chunk_index]
            supported = (similarity >= threshold and overlap >= 0.12) or overlap >= 0.65
            if (supported, similarity, overlap) > (
                best_support,
                best_similarity,
                best_overlap,
            ):
                best_index = chunk_index
                best_similarity = similarity
                best_overlap = overlap
                best_support = supported
        assessment = {
            "sentence": sentence,
            "supported": best_support,
            "similarity": round(best_similarity, 4),
            "keyword_overlap": round(best_overlap, 4),
        }
        supported_sentences.append(assessment)
        if best_support and best_index is not None:
            chunk_usage[best_index].append(assessment)
            offsets = _highlight(sentence, str(chunks[best_index].get("text", "")))
            if offsets is not None:
                highlights[best_index].append(offsets)
        else:
            unsupported.append(sentence)

    score = (
        sum(item["supported"] for item in supported_sentences) / len(sentences)
        if sentences
        else 1.0
    )
    explained_chunks = []
    for index, chunk in enumerate(chunks):
        explained_chunks.append(
            {
                **chunk,
                "used_sentences": chunk_usage[index],
                "highlight_offsets": highlights[index],
            }
        )
    return {
        "grounding_score": round(score, 4),
        "unsupported_sentences": unsupported,
        "sentence_assessments": supported_sentences,
        "chunks": explained_chunks,
    }
