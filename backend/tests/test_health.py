"""Tests for the health endpoint and request middleware."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_ok_and_generates_request_id() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["llm"]["active_chain"]
    assert "providers" in body["llm"]
    assert response.headers["x-request-id"]


def test_request_id_is_propagated() -> None:
    response = client.get("/health", headers={"x-request-id": "test-request-123"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "test-request-123"


def test_unhandled_error_is_json_with_request_id_and_cors() -> None:
    def explode() -> None:
        raise RuntimeError("private implementation detail")

    app.add_api_route("/__test_server_error", explode, methods=["GET"])
    try:
        response = client.get(
            "/__test_server_error",
            headers={"Origin": "http://localhost:3000", "x-request-id": "error-123"},
        )
    finally:
        app.router.routes[:] = [
            route
            for route in app.router.routes
            if getattr(route, "path", None) != "/__test_server_error"
        ]
    assert response.status_code == 500
    assert response.json() == {
        "detail": "Internal server error.",
        "request_id": "error-123",
    }
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:3000", "http://127.0.0.1:3000"],
)
def test_cors_preflight_allows_local_frontend(origin: str) -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
