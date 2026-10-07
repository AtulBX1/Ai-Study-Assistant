"""Evaluate a registered retriever against page- or chunk-labeled questions."""

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

import pymupdf

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
for import_path in (PROJECT_ROOT, BACKEND_ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from app.models import DocumentPage  # noqa: E402
from app.retrieval.base import ChunkRecord  # noqa: E402
from app.retrieval.registry import get_retriever  # noqa: E402
from app.services.chunking import create_chunks  # noqa: E402
from ml.eval.metrics import (  # noqa: E402
    mean_reciprocal_rank,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)

METRIC_NAMES = ("precision_at_k", "recall_at_k", "mrr", "ndcg_at_k")


def _load_questions(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    questions = data["questions"] if isinstance(data, dict) else data
    if not isinstance(questions, list):
        raise ValueError("The labeled file must contain a list of questions.")
    for item in questions:
        if not isinstance(item, dict) or not isinstance(item.get("question"), str):
            raise ValueError("Each evaluation item needs a question string.")
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
        with pymupdf.open(path) as pdf:
            texts = [page.get_text("text") for page in pdf]
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
) -> dict[str, float]:
    """Run all labeled questions and return macro-averaged ranking metrics."""
    chunks, document_ids = _load_corpus(questions)
    retriever = get_retriever(mode, user_id=0, chunks=chunks)
    totals = dict.fromkeys(METRIC_NAMES, 0.0)
    for item in questions:
        path = _resolve_document(item["document"])
        doc_id = document_ids[str(path.resolve())]
        results = retriever.retrieve(item["question"], [doc_id], k)
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
        for metric, value in zip(METRIC_NAMES, values, strict=True):
            totals[metric] += value
    return {metric: total / len(questions) for metric, total in totals.items()}


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
    parser.add_argument("--mode", choices=("tfidf", "bm25"), required=True)
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
    metrics = evaluate(args.mode, questions, args.k)
    results_path = _save_results(args.mode, metrics, len(questions), args.k)
    if args.mlflow:
        _log_mlflow(args.mode, metrics, questions_path, results_path)
    print(f"mode={args.mode}, questions={len(questions)}, k={args.k}")
    print("metric,value")
    for metric, value in metrics.items():
        print(f"{metric},{value:.4f}")
    print(f"results={results_path}")


if __name__ == "__main__":
    main()
