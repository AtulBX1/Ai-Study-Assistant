"""Transparent heuristic difficulty labels for extracted document chunks."""

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pymupdf
from app.nlp.preprocessing import normalize_text, regex_tokenize, sentence_segmentation
from app.services.chunking import create_chunks

from ml.sequence_models.data import PROJECT_ROOT, write_json

TECHNICAL_SUFFIXES = (
    "tion",
    "sion",
    "ology",
    "metric",
    "ization",
    "ence",
    "ance",
    "ity",
    "ics",
    "graphy",
)


def extract_pdf_chunks(pdf_path: Path, chunk_size: int = 400) -> list[dict[str, Any]]:
    """Extract searchable text from a PDF and reuse the Step 3 chunker."""
    from types import SimpleNamespace

    pages: list[SimpleNamespace] = []
    with pymupdf.open(pdf_path) as document:
        for page_number, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            if text:
                pages.append(
                    SimpleNamespace(
                        page_number=page_number,
                        text=text,
                        headings=[],
                    )
                )
    chunks = create_chunks(0, pages, chunk_size=chunk_size, overlap=40)
    return [
        {
            "chunk_index": chunk.chunk_index,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "text": normalize_text(chunk.text),
        }
        for chunk in chunks
    ]


def label_chunks(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Score readability, corpus-relative rarity, sentence length, and technical density."""
    if not chunks:
        return []
    token_lists = [regex_tokenize(str(chunk["text"])) for chunk in chunks]
    document_frequency: Counter[str] = Counter()
    for tokens in token_lists:
        document_frequency.update({token.lower() for token in tokens})
    document_count = len(chunks)
    scored: list[dict[str, Any]] = []
    for chunk, tokens in zip(chunks, token_lists, strict=True):
        text = str(chunk["text"])
        sentences = sentence_segmentation(text) or [text]
        words = [
            token for token in tokens if any(character.isalpha() for character in token)
        ]
        sentence_words = [
            sum(
                any(character.isalpha() for character in token)
                for token in regex_tokenize(sentence)
            )
            for sentence in sentences
        ]
        average_sentence_length = sum(sentence_words) / max(len(sentence_words), 1)
        syllables = sum(_syllables(word) for word in words)
        readability = (
            206.835
            - 1.015 * len(words) / max(len(sentences), 1)
            - 84.6 * syllables / max(len(words), 1)
        )
        rarity = sum(
            math.log((document_count + 1) / (document_frequency[token.lower()] + 1))
            for token in words
        ) / max(len(words), 1)
        technical_density = sum(
            token.lower().endswith(TECHNICAL_SUFFIXES) for token in words
        ) / max(len(words), 1)
        scored.append(
            {
                **chunk,
                "heuristics": {
                    "flesch_reading_ease": round(readability, 4),
                    "term_rarity": round(rarity, 4),
                    "average_sentence_length": round(average_sentence_length, 4),
                    "technical_term_density": round(technical_density, 4),
                },
                "difficulty_score": 0.0,
            }
        )
        scored[-1]["difficulty_score"] = round(
            max(0.0, (100.0 - readability) / 100.0)
            + rarity
            + average_sentence_length / 40.0
            + technical_density * 3.0,
            4,
        )
    ranked = sorted(
        range(len(scored)),
        key=lambda index: (scored[index]["difficulty_score"], index),
    )
    first_cutoff = (len(ranked) + 2) // 3
    second_cutoff = (2 * len(ranked) + 2) // 3
    for rank, index in enumerate(ranked):
        scored[index]["label"] = (
            "easy"
            if rank < first_cutoff
            else "medium" if rank < second_cutoff else "hard"
        )
    for item in scored:
        item["label_type"] = "weak_heuristic"
    return scored


def save_weak_labels(
    chunks: list[dict[str, Any]],
    output_path: Path = PROJECT_ROOT / "data" / "labels" / "difficulty_weak.json",
) -> list[dict[str, Any]]:
    """Save weak labels with their heuristic provenance for later human/LLM review."""
    labeled = label_chunks(chunks)
    write_json(
        output_path,
        {
            "source": "weak_heuristic",
            "labels_are_weak": True,
            "heuristics": [
                "Flesch reading ease",
                "inverse document-frequency term rarity",
                "average sentence length",
                "technical-term suffix density",
            ],
            "chunks": labeled,
        },
    )
    return labeled


def _syllables(word: str) -> int:
    """Approximate English syllable count for a transparent readability heuristic."""
    groups = re.findall(r"[aeiouy]+", word.lower())
    count = len(groups)
    if word.lower().endswith("e") and count > 1:
        count -= 1
    return max(count, 1)
