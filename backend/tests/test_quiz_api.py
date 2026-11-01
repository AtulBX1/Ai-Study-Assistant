"""Owner isolation and privacy routing tests using the in-memory CI database."""

from app.models import Chunk, Document, Quiz, User
from app.routers import quizzes
from app.services.quiz.schemas import QuizQuestion
from tests.conftest import access_token_for


def _user(db, email):
    user = User(email=email, full_name=email, password_hash="unused")
    db.add(user)
    db.flush()
    return user


def test_quiz_ownership_isolation(client, db_session):
    owner = _user(db_session, "quiz-owner@example.test")
    other = _user(db_session, "quiz-other@example.test")
    quiz = Quiz(owner_id=owner.id, title="Owned quiz", engine="classic")
    db_session.add(quiz)
    db_session.commit()
    response = client.get(
        f"/quizzes/{quiz.id}",
        headers={"Authorization": f"Bearer {access_token_for(other.id)}"},
    )
    assert response.status_code == 404


def test_private_document_routes_to_classic_without_provider(
    client, db_session, monkeypatch
):
    user = _user(db_session, "quiz-private@example.test")
    document = Document(
        owner_id=user.id,
        title="Private notes",
        status="ready",
        is_private=True,
    )
    db_session.add(document)
    db_session.flush()
    chunk = Chunk(
        doc_id=document.id,
        page=4,
        page_start=4,
        page_end=4,
        text="The Python Software Foundation maintains the Python language.",
        token_count=9,
        chunk_index=0,
    )
    db_session.add(chunk)
    db_session.commit()

    question = QuizQuestion(
        question="Which foundation maintains the Python language?",
        type="short_answer",
        correct_answer="Python Software Foundation",
        evidence="The Python Software Foundation maintains the Python language.",
        explanation="The Python Software Foundation maintains the Python language.",
        source_chunk_id=chunk.id,
        page=4,
        difficulty="easy",
        engine="classic",
    )

    class FakeClassic:
        qa_model = staticmethod(lambda *_: "Python Software Foundation")

        def __init__(self):
            pass

        def generate(self, *_args, **_kwargs):
            return [question]

    def forbidden_provider():
        raise AssertionError("Private source reached an LLM provider")

    monkeypatch.setattr(quizzes, "ClassicEngine", FakeClassic)
    monkeypatch.setattr(quizzes, "_provider", forbidden_provider)
    response = client.post(
        "/quizzes",
        headers={"Authorization": f"Bearer {access_token_for(user.id)}"},
        json={
            "title": "Private quiz",
            "document_ids": [document.id],
            "engine": "llm",
            "question_count": 1,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["engine"] == "classic"
    assert response.json()["report"]["fallback_reason"] == "private_document"
    quiz_id = response.json()["id"]
    headers = {"Authorization": f"Bearer {access_token_for(user.id)}"}
    quiz_response = client.get(f"/quizzes/{quiz_id}", headers=headers)
    item = quiz_response.json()["questions"][0]
    assert "correct_answer" not in item
    attempt = client.post(f"/quizzes/{quiz_id}/attempts", headers=headers).json()
    submission = client.post(
        f"/quizzes/{quiz_id}/attempts/{attempt['attempt_id']}/submit",
        headers=headers,
        json={"answers": [{"question_id": item["id"], "answer": "incorrect"}]},
    )
    assert submission.status_code == 200
    assert submission.json()["score"] == 0
    retry = client.post(
        f"/quizzes/{quiz_id}/retake?attempt_id={attempt['attempt_id']}",
        headers=headers,
    )
    assert retry.status_code == 201
    assert len(retry.json()["questions"]) == 1
