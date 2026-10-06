"""Ownership isolation tests for documents and teacher class data."""

from conftest import access_token_for
from fastapi.testclient import TestClient

from app.models import Document, StudyClass, User


def test_student_cannot_read_another_students_document(
    client: TestClient, db_session
) -> None:
    owner = User(
        email="owner@example.com",
        full_name="Owner",
        password_hash="unused",
        role="student",
    )
    other = User(
        email="other@example.com",
        full_name="Other",
        password_hash="unused",
        role="student",
    )
    db_session.add_all([owner, other])
    db_session.flush()
    document = Document(
        owner_id=owner.id,
        title="Private notes",
        status="ready",
        page_count=3,
        language="en",
    )
    db_session.add(document)
    db_session.commit()

    token = access_token_for(other.id)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/documents", headers=headers).json() == []
    assert client.get(f"/documents/{document.id}", headers=headers).status_code == 404


def test_teacher_can_only_read_their_own_classes(
    client: TestClient, db_session
) -> None:
    first_teacher = User(
        email="teacher-one@example.com",
        full_name="Teacher One",
        password_hash="unused",
        role="teacher",
    )
    second_teacher = User(
        email="teacher-two@example.com",
        full_name="Teacher Two",
        password_hash="unused",
        role="teacher",
    )
    db_session.add_all([first_teacher, second_teacher])
    db_session.flush()
    own_class = StudyClass(teacher_id=first_teacher.id, name="My class")
    foreign_class = StudyClass(teacher_id=second_teacher.id, name="Other class")
    db_session.add_all([own_class, foreign_class])
    db_session.commit()

    token = access_token_for(first_teacher.id)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/classes", headers=headers).json() == [
        {"id": own_class.id, "name": "My class"}
    ]
    assert (
        client.get(
            f"/classes/{foreign_class.id}/assignments",
            headers=headers,
        ).status_code
        == 404
    )
