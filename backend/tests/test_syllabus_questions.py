from types import SimpleNamespace

from app.services.syllabus.questions import important_questions


def test_question_batch_uses_only_mapped_note_evidence():
    topic = SimpleNamespace(id=9021, title="Routing")
    mapping = SimpleNamespace(page_start=4)
    chunk = SimpleNamespace(
        id=9021,
        page_start=3,
        page=3,
        section="Routing",
        text=(
            "Routing tables store destination paths for forwarding packets. "
            "Routers update these paths when network links change."
        ),
    )
    result = important_questions(topic, [(mapping, chunk)])
    assert result["status"] == "grounded"
    assert [item["type"] for item in result["items"]] == ["short"] * 3 + [
        "long"
    ] * 2 + ["application"]
    assert all(item["evidence_quote"] in chunk.text for item in result["items"])
    assert all(item["label"] == "From your notes (p.4)" for item in result["items"])
    assert important_questions(topic, [(mapping, chunk)])["cached"] is True


def test_missing_notes_stay_explicit_unless_suggestions_enabled():
    topic = SimpleNamespace(id=9022, title="Cryptography")
    assert important_questions(topic, []) == {
        "topic_id": 9022,
        "topic": "Cryptography",
        "status": "no_notes",
        "message": "No notes for this topic",
        "items": [],
    }
    suggestions = important_questions(topic, [], suggest_likely=True)
    assert suggestions["status"] == "unverified"
    assert len(suggestions["items"]) == 6
    assert all(
        item["label"] == "Not from your notes (unverified)"
        for item in suggestions["items"]
    )
