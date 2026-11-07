"""Fake-only acceptance tests for concept graphs and deterministic study plans."""

from datetime import date, timedelta

from sqlalchemy import select

from app.models import (
    Chunk,
    Document,
    DocumentKeyTerm,
    DocumentPage,
    GlossaryTerm,
    StudyPlan,
    StudyPlanItem,
    TopicStat,
    User,
)
from app.services.study.concept_graph import build_concept_graph
from app.services.study.planner import (
    StudyTopic,
    collect_study_topics,
    generate_study_plan,
)
from tests.conftest import access_token_for


def _user(db_session, name: str) -> User:
    user = User(email=f"{name}@example.test", full_name=name, password_hash="unused")
    db_session.add(user)
    db_session.flush()
    return user


def _document(db_session, owner: User, *, private: bool = False) -> Document:
    document = Document(
        owner_id=owner.id,
        title="Fake study material",
        status="ready",
        is_private=private,
    )
    db_session.add(document)
    db_session.flush()
    return document


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token_for(user.id)}"}


def _graph_fixture(db_session, owner: User, *, private: bool = False) -> Document:
    document = _document(db_session, owner, private=private)
    db_session.add_all(
        [
            DocumentPage(
                document_id=document.id,
                page_number=1,
                text=(
                    "Stemming is a type of normalization. "
                    "Stemming uses tokenization. "
                    "Normalization improves tokenization. "
                    "Normalization improves tokenization. "
                    "Orphan appears by itself."
                ),
                headings=[{"text": "Chapter 1"}],
            ),
            DocumentKeyTerm(
                document_id=document.id,
                term="Stemming",
                label="KEYPHRASE",
                page=1,
                source="stored",
            ),
            DocumentKeyTerm(
                document_id=document.id,
                term="normalization",
                label="KEYPHRASE",
                page=1,
                source="stored",
            ),
            DocumentKeyTerm(
                document_id=document.id,
                term="tokenization",
                label="KEYPHRASE",
                page=1,
                source="stored",
            ),
            DocumentKeyTerm(
                document_id=document.id,
                term="Orphan",
                label="KEYPHRASE",
                page=1,
                source="stored",
            ),
            GlossaryTerm(
                owner_id=owner.id,
                document_id=document.id,
                term="Stemming",
                term_key="stemming",
                definition="Stemming reduces inflected words to their roots.",
                page=1,
                evidence_sentence="Stemming is a type of normalization.",
                source="stored",
                importance=2,
            ),
        ]
    )
    db_session.flush()
    return document


def test_graph_evidence_patterns_cooccurrence_isolates_and_limit(db_session):
    owner = _user(db_session, "graph-owner")
    document = _graph_fixture(db_session, owner)

    graph = build_concept_graph(db_session, document=document, owner_id=owner.id)
    limited_graph = build_concept_graph(
        db_session, document=document, owner_id=owner.id, max_nodes=3
    )

    assert len(limited_graph["nodes"]) <= 3
    assert all(
        edge["evidence_sentence"]
        .casefold()
        .find(
            next(
                node["label"].casefold()
                for node in graph["nodes"]
                if node["id"] == edge["source"]
            )
        )
        >= 0
        and edge["evidence_sentence"]
        .casefold()
        .find(
            next(
                node["label"].casefold()
                for node in graph["nodes"]
                if node["id"] == edge["target"]
            )
        )
        >= 0
        for edge in graph["edges"]
    )
    relations = {
        (edge["relation"], edge["evidence_sentence"]) for edge in graph["edges"]
    }
    assert ("is_a", "Stemming is a type of normalization.") in relations
    assert ("uses", "Stemming uses tokenization.") in relations
    assert ("related_to", "Normalization improves tokenization.") in relations
    uses_edge = next(edge for edge in graph["edges"] if edge["relation"] == "uses")
    graph_labels = {node["id"]: node["label"] for node in graph["nodes"]}
    assert graph_labels[uses_edge["source"]] == "Stemming"
    assert graph_labels[uses_edge["target"]] == "tokenization"
    related_edge = next(
        edge for edge in graph["edges"] if edge["relation"] == "related_to"
    )
    assert related_edge["weight"] == 2
    assert "Orphan" not in {node["label"] for node in graph["nodes"]}
    assert all(edge["page"] == 1 for edge in graph["edges"])


def test_plan_caps_days_and_reserves_final_date_for_revision():
    today = date(2026, 11, 7)
    exam_date = today + timedelta(days=7)
    topics = [
        StudyTopic(1, "Weak topic", 1, 2, "hard", 0.8, 2.0, 45),
        StudyTopic(1, "Strong topic", 3, 3, "easy", 0.0, 1.0, 20),
    ]

    plan = generate_study_plan(
        topics,
        exam_date=exam_date,
        daily_minutes=60,
        today=today,
    )

    assert plan["days"][-1]["date"] == exam_date.isoformat()
    assert all(day["total_minutes"] <= 60 for day in plan["days"])
    assert all(
        activity["activity_type"] in {"revise_weak_topic", "review_flashcards"}
        for activity in plan["days"][-1]["activities"]
    )
    assert all(
        activity["activity_type"] in {"revise_weak_topic", "review_flashcards"}
        for activity in plan["days"][-2]["activities"]
    )


def test_weak_topics_are_first_and_receive_more_study_time():
    today = date(2026, 11, 7)
    topics = [
        StudyTopic(1, "Strong", 1, 1, "easy", 0.0, 1.2, 20),
        StudyTopic(1, "Weak", 2, 2, "hard", 0.9, 2.0, 40),
    ]
    plan = generate_study_plan(
        topics,
        exam_date=today + timedelta(days=9),
        daily_minutes=60,
        today=today,
    )
    first_day = plan["days"][0]["activities"]
    first_topics = [activity["topic"] for activity in first_day]
    assert first_topics[0] == "Weak"
    weak_minutes = sum(
        activity["minutes"]
        for day in plan["days"]
        for activity in day["activities"]
        if activity["topic"] == "Weak"
    )
    strong_minutes = sum(
        activity["minutes"]
        for day in plan["days"]
        for activity in day["activities"]
        if activity["topic"] == "Strong"
    )
    assert weak_minutes > strong_minutes
    revision_dates = {
        date.fromisoformat(day["date"])
        for day in plan["days"]
        for activity in day["activities"]
        if activity["topic"] == "Weak"
        and activity["activity_type"] == "revise_weak_topic"
    }
    first_study = date.fromisoformat(plan["days"][0]["date"])
    assert {first_study + timedelta(days=offset) for offset in (1, 3, 7)} <= (
        revision_dates
    )


def test_stored_topic_stats_and_chunk_difficulty_change_topic_estimates(db_session):
    owner = _user(db_session, "topic-stats-owner")
    document = _document(db_session, owner)
    paragraph = (
        "This section explains essential course material in clear sentences. "
        "Students connect concepts, practice careful reading, and review facts. "
        "Retrieval practice improves recall and supports learning."
    )
    db_session.add_all(
        [
            DocumentPage(
                document_id=document.id,
                page_number=1,
                text=paragraph,
                headings=[{"text": "Weak topic"}],
            ),
            DocumentPage(
                document_id=document.id,
                page_number=2,
                text=paragraph,
                headings=[{"text": "Strong topic"}],
            ),
            DocumentPage(
                document_id=document.id,
                page_number=3,
                text=paragraph,
                headings=[{"text": "Correct Answer: B"}],
            ),
            Chunk(
                doc_id=document.id,
                page=1,
                page_start=1,
                page_end=1,
                text=paragraph,
                token_count=32,
                chunk_index=0,
                difficulty_label="hard",
            ),
            Chunk(
                doc_id=document.id,
                page=2,
                page_start=2,
                page_end=2,
                text=paragraph,
                token_count=32,
                chunk_index=1,
                difficulty_label="easy",
            ),
            TopicStat(owner_id=owner.id, topic="Weak topic", attempts=5, correct=1),
            TopicStat(owner_id=owner.id, topic="Strong topic", attempts=5, correct=5),
        ]
    )
    db_session.flush()

    topics = collect_study_topics(
        db_session, owner_id=owner.id, document_ids=[document.id]
    )

    assert topics[0].title == "Weak topic"
    assert topics[0].weak_score == 0.8
    assert topics[0].difficulty == "hard"
    assert topics[0].study_minutes > topics[1].study_minutes
    assert "Correct Answer: B" not in {topic.title for topic in topics}


def test_short_plan_reports_lower_priority_topics():
    today = date(2026, 11, 7)
    topics = [
        StudyTopic(1, "Weak", 1, 1, "medium", 0.9, 2.0, 20),
        StudyTopic(1, "Strong", 2, 2, "medium", 0.0, 1.0, 20),
    ]
    plan = generate_study_plan(
        topics,
        exam_date=today + timedelta(days=2),
        daily_minutes=20,
        today=today,
    )
    assert plan["omitted_topics"] == [
        {
            "document_id": 1,
            "topic": "Strong",
            "page_start": 2,
            "page_end": 2,
            "reason": "insufficient_available_study_time",
        }
    ]


def test_graph_and_plan_routes_are_owner_scoped(client, db_session, monkeypatch):
    owner = _user(db_session, "private-owner")
    other_user = _user(db_session, "other-owner")
    document = _graph_fixture(db_session, owner, private=True)

    def forbidden_provider(*args, **kwargs):
        raise AssertionError("Private graph requests must not initialize a provider.")

    monkeypatch.setattr("app.routers.study.RAGChatPipeline", forbidden_provider)
    db_session.commit()
    response = client.get(
        f"/study/documents/{document.id}/graph?label_relations=true",
        headers=_headers(owner),
    )
    assert response.status_code == 200
    assert response.json()["nodes"]
    chapter_graph = client.get(
        f"/study/documents/{document.id}/graph?chapter=Chapter%201",
        headers=_headers(owner),
    )
    assert chapter_graph.status_code == 200
    first_node = chapter_graph.json()["nodes"][0]
    detail = client.get(
        f"/study/documents/{document.id}/graph/nodes/{first_node['id']}?chapter=Chapter%201",
        headers=_headers(owner),
    )
    assert detail.status_code == 200
    assert "definition" in detail.json()
    assert (
        client.get(
            f"/study/documents/{document.id}/graph",
            headers=_headers(other_user),
        ).status_code
        == 404
    )
    plan_response = client.post(
        "/study/plans",
        headers=_headers(owner),
        json={
            "exam_date": (date.today() + timedelta(days=7)).isoformat(),
            "daily_minutes": 60,
            "document_ids": [document.id],
        },
    )
    assert plan_response.status_code == 201
    assert (
        client.get("/study/plans/current", headers=_headers(other_user)).status_code
        == 404
    )
    assert (
        client.patch(
            f"/study/plans/{plan_response.json()['id']}/days/"
            f"{plan_response.json()['days'][0]['date']}/done?done=true",
            headers=_headers(other_user),
        ).status_code
        == 404
    )


def test_plan_creation_completion_and_regeneration_preserve_done_item(
    client, db_session
):
    owner = _user(db_session, "planner-owner")
    document = _document(db_session, owner)
    text = (
        "A section contains meaningful study content and explains its main ideas. "
        "Students should connect concepts, practice careful reading, and review "
        "important facts. Retrieval practice improves recall and supports learning."
    )
    db_session.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            text=text,
            headings=[{"text": "Weak topic"}],
        )
    )
    db_session.add(
        Chunk(
            doc_id=document.id,
            page=1,
            page_start=1,
            page_end=1,
            text=text,
            token_count=32,
            chunk_index=0,
            difficulty_label="hard",
        )
    )
    db_session.add(
        TopicStat(owner_id=owner.id, topic="Weak topic", attempts=5, correct=1)
    )
    db_session.commit()
    today = date.today()
    response = client.post(
        "/study/plans",
        headers=_headers(owner),
        json={
            "exam_date": (today + timedelta(days=7)).isoformat(),
            "daily_minutes": 60,
            "document_ids": [document.id],
        },
    )
    assert response.status_code == 201
    plan = response.json()
    item = next(
        activity
        for day in plan["days"]
        for activity in day["activities"]
        if activity["topic"] == "Weak topic"
    )
    marked = client.patch(
        f"/study/plans/{plan['id']}/items/{item['id']}/done?done=true",
        headers=_headers(owner),
    )
    assert marked.status_code == 200
    regenerated = client.post(
        f"/study/plans/{plan['id']}/regenerate",
        headers=_headers(owner),
    )
    assert regenerated.status_code == 200
    retained = [
        activity
        for day in regenerated.json()["days"]
        for activity in day["activities"]
        if activity["id"] == item["id"]
    ]
    assert len(retained) == 1
    assert retained[0]["is_done"] is True
    assert (
        db_session.scalar(
            select(StudyPlanItem.id).where(StudyPlanItem.id == item["id"])
        )
        == item["id"]
    )
    assert db_session.scalar(select(StudyPlan.id).where(StudyPlan.id == plan["id"]))
