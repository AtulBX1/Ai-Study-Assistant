"""The editable sample evaluation set has the requested labeled format."""

import json
from pathlib import Path


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
