"""CI-safe tests for stratified quality-report chunk sampling."""

from types import SimpleNamespace

import pytest

from scripts.quiz_quality import require_minimum_chunks, sample_chunks
from scripts.quiz_rating import accepted_classic_questions, score_ratings


def test_quality_sampler_spans_pages_and_sections_without_repeats():
    chunks = [
        SimpleNamespace(
            id=index,
            page=index + 1,
            page_start=index + 1,
            page_end=index + 1,
            section=f"Section {index % 4}",
            chunk_index=index,
            text=(
                "Researchers study language and build computational models for "
                "many practical applications in education and communication "
                "across diverse academic and professional settings. "
                "Computational systems process text and identify useful patterns "
                "across large collections of educational documents. "
                "Researchers compare these methods and evaluate their effects "
                "on communication and learning outcomes across several different "
                "student and researcher communities."
            ),
        )
        for index in range(100)
    ]
    selected = sample_chunks(chunks, limit=20)
    assert len(selected) == 20
    assert len({item.id for item in selected}) == 20
    assert min(item.page for item in selected) <= 4
    assert max(item.page for item in selected) >= 97
    assert {item.section for item in selected} == {
        "Section 0",
        "Section 1",
        "Section 2",
        "Section 3",
    }


def test_quality_run_requires_twenty_chunks():
    with pytest.raises(ValueError, match="at least 20"):
        require_minimum_chunks(2, 19)
    require_minimum_chunks(2, 20)


def test_rating_sheet_reader_counts_good_percentage():
    sheet = (
        "| # | Question | Rating (good / ok / bad) |\n"
        "|---:|---|---|\n"
        "| 1 | Which word | good |\n"
        "| 2 | Another | ok |\n"
        "| 3 | Third | bad |\n"
    )
    assert score_ratings(sheet) == (1, 3, 100 / 3)


def test_rating_export_parser_only_selects_classic_accepted_rows():
    report = (
        "## classic\n### Accepted examples\n- p.1 (chunk 1): Good? -> term\n"
        "### Rejected examples\n- p.1 bad row\n## llm\n"
        "### Accepted examples\n- p.2 (chunk 2): Ignore? -> term\n"
    )
    assert accepted_classic_questions(report) == ["p.1 (chunk 1): Good? -> term"]
