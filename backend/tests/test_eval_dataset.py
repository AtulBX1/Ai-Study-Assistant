"""The editable sample evaluation set has the requested labeled format."""

import json
from pathlib import Path

import pytest
from ml.eval.run_retrieval_eval import _load_corpus, _load_questions


def test_sample_question_set_has_30_page_labeled_questions() -> None:
    path = (
        Path(__file__).resolve().parents[2] / "data" / "eval" / "questions_sample.json"
    )
    questions = json.loads(path.read_text(encoding="utf-8"))

    assert len(questions) == 30
    assert all(
        item["question"]
        and item["relevant_pages"]
        and item["document"] == "data/samples/text.pdf"
        for item in questions
    )


def test_real_question_set_is_editable_labeled_and_review_flagged() -> None:
    project_root = Path(__file__).resolve().parents[2]
    path = project_root / "data" / "eval" / "questions_real.json"
    questions = _load_questions(path)

    assert len(questions) >= 40
    assert {item["question_type"] for item in questions} == {
        "keyword",
        "paraphrased",
        "multi_sentence",
    }
    assert all(item["needs_review"] for item in questions)
    assert all(item["relevant_chunk_ids"] for item in questions)

    if not (project_root / "data" / "real_docs" / "nlp_notes.pdf").exists():
        pytest.skip("The real PDF is local and intentionally excluded from Git.")
    chunks, _ = _load_corpus(questions)
    assert len(chunks) >= 50
    chunk_ids = {chunk.chunk_id for chunk in chunks}
    assert all(
        int(chunk_id) in chunk_ids
        for item in questions
        for chunk_id in item["relevant_chunk_ids"]
    )
