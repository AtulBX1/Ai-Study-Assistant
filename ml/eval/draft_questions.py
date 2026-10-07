"""Draft editable page-relevance questions from a sample PDF without an LLM."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import pymupdf

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.nlp.preprocessing import sentence_segmentation  # noqa: E402
from app.retrieval.base import preprocess_tokens  # noqa: E402

QUESTION_TEMPLATES = (
    "What does the document say about {term}?",
    "How is {term} described in the document?",
    "Which idea in the document is connected to {term}?",
    "What role does {term} have in the material?",
    "What information about {term} can be found in the document?",
    "How does the document explain {term}?",
)


def draft_questions(pdf_path: Path, count: int = 30) -> list[dict[str, object]]:
    """Make deterministic term-based questions labeled with source page numbers."""
    if count < 1:
        raise ValueError("count must be at least 1.")
    with pymupdf.open(pdf_path) as pdf:
        pages = [page.get_text("text") for page in pdf]

    terms: list[str] = []
    for page_text in pages:
        counts = Counter(preprocess_tokens(page_text))
        terms.extend(
            term
            for term, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
            if len(term) > 2 and term not in terms
        )
    if not terms:
        raise ValueError("The PDF contains no usable terms for draft questions.")

    questions: list[dict[str, object]] = []
    seen: set[str] = set()
    template_index = 0
    while len(questions) < count and template_index < len(QUESTION_TEMPLATES):
        for term_index, term in enumerate(terms):
            template = QUESTION_TEMPLATES[
                (term_index + template_index) % len(QUESTION_TEMPLATES)
            ]
            question = template.format(term=term)
            if question in seen:
                continue
            sentence = next(
                (
                    segment
                    for page_text in pages
                    for segment in sentence_segmentation(page_text)
                    if term in preprocess_tokens(segment)
                ),
                "",
            )
            try:
                document_path = pdf_path.resolve().relative_to(PROJECT_ROOT).as_posix()
            except ValueError:
                document_path = str(pdf_path.resolve())
            questions.append(
                {
                    "question": question,
                    "relevant_pages": [
                        page_number
                        for page_number, page_text in enumerate(pages, start=1)
                        if term in preprocess_tokens(page_text)
                    ],
                    "document": document_path,
                    "source_sentence": sentence,
                }
            )
            seen.add(question)
            if len(questions) == count:
                break
        template_index += 1
    return questions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "pdf",
        nargs="?",
        type=Path,
        default=PROJECT_ROOT / "data" / "samples" / "text.pdf",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "data" / "eval" / "questions_sample.json",
    )
    parser.add_argument("--count", type=int, default=30)
    args = parser.parse_args()
    pdf_path = args.pdf.resolve()
    questions = draft_questions(pdf_path, args.count)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(questions, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(questions)} draft questions to {args.output.resolve()}")


if __name__ == "__main__":
    main()
