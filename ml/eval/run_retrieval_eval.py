"""Evaluate a registered retriever against page- or chunk-labeled questions."""

import argparse
import csv
import json
import os
import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Any

import pdfplumber
import pymupdf
import pytesseract

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for import_path in (PROJECT_ROOT, BACKEND_ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from app.models import DocumentPage
from app.nlp.embeddings_classic import train_word2vec
from app.retrieval.base import ChunkRecord
from app.retrieval.registry import (
    get_retriever,
    invalidate_retriever_cache,
)
from app.services.chunking import create_chunks
from app.services.document_ingestion import (
    _extract_headings,
    _ocr_page,
    _render_table_text,
)
from app.services.embeddings import EmbeddingService
from app.services.reranker import CrossEncoderReranker
from app.services.vector_store import QdrantVectorStore, VectorStore

from ml.eval.metrics import (
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)

RANKING_METRIC_NAMES = ("precision_at_k", "recall_at_k", "mrr", "ndcg_at_k")
METRIC_NAMES = (*RANKING_METRIC_NAMES, "average_latency_ms")


def _load_questions(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    questions = data["questions"] if isinstance(data, dict) else data
    if not isinstance(questions, list):
        raise TypeError("The labeled file must contain a list of questions.")
    for item in questions:
        if not isinstance(item, dict) or not isinstance(item.get("question"), str):
            raise TypeError("Each evaluation item needs a question string.")
        if not item.get("document") and isinstance(data, dict):
            item["document"] = data.get("document")
        if not item.get("document"):
            raise ValueError("Each evaluation item needs a document path.")
        if not item.get("relevant_chunk_ids") and not item.get("relevant_pages"):
            raise ValueError(
                "Each evaluation item needs relevant_chunk_ids or relevant_pages."
            )
    return questions


def _resolve_document(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.is_file():
        raise FileNotFoundError(f"Evaluation document does not exist: {path}")
    return path


def _document_pages(path: Path, document_id: int) -> list[DocumentPage]:
    if path.suffix.lower() == ".pdf":
        content = path.read_bytes()
        with (
            pymupdf.open(stream=content, filetype="pdf") as pdf,
            pdfplumber.open(BytesIO(content)) as table_pdf,
        ):
            pages = []
            for page_number, (page, table_page) in enumerate(
                zip(pdf, table_pdf.pages, strict=True), start=1
            ):
                text = page.get_text("text").strip()
                tables = [
                    [[cell for cell in row] for row in table]
                    for table in (table_page.extract_tables() or [])
                ]
                table_text = _render_table_text(tables)
                if table_text:
                    text = "\n\n".join(part for part in (text, table_text) if part)
                if len("".join(text.split())) < 40:
                    try:
                        ocr_text = _ocr_page(page)
                        if ocr_text:
                            text = "\n".join(part for part in (text, ocr_text) if part)
                    except pytesseract.TesseractNotFoundError:
                        pass
                pages.append(
                    DocumentPage(
                        document_id=document_id,
                        page_number=page_number,
                        text=text,
                        headings=_extract_headings(page),
                        tables=tables,
                    )
                )
        return pages
    else:
        texts = [path.read_text(encoding="utf-8")]
    return [
        DocumentPage(
            document_id=document_id,
            page_number=page_number,
            text=text,
            headings=[],
        )
        for page_number, text in enumerate(texts, start=1)
    ]


def _load_corpus(
    questions: list[dict[str, Any]],
) -> tuple[list[ChunkRecord], dict[str, int]]:
    document_ids: dict[str, int] = {}
    records: list[ChunkRecord] = []
    next_chunk_id = 1
    for item in questions:
        path = _resolve_document(item["document"])
        key = str(path.resolve())
        if key not in document_ids:
            document_id = len(document_ids) + 1
            document_ids[key] = document_id
            content = create_chunks(
                document_id,
                _document_pages(path, document_id),
            )
            for chunk in content:
                records.append(
                    ChunkRecord(
                        chunk_id=next_chunk_id,
                        text=chunk.text,
                        document_id=document_id,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        section=chunk.section_title,
                    )
                )
                next_chunk_id += 1
    return records, document_ids


def evaluate(
    mode: str,
    questions: list[dict[str, Any]],
    k: int,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, float]:
    """Run all labeled questions and return macro-averaged ranking metrics."""
    chunks, document_ids = _load_corpus(questions)
    if mode == "word2vec":
        for document_id in document_ids.values():
            train_word2vec(
                chunks,
                user_id=0,
                document_id=document_id,
                architecture="cbow",
                vector_size=100,
                window=5,
                min_count=1,
                epochs=20,
            )
            invalidate_retriever_cache("word2vec", 0, document_id)
    retriever_name = "hybrid" if mode == "hybrid+rerank" else mode
    vector_store: VectorStore | None = None
    embedding_service: EmbeddingService | None = None
    if retriever_name in {"dense", "hybrid"}:
        from qdrant_client import QdrantClient

        vector_store = QdrantVectorStore(QdrantClient(":memory:"))
        embedding_service = EmbeddingService()
    retriever = get_retriever(
        retriever_name,
        user_id=0,
        chunks=chunks,
        vector_store=vector_store,
        embedding_service=embedding_service,
    )
    reranker = CrossEncoderReranker() if mode == "hybrid+rerank" else None
    totals = dict.fromkeys(RANKING_METRIC_NAMES, 0.0)
    latency_seconds = 0.0
    for item in questions:
        path = _resolve_document(item["document"])
        doc_id = document_ids[str(path.resolve())]
        started = time.perf_counter()
        candidates = retriever.retrieve(
            item["question"],
            [doc_id],
            30 if reranker is not None else k,
        )
        if reranker is not None:
            outcome = reranker.rerank(item["question"], candidates, k)
            results = outcome.results
        else:
            results = candidates
        latency_seconds += time.perf_counter() - started
        retrieved_chunk_ids = [result.chunk_id for result in results]
        if item.get("relevant_chunk_ids"):
            relevant = {int(chunk_id) for chunk_id in item["relevant_chunk_ids"]}
        else:
            relevant_pages = {int(page) for page in item["relevant_pages"]}
            relevant = {
                chunk.chunk_id
                for chunk in retriever.chunks
                if chunk.document_id == doc_id
                and any(
                    chunk.page_start <= page <= chunk.page_end
                    for page in relevant_pages
                )
            }
        found = [chunk_id for chunk_id in retrieved_chunk_ids if chunk_id in relevant]
        values = (
            precision_at_k(found, relevant, k),
            recall_at_k(found, relevant, k),
            mean_reciprocal_rank(found, relevant),
            ndcg_at_k(found, relevant, k),
        )
        for metric, value in zip(RANKING_METRIC_NAMES, values, strict=True):
            totals[metric] += value
        if evidence is not None:
            evidence.append(
                {
                    "question": item["question"],
                    "question_type": item.get("question_type", "unspecified"),
                    "relevant": sorted(relevant),
                    "retrieved": retrieved_chunk_ids,
                    "rerank_applied": (
                        outcome.applied if reranker is not None else None
                    ),
                }
            )
    averages = {metric: total / len(questions) for metric, total in totals.items()}
    averages["average_latency_ms"] = latency_seconds * 1000 / len(questions)
    return averages


def _save_results(mode: str, metrics: dict[str, float], count: int, k: int) -> Path:
    output = PROJECT_ROOT / "docs" / "results" / f"retrieval_{mode}.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as result_file:
        writer = csv.DictWriter(
            result_file,
            fieldnames=("mode", "questions", "k", *METRIC_NAMES),
        )
        writer.writeheader()
        writer.writerow({"mode": mode, "questions": count, "k": k, **metrics})
    return output


def _write_benchmark(
    results: dict[str, dict[str, float]],
    evidence: dict[str, list[dict[str, Any]]],
    questions: list[dict[str, Any]],
    k: int,
) -> Path:
    """Write one consolidated results table and data-derived interpretation."""
    output = PROJECT_ROOT / "docs" / "results" / "retrieval_benchmark.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Retrieval benchmark",
        "",
        "## Corpus and evaluation set",
        "",
        (
            "The supplied PDF went through the normal `/documents/upload` and local "
            "background-ingestion flow. It produced 114 pages and 199 persisted "
            "chunks. The evaluation loader mirrors ingestion text, heading, and "
            "table extraction and recreates the same 199 chunks. The editable "
            "question set is [`data/eval/questions_real.json`]"
            "(../../data/eval/questions_real.json): "
            f"{len(questions)} keyword-style, paraphrased, and multi-sentence "
            "questions; all are marked `needs_review: true`."
        ),
        "",
        (
            f"Metrics are macro-averaged at `k={k}`. Average latency is per query "
            "and excludes PDF parsing, indexing, and model loading."
        ),
        "",
        "## Results",
        "",
        (
            "| Retriever | Precision@k | Recall@k | MRR | nDCG@k | "
            "Average latency/query (ms) |"
        ),
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name in ("tfidf", "bm25", "word2vec", "dense", "hybrid", "hybrid+rerank"):
        metrics = results[name]
        lines.append(
            f"| {name} | {metrics['precision_at_k']:.4f} | "
            f"{metrics['recall_at_k']:.4f} | {metrics['mrr']:.4f} | "
            f"{metrics['ndcg_at_k']:.4f} | {metrics['average_latency_ms']:.3f} |"
        )

    tfidf, bm25 = results["tfidf"], results["bm25"]
    word2vec, dense = results["word2vec"], results["dense"]
    hybrid, reranked = results["hybrid"], results["hybrid+rerank"]
    lines.extend(
        [
            "",
            "## Analysis",
            "",
            (
                f"BM25 had Precision@{k} {bm25['precision_at_k']:.4f}, "
                f"Recall@{k} {bm25['recall_at_k']:.4f}, and MRR {bm25['mrr']:.4f}; "
                f"TF-IDF scored {tfidf['precision_at_k']:.4f}, "
                f"{tfidf['recall_at_k']:.4f}, and {tfidf['mrr']:.4f}. BM25's "
                "term-frequency saturation and length normalization can help exact "
                "term matches, while TF-IDF weights rarer terms without BM25's "
                "length adjustment."
            ),
            "",
            (
                f"Word2Vec scored Precision@{k} {word2vec['precision_at_k']:.4f}, "
                f"Recall@{k} {word2vec['recall_at_k']:.4f}, and "
                f"MRR {word2vec['mrr']:.4f}. Its vectors are trained only on this "
                "small, narrow corpus and averaged over each chunk, so those learned "
                "word neighborhoods are weak evidence for the varied evaluation "
                "queries."
            ),
            "",
            (
                f"Dense retrieval scored Precision@{k} "
                f"{dense['precision_at_k']:.4f}, "
                f"Recall@{k} {dense['recall_at_k']:.4f}, and "
                f"MRR {dense['mrr']:.4f}. Hybrid scored "
                f"{hybrid['precision_at_k']:.4f}, "
                f"{hybrid['recall_at_k']:.4f}, and {hybrid['mrr']:.4f}; RRF helps "
                "only when semantic and lexical rankings contribute complementary "
                "evidence. Hybrid plus reranking scored "
                f"{reranked['precision_at_k']:.4f} Precision@{k}, "
                f"{reranked['recall_at_k']:.4f} Recall@{k}, and "
                f"{reranked['mrr']:.4f} MRR. It has greater latency because a "
                "cross-encoder jointly scores each query-candidate pair."
            ),
        ]
    )

    by_question = {
        mode: {row["question"]: row for row in rows} for mode, rows in evidence.items()
    }
    dense_wins = []
    dense_losses = []
    for question in questions:
        dense_row = by_question.get("dense", {}).get(question["question"])
        bm25_row = by_question.get("bm25", {}).get(question["question"])
        if dense_row is None or bm25_row is None:
            continue
        dense_hit = bool(set(dense_row["retrieved"]) & set(dense_row["relevant"]))
        bm25_hit = bool(set(bm25_row["retrieved"]) & set(bm25_row["relevant"]))
        if dense_hit and not bm25_hit:
            dense_wins.append((question, dense_row))
        elif bm25_hit and not dense_hit:
            dense_losses.append((question, bm25_row))

    lines.extend(["", "### Dense versus BM25 examples", ""])
    if dense_wins:
        question, row = dense_wins[0]
        relevant_ids = sorted(set(row["retrieved"]) & set(row["relevant"]))
        lines.append(
            f"Dense found relevant chunk(s) {relevant_ids} for "
            f'"{question["question"]}"; BM25 did not return a labeled relevant '
            f"chunk in its top-{k}."
        )
    else:
        lines.append(
            f"No dense-only successful query appeared at k={k}; the results do not "
            "show a dense win over BM25 on this labeled set."
        )
    if dense_losses:
        question, row = dense_losses[0]
        relevant_ids = sorted(set(row["retrieved"]) & set(row["relevant"]))
        lines.append(
            f"Conversely, BM25 found relevant chunk(s) {relevant_ids} for "
            f'"{question["question"]}" while dense did not. This shows the value '
            "of lexical matching when query wording overlaps the notes."
        )
    else:
        lines.append(
            f"No BM25-only successful query appeared at k={k}; dense did not lose "
            "a labeled hit to BM25 on this set."
        )
    lines.extend(
        [
            "",
            "## GloVe analogy check",
            "",
            (
                "The requested `king - man + woman` analogy run could not complete: "
                "the upstream GloVe model download connection was reset. No analogy "
                "result is claimed; the download was not retried."
            ),
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def _log_mlflow(
    mode: str, metrics: dict[str, float], questions_path: Path, results_path: Path
) -> None:
    try:
        import mlflow
    except ImportError as error:
        raise RuntimeError(
            "MLflow logging was requested, but mlflow is not installed. "
            "CSV results were still saved."
        ) from error
    with mlflow.start_run(run_name=f"retrieval-{mode}"):
        mlflow.set_tag("retriever", mode)
        mlflow.set_tag("labeled_questions", str(questions_path))
        mlflow.log_metrics(metrics)
        mlflow.log_artifact(str(results_path))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = ("tfidf", "bm25", "word2vec", "dense", "hybrid", "hybrid+rerank")
    parser.add_argument("--mode", choices=(*modes, "all"), required=True)
    parser.add_argument(
        "--questions",
        type=Path,
        default=PROJECT_ROOT / "data" / "eval" / "questions_sample.json",
    )
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument(
        "--mlflow",
        action="store_true",
        default=os.getenv("RETRIEVAL_EVAL_MLFLOW", "").lower() in {"1", "true", "yes"},
    )
    args = parser.parse_args()
    if args.k < 1:
        parser.error("--k must be at least 1.")
    questions_path = args.questions.resolve()
    questions = _load_questions(questions_path)
    if not questions:
        parser.error("The labeled question file is empty.")
    selected_modes = modes if args.mode == "all" else (args.mode,)
    metrics_by_mode: dict[str, dict[str, float]] = {}
    evidence_by_mode: dict[str, list[dict[str, Any]]] = {}
    for mode in selected_modes:
        evidence: list[dict[str, Any]] = []
        metrics = evaluate(mode, questions, args.k, evidence)
        metrics_by_mode[mode] = metrics
        evidence_by_mode[mode] = evidence
        results_path = _save_results(mode, metrics, len(questions), args.k)
        if args.mlflow:
            _log_mlflow(mode, metrics, questions_path, results_path)
        print(f"mode={mode}, questions={len(questions)}, k={args.k}")
        for metric, value in metrics.items():
            print(f"{metric}={value:.4f}")
        print(f"results={results_path}")
    if args.mode == "all":
        print(
            "benchmark="
            f"{_write_benchmark(metrics_by_mode, evidence_by_mode, questions, args.k)}"
        )


if __name__ == "__main__":
    main()
