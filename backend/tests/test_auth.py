"""Authentication, token lifecycle, and authorization tests."""

from datetime import UTC, datetime, timedelta

import jwt
from conftest import access_token_for
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import verify_password
from app.models import RefreshToken, User


def test_register_login_refresh_and_logout(client: TestClient, db_session) -> None:
    registration = client.post(
        "/auth/register",
        json={
            "email": "  Learner@Example.com ",
            "full_name": "Learner",
            "password": "correct-horse-battery",
        },
    )
    assert registration.status_code == 201
    initial = registration.json()
    assert initial["user"]["role"] == "student"
    user = db_session.scalar(select(User).where(User.email == "learner@example.com"))
    assert user is not None
    assert user.password_hash.startswith("$argon2id$")
    assert verify_password("correct-horse-battery", user.password_hash)

    login = client.post(
        "/auth/login",
        json={"email": "LEARNER@example.com", "password": "correct-horse-battery"},
    )
    assert login.status_code == 200
    first_refresh = login.json()["refresh_token"]
    refreshed = client.post("/auth/refresh", json={"refresh_token": first_refresh})
    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] != first_refresh
    assert (
        client.post("/auth/refresh", json={"refresh_token": first_refresh}).status_code
        == 401
    )

    active_refresh = refreshed.json()["refresh_token"]
    assert client.post(
        "/auth/logout", json={"refresh_token": active_refresh}
    ).json() == {"status": "logged_out"}
    assert (
        client.post("/auth/refresh", json={"refresh_token": active_refresh}).status_code
        == 401
    )
    assert db_session.scalar(
        select(RefreshToken).where(RefreshToken.revoked_at.is_not(None))
    )


def test_wrong_password_is_rejected(client: TestClient) -> None:
    client.post(
        "/auth/register",
        json={
            "email": "wrong@example.com",
            "full_name": "Wrong Password",
            "password": "correct-password",
        },
    )
    response = client.post(
        "/auth/login",
        json={"email": "wrong@example.com", "password": "incorrect-password"},
    )
    assert response.status_code == 401


def test_expired_access_token_is_rejected(client: TestClient) -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "1",
            "typ": "access",
            "jti": "expired-token",
            "iat": now - timedelta(minutes=2),
            "exp": now - timedelta(minutes=1),
        },
        get_settings().jwt_secret_key,
        algorithm=get_settings().jwt_algorithm,
    )
    response = client.get(
        "/documents/1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 401


def test_student_cannot_access_teacher_routes(client: TestClient, db_session) -> None:
    student = User(
        email="student-role@example.com",
        full_name="Student",
        password_hash="unused",
        role="student",
    )
    db_session.add(student)
    db_session.commit()
    login_token = access_token_for(student.id)

    response = client.get(
        "/classes",
        headers={"Authorization": f"Bearer {login_token}"},
    )
    assert response.status_code == 403
