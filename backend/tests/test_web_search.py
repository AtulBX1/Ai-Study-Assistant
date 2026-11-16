from app.core.config import Settings
from app.services.rag.prompts import build_grounded_context, build_system_prompt
from app.services.web_search import search_web


def test_grounded_context_has_separate_delimited_untrusted_sources():
    context = build_grounded_context(
        [
            {
                "chunk_id": 7,
                "document_title": "notes.pdf",
                "page": 2,
                "text": "Note text",
            }
        ],
        [
            {
                "title": "Page",
                "url": "https://example.test/a",
                "domain": "example.test",
                "snippet": "Web text",
            }
        ],
    )
    assert "[YOUR NOTES]" in context and "[/YOUR NOTES]" in context
    assert "[chunk 7, notes.pdf, p.2]" in context
    assert "[WEB]" in context and "[/WEB]" in context
    assert "Web text" in context
    assert "untrusted" in build_system_prompt().lower()


def test_search_is_off_without_key_or_daily_allowance():
    result, notice = search_web("short topic", Settings(web_search_api_key=None))
    assert result == []
    assert "continuing with your notes only" in notice
