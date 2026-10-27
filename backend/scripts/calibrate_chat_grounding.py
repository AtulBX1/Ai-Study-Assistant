"""Offline calibration of chat retrieval refusal and answer grounding."""

from __future__ import annotations

import math
import random
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import Settings  # noqa: E402
from app.services.rag.grounding import evaluate_grounding  # noqa: E402
from app.services.reranker import CrossEncoderReranker  # noqa: E402

PDF_PATH = ROOT / "data" / "real_docs" / "nlp_notes.pdf"
REPORT_PATH = ROOT / "docs" / "results" / "chat_grounding.md"


def _chunks_from_pdf(path: Path) -> list[dict[str, Any]]:
    import pymupdf

    document = pymupdf.open(path)
    chunks: list[dict[str, Any]] = []
    for page_index, page in enumerate(document):
        text = " ".join(page.get_text().split())
        if not text:
            continue
        sentences = re.split(r"(?<=[.!?])\s+", text)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence.split()) < 5:
                continue
            chunks.append(
                {
                    "chunk_id": len(chunks) + 1,
                    "document_id": 1,
                    "document_title": path.name,
                    "page": page_index + 1,
                    "text": sentence,
                    "is_private": False,
                }
            )
    return chunks


def _make_questions(
    chunks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rng = random.Random(42)
    usable = [chunk for chunk in chunks if len(chunk["text"].split()) >= 8]
    rng.shuffle(usable)
    in_doc: list[dict[str, Any]] = []
    for chunk in usable:
        sentence = chunk["text"]
        words = re.findall(r"[A-Za-z][A-Za-z'-]+", sentence)
        if not words:
            continue
        keyword = max(words, key=len)
        in_doc.append(
            {
                "question": f"What does the document state about {keyword}?",
                "expected": sentence,
                "answer": sentence,
                "gold_in_document": True,
            }
        )
        if len(in_doc) == 30:
            break
    out_questions = [
        "What is the orbital period of Saturn's moon Enceladus?",
        "What is the chemical formula of hemoglobin?",
        "How many moons orbit the planet Mars?",
        "What is the boiling point of liquid nitrogen?",
        "Who won the 2018 FIFA World Cup?",
        "What is the deepest point in the Pacific Ocean?",
        "How does a nuclear fusion reactor confine plasma?",
        "What is the mass of the Andromeda galaxy?",
        "Which enzyme replicates DNA in human cells?",
        "What is the exchange rate of the euro today?",
        "When did the first powered flight cross the Atlantic?",
        "What is the population of Kyoto this year?",
        "How many rings does Uranus have?",
        "What is the melting point of tungsten?",
        "Which tectonic plate contains the Hawaiian Islands?",
    ]
    out_doc = [
        {
            "question": question,
            "expected": "",
            "answer": "not found in the document",
            "gold_in_document": False,
        }
        for question in out_questions
    ]
    return in_doc, out_doc


def _rank(
    question: str, chunks: list[dict[str, Any]], reranker: CrossEncoderReranker
) -> tuple[list[dict[str, Any]], float | None]:
    from app.retrieval.base import RetrievalResult

    question_terms = {
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z'-]+", question)
        if len(token) > 2
    }
    lexical_candidates = sorted(
        chunks,
        key=lambda chunk: (
            -len(
                question_terms
                & {
                    token.casefold()
                    for token in re.findall(r"[A-Za-z][A-Za-z'-]+", chunk["text"])
                }
            )
        ),
    )[:30]
    candidates = [
        RetrievalResult(
            chunk_id=chunk["chunk_id"],
            text=chunk["text"],
            document_id=1,
            page=chunk["page"],
            page_end=chunk["page"],
            section=None,
            score=float(31 - index),
            rank=index,
        )
        for index, chunk in enumerate(lexical_candidates, start=1)
    ]
    outcome = reranker.rerank(question, candidates, 5)
    by_id = {chunk["chunk_id"]: chunk for chunk in lexical_candidates}
    ranked = []
    for result in outcome.results:
        chunk = dict(by_id[result.chunk_id])
        chunk["retrieval_score"] = result.original_score or result.score
        chunk["rerank_score"] = result.rerank_score
        ranked.append(chunk)
    top_score = ranked[0].get("rerank_score") if ranked else None
    return ranked, top_score


def _write_report(
    rows: list[dict[str, Any]], threshold: float, fallback_note: str
) -> None:
    in_rows = [row for row in rows if row["gold_in_document"]]
    out_rows = [row for row in rows if not row["gold_in_document"]]

    def predicted_refusal(row: dict[str, Any]) -> bool:
        return row["top_rerank_score"] is None or row["top_rerank_score"] < threshold

    correct_refusals = sum(predicted_refusal(row) for row in out_rows)
    missed_refusals = sum(not predicted_refusal(row) for row in out_rows)
    false_refusals = sum(predicted_refusal(row) for row in in_rows)
    scores = sorted(row["grounding_score"] for row in in_rows)
    median = scores[len(scores) // 2] if scores else 0.0
    q1 = scores[len(scores) // 4] if scores else 0.0
    q3 = scores[(3 * len(scores)) // 4] if scores else 0.0
    lines = [
        "# Step 11b chat grounding calibration",
        "",
        f"- PDF: `{PDF_PATH.relative_to(ROOT).as_posix()}` "
        f"({PDF_PATH.stat().st_size:,} bytes).",
        "- Questions: 30 generated from extracted PDF sentences; "
        "15 fixed out-of-domain questions.",
        f"- Retrieval refusal threshold: `{threshold:.4f}` "
        "(top cross-encoder score; missing score refuses).",
        "- In-document false-refusal rate: "
        f"{false_refusals}/{len(in_rows)} "
        f"({false_refusals / max(1, len(in_rows)):.1%}).",
        "- Out-of-document refusal accuracy: "
        f"{correct_refusals}/{len(out_rows)} "
        f"({correct_refusals / max(1, len(out_rows)):.1%}); "
        f"missed refusals: {missed_refusals}.",
        "- In-document answer grounding distribution "
        "(sentence-level supported fraction): "
        f"min {min(scores, default=0):.2f}, Q1 {q1:.2f}, median {median:.2f}, "
        f"Q3 {q3:.2f}, max {max(scores, default=0):.2f}.",
        "",
        "## Notes and limitations",
        "",
        "Questions are deterministic templates, not human-authored or independently "
        "verified labels; in-document expected answers are the source sentences. "
        "The out-of-domain set is not an exhaustive test of the document topic "
        "boundary. This small run is a diagnostic, not a statistically reliable "
        "threshold estimate.",
        "The threshold compares the reranker's raw score (not a calibrated "
        "probability); its scale depends on the local cross-encoder. Candidate "
        "chunks are prefiltered by simple lexical overlap before cross-encoding, "
        "not by the full production hybrid retriever. The selected threshold is "
        "specific to this synthetic question set and must not be treated as a "
        "general accuracy claim.",
        fallback_note,
        "Grounding is a lightweight sentence embedding plus keyword-overlap heuristic; "
        "it can miss paraphrases and logical contradictions. A score is not a truth "
        "guarantee.",
        "",
        "## Per-question diagnostic",
        "",
        "| Set | Question | Rerank score | Refused | Grounding | Unsupported |",
        "|---|---|---:|:---:|---:|---|",
    ]
    for row in rows:
        score = (
            "n/a"
            if row["top_rerank_score"] is None
            else f"{row['top_rerank_score']:.4f}"
        )
        unsupported = "; ".join(row["unsupported_sentences"]).replace("|", "\\|")
        lines.append(
            f"| {'in' if row['gold_in_document'] else 'out'} | "
            f"{row['question']} | {score} | "
            f"{'yes' if predicted_refusal(row) else 'no'} | "
            f"{row['grounding_score']:.2f} | {unsupported} |"
        )
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    if not PDF_PATH.is_file():
        raise SystemExit(f"Real PDF not found: {PDF_PATH}")
    settings = Settings()
    chunks = _chunks_from_pdf(PDF_PATH)
    in_doc, out_doc = _make_questions(chunks)
    if len(in_doc) != 30:
        raise SystemExit(
            "Need 30 in-document questions; extracted only "
            f"{len(in_doc)} source sentences."
        )
    try:
        reranker = CrossEncoderReranker(settings)
        reranker._load_model()
        fallback_note = (
            "The cached local cross-encoder was available and used; "
            "no network access was requested."
        )
    except Exception as error:
        raise SystemExit(
            "Calibration needs the already-cached local cross-encoder; "
            "no download was attempted. "
            f"Loader reported {type(error).__name__}: {error}"
        ) from error
    rows: list[dict[str, Any]] = []
    for item in [*in_doc, *out_doc]:
        ranked, top_score = _rank(item["question"], chunks, reranker)
        answer = item["answer"]
        grounding = evaluate_grounding(answer, ranked, settings)
        rows.append(
            {
                **item,
                "top_rerank_score": top_score,
                "grounding_score": grounding["grounding_score"],
                "unsupported_sentences": grounding["unsupported_sentences"],
            }
        )
    score_values = [
        row["top_rerank_score"] for row in rows if row["top_rerank_score"] is not None
    ]
    thresholds = sorted(
        {0.0, *(math.nextafter(score, math.inf) for score in score_values)}
    )

    def balanced_accuracy(value: float) -> float:
        in_doc_rows = [row for row in rows if row["gold_in_document"]]
        out_doc_rows = [row for row in rows if not row["gold_in_document"]]
        in_recall = sum(
            row["top_rerank_score"] is not None and row["top_rerank_score"] >= value
            for row in in_doc_rows
        ) / max(1, len(in_doc_rows))
        out_recall = sum(
            row["top_rerank_score"] is None or row["top_rerank_score"] < value
            for row in out_doc_rows
        ) / max(1, len(out_doc_rows))
        return (in_recall + out_recall) / 2

    best_threshold = max(
        thresholds, key=lambda value: (balanced_accuracy(value), -value)
    )
    _write_report(rows, best_threshold, fallback_note)
    print(f"Wrote {REPORT_PATH.relative_to(ROOT)}")
    print("In-document: 30; out-of-document: 15")
    print(f"Suggested raw rerank threshold: {best_threshold:.6f}")
    refused_in = sum(
        row["top_rerank_score"] is None or row["top_rerank_score"] < best_threshold
        for row in in_doc
    )
    print(f"In-document false refusals: {refused_in}/30")
    scores = sorted(row["grounding_score"] for row in in_doc)
    print(
        "Grounding distribution min/median/max: "
        f"{min(scores):.2f}/{scores[len(scores) // 2]:.2f}/{max(scores):.2f}"
    )
    refused_out = sum(
        row["top_rerank_score"] is None or row["top_rerank_score"] < best_threshold
        for row in out_doc
    )
    print(f"Out-of-document refusal accuracy: {refused_out}/15")
    unsupported = next(
        (sentence for row in rows for sentence in row["unsupported_sentences"]), None
    )
    print(f"Flagged unsupported example: {unsupported or 'none in this run'}")


if __name__ == "__main__":
    main()
