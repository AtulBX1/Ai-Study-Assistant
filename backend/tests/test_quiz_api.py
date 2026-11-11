"""Fake-only quiz API routing, quotas, and owner-isolation tests."""

from app.models import Chunk, Document, Question, Quiz, User
from app.routers import quizzes
from app.services.quiz.schemas import QuizQuestion
from tests.conftest import access_token_for


def _user(db, email: str) -> User:
    user = User(email=email, full_name=email, password_hash="unused")
    db.add(user)
    db.flush()
    return user


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token_for(user.id)}"}


def _source_question(chunk: Chunk, *, answer: str, evidence: str, question: str):
    return QuizQuestion(
        question=question,
        type="short_answer",
        correct_answer=answer,
        evidence=evidence,
        explanation=evidence,
        source_chunk_id=chunk.id,
        page=chunk.page,
        difficulty="medium",
        engine="offline",
    )


def test_quiz_ownership_isolation(client, db_session):
    owner = _user(db_session, "quiz-owner@example.test")
    other = _user(db_session, "quiz-other@example.test")
    quiz = Quiz(owner_id=owner.id, title="Owned quiz", engine="offline")
    db_session.add(quiz)
    db_session.commit()

    response = client.get(f"/quizzes/{quiz.id}", headers=_headers(other))

    assert response.status_code == 404


def test_private_auto_routes_to_offline_without_provider(
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
    question = _source_question(
        chunk,
        answer="Python Software Foundation",
        evidence="The Python Software Foundation maintains the Python language.",
        question="Which foundation maintains the Python language?",
    )

    class FakeOffline:
        qa_model = staticmethod(lambda *_: "Python Software Foundation")

        def generate(self, *_args, **_kwargs):
            return [question]

    def forbidden_provider():
        raise AssertionError("Private source reached an AI provider")

    monkeypatch.setattr(quizzes, "ClassicEngine", FakeOffline)
    monkeypatch.setattr(quizzes, "_provider", forbidden_provider)
    response = client.post(
        "/quizzes",
        headers=_headers(user),
        json={
            "title": "Private quiz",
            "document_ids": [document.id],
            "engine": "auto",
            "question_types": ["short_answer"],
            "count": 1,
        },
    )

    assert response.status_code == 201, response.text
    result = response.json()
    assert result["engine"] == "auto"
    assert result["report"]["fallback_reason"] == "private_document"
    assert result["report"]["by_type"]["short_answer"] == {
        "requested": 1,
        "produced": 1,
        "reject_reasons": {},
    }
    quiz_id = result["id"]
    headers = _headers(user)
    quiz_response = client.get(f"/quizzes/{quiz_id}", headers=headers)
    item = quiz_response.json()["questions"][0]
    assert item["engine"] == "offline"
    assert "correct_answer" not in item
    attempt = client.post(f"/quizzes/{quiz_id}/attempts", headers=headers).json()
    submission = client.post(
        f"/quizzes/{quiz_id}/attempts/{attempt['attempt_id']}/submit",
        headers=headers,
        json={"answers": [{"question_id": item["id"], "answer": "incorrect"}]},
    )
    assert submission.status_code == 200
    assert submission.json()["score"] == 0


def test_ai_engine_rejects_private_documents_without_calling_provider(
    client, db_session, monkeypatch
):
    user = _user(db_session, "quiz-private-ai@example.test")
    document = Document(
        owner_id=user.id,
        title="Private notes",
        status="ready",
        is_private=True,
    )
    db_session.add(document)
    db_session.flush()
    db_session.add(
        Chunk(
            doc_id=document.id,
            page=1,
            page_start=1,
            page_end=1,
            text="Python language supports indentation in its standard code syntax.",
            token_count=10,
            chunk_index=0,
        )
    )
    db_session.commit()

    def forbidden_provider():
        raise AssertionError("Private source reached an AI provider")

    monkeypatch.setattr(quizzes, "_provider", forbidden_provider)
    response = client.post(
        "/quizzes",
        headers=_headers(user),
        json={
            "document_ids": [document.id],
            "engine": "ai",
            "question_types": ["short_answer"],
            "count": 1,
        },
    )

    assert response.status_code == 422
    assert "private documents" in response.json()["detail"]["message"].lower()


def test_offline_quiz_reports_round_robin_type_quotas(client, db_session, monkeypatch):
    user = _user(db_session, "quiz-quotas@example.test")
    document = Document(owner_id=user.id, title="NLP notes", status="ready")
    db_session.add(document)
    db_session.flush()
    chunk = Chunk(
        doc_id=document.id,
        page=1,
        page_start=1,
        page_end=1,
        text=(
            "Python language supports indentation in its standard code syntax. "
            "Java language compiles many source files into portable bytecode. "
            "Ruby language provides concise syntax for dynamic applications."
        ),
        token_count=28,
        chunk_index=0,
    )
    db_session.add(chunk)
    db_session.commit()
    items = [
        _source_question(
            chunk,
            answer="Python language",
            evidence=(
                "Python language supports indentation in its standard code syntax."
            ),
            question="Which language supports indentation in its standard code syntax?",
        ),
        _source_question(
            chunk,
            answer="Java language",
            evidence=(
                "Java language compiles many source files into portable bytecode."
            ),
            question=(
                "Which language compiles many source files into portable bytecode?"
            ),
        ),
        QuizQuestion(
            question=(
                "Fill in the blank: The _____ provides concise syntax "
                "for dynamic applications."
            ),
            type="fill_in_the_blank",
            correct_answer="Ruby language",
            evidence="Ruby language provides concise syntax for dynamic applications.",
            explanation=(
                "Ruby language provides concise syntax for dynamic applications."
            ),
            source_chunk_id=chunk.id,
            page=1,
            difficulty="medium",
            engine="offline",
        ),
    ]

    class FakeOffline:
        qa_model = staticmethod(
            lambda question, _: (
                "Python language"
                if "supports indentation" in question
                else "Java language"
            )
        )

        def generate(self, *_args, **_kwargs):
            return items

    monkeypatch.setattr(quizzes, "ClassicEngine", FakeOffline)
    monkeypatch.setattr(quizzes, "embedding_similarity", lambda *_args: 0.0)
    monkeypatch.setattr(
        quizzes,
        "_provider",
        lambda: (_ for _ in ()).throw(AssertionError("Offline requested provider")),
    )
    response = client.post(
        "/quizzes",
        headers=_headers(user),
        json={
            "document_ids": [document.id],
            "engine": "offline",
            "question_types": ["short_answer", "fill_in_the_blank"],
            "count": 3,
        },
    )

    assert response.status_code == 201, response.text
    report = response.json()["report"]
    assert report["by_type"]["short_answer"]["requested"] == 2
    assert report["by_type"]["short_answer"]["produced"] == 2
    assert report["by_type"]["fill_in_the_blank"]["requested"] == 1
    assert report["by_type"]["fill_in_the_blank"]["produced"] == 1
    assert response.json()["questions"] == 3


def test_auto_uses_ai_then_offline_for_shortfall(client, db_session, monkeypatch):
    user = _user(db_session, "quiz-auto-topup@example.test")
    document = Document(owner_id=user.id, title="NLP notes", status="ready")
    db_session.add(document)
    db_session.flush()
    chunk = Chunk(
        doc_id=document.id,
        page=1,
        page_start=1,
        page_end=1,
        text=(
            "Python language supports indentation in its standard code syntax. "
            "Java language compiles many source files into portable bytecode."
        ),
        token_count=20,
        chunk_index=0,
    )
    db_session.add(chunk)
    db_session.commit()
    ai_question = _source_question(
        chunk,
        answer="Python language",
        evidence="Python language supports indentation in its standard code syntax.",
        question="Which language supports indentation in its standard code syntax?",
    )
    ai_question.engine = "ai"
    ai_question.provider = "fake-provider"
    offline_question = _source_question(
        chunk,
        answer="Java language",
        evidence="Java language compiles many source files into portable bytecode.",
        question="Which language compiles many source files into portable bytecode?",
    )
    calls = []

    class FakeAI:
        def __init__(self, _provider):
            self.provider = _provider

        def generate(self, *_args, **_kwargs):
            calls.append("ai")
            return [ai_question]

    class FakeOffline:
        qa_model = staticmethod(
            lambda question, _: (
                "Python language"
                if "supports indentation" in question
                else "Java language"
            )
        )

        def generate(self, *_args, **_kwargs):
            calls.append("offline")
            return [offline_question]

    monkeypatch.setattr(quizzes, "_provider", lambda: object())
    monkeypatch.setattr(quizzes, "LLMEngine", FakeAI)
    monkeypatch.setattr(quizzes, "ClassicEngine", FakeOffline)
    monkeypatch.setattr(quizzes, "embedding_similarity", lambda *_args: 0.0)
    response = client.post(
        "/quizzes",
        headers=_headers(user),
        json={
            "document_ids": [document.id],
            "engine": "auto",
            "question_types": ["short_answer"],
            "count": 2,
        },
    )

    assert response.status_code == 201, response.text
    assert calls == ["ai", "offline"]
    assert response.json()["report"]["by_type"]["short_answer"]["produced"] == 2
    questions = (
        db_session.query(Question).filter_by(quiz_id=response.json()["id"]).all()
    )
    assert {item.engine for item in questions} == {"ai", "offline"}
    assert {item.options["provider"] for item in questions} == {
        "fake-provider",
        None,
    }


def test_ai_only_non_private_does_not_fall_back_offline(
    client, db_session, monkeypatch
):
    user = _user(db_session, "quiz-ai-only@example.test")
    document = Document(owner_id=user.id, title="NLP notes", status="ready")
    db_session.add(document)
    db_session.flush()
    chunk = Chunk(
        doc_id=document.id,
        page=1,
        page_start=1,
        page_end=1,
        text="Python language supports indentation in its standard code syntax.",
        token_count=10,
        chunk_index=0,
    )
    db_session.add(chunk)
    db_session.commit()
    ai_question = _source_question(
        chunk,
        answer="Python language",
        evidence="Python language supports indentation in its standard code syntax.",
        question="Which language supports indentation in its standard code syntax?",
    )
    ai_question.engine = "ai"
    ai_question.provider = "fake-provider"
    calls = []

    class FakeAI:
        def __init__(self, _provider):
            self.provider = _provider

        def generate(self, *_args, **_kwargs):
            calls.append("ai")
            return [ai_question]

    class ForbiddenOffline:
        qa_model = staticmethod(lambda *_: "Python language")

        def generate(self, *_args, **_kwargs):
            raise AssertionError("AI-only generation called the offline engine")

    monkeypatch.setattr(quizzes, "_provider", lambda: object())
    monkeypatch.setattr(quizzes, "LLMEngine", FakeAI)
    monkeypatch.setattr(quizzes, "ClassicEngine", ForbiddenOffline)
    monkeypatch.setattr(quizzes, "embedding_similarity", lambda *_args: 0.0)
    response = client.post(
        "/quizzes",
        headers=_headers(user),
        json={
            "document_ids": [document.id],
            "engine": "ai",
            "question_types": ["short_answer"],
            "question_count": 1,
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["engine"] == "ai"
    assert calls == ["ai"]
    question = db_session.query(Question).filter_by(quiz_id=response.json()["id"]).one()
    assert question.engine == "ai"
    assert question.options["provider"] == "fake-provider"
