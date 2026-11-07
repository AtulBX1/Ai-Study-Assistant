"""Ownership isolation tests for private documents."""

from conftest import access_token_for
from fastapi.testclient import TestClient

from app.models import Document, User


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

    headers = {"Authorization": f"Bearer {access_token_for(other.id)}"}
    assert client.get("/documents", headers=headers).json() == []
    assert client.get(f"/documents/{document.id}", headers=headers).status_code == 404


def test_removed_class_endpoints_are_unavailable(
    client: TestClient, db_session
) -> None:
    student = User(
        email="student@example.com",
        full_name="Student",
        password_hash="unused",
        role="student",
    )
    db_session.add(student)
    db_session.commit()
    headers = {"Authorization": f"Bearer {access_token_for(student.id)}"}
    assert client.get("/classes", headers=headers).status_code == 404
