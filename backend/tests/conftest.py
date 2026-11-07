"""Shared isolated database and authentication fixtures."""

import ipaddress
import os
import re
import socket
from collections.abc import Generator
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.cache import MemoryCache
from app.core.config import Settings, get_settings

Settings.model_config["env_file"] = None
for name in tuple(os.environ):
    if re.search(
        r"(?:API_KEY|ACCESS_KEY|SECRET|TOKEN|(?:^|_)PROVIDER(?:_|$)|"
        r"ALLOW_EXTERNAL_LLM)",
        name,
        re.IGNORECASE,
    ):
        os.environ.pop(name, None)
os.environ.update(
    {
        "BACKEND": "local",
        "DATABASE_URL": "sqlite://",
        "JWT_SECRET_KEY": "test-only-jwt-secret-never-use-in-production",
        "RATE_LIMIT_IP_PER_MINUTE": "10000",
        "RATE_LIMIT_USER_PER_MINUTE": "10000",
    }
)
get_settings.cache_clear()

import app.models  # noqa: E402, F401
from app.core.database import Base, get_db
from app.main import app, rate_limit_cache


@pytest.fixture(autouse=True)
def isolate_provider_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Keep real provider credentials and dotenv settings out of every test."""
    credential_or_provider = re.compile(
        r"(?:API_KEY|ACCESS_KEY|SECRET|TOKEN|(?:^|_)PROVIDER(?:_|$)|"
        r"ALLOW_EXTERNAL_LLM)",
        re.IGNORECASE,
    )
    for name in tuple(os.environ):
        if credential_or_provider.search(name) or name in {
            "GROQ_API_KEY",
            "GEMINI_API_KEY",
            "OPENAI_API_KEY",
            "LLM_PROVIDER",
            "LLM_PROVIDER_CHAIN",
        }:
            monkeypatch.delenv(name, raising=False)

    # Pydantic settings otherwise loads the developer's ../.env file even
    # after provider variables have been removed from the process environment.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def clear_shared_rate_limit_cache() -> Generator[None, None, None]:
    """Keep process-wide middleware counters isolated across tests."""
    assert isinstance(rate_limit_cache, MemoryCache)
    rate_limit_cache.clear()
    yield
    rate_limit_cache.clear()


@pytest.fixture(autouse=True)
def block_network(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> Generator[None, None, None]:
    """Block external sockets; allow loopback for the in-process test client."""
    allow_local_network = bool(request.node.get_closest_marker("allow_local_network"))
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_sendto = socket.socket.sendto
    original_create_connection = socket.create_connection
    original_getaddrinfo = socket.getaddrinfo
    attempted: list[str] = []

    def is_allowed_local_address(address: object) -> bool:
        host = address[0] if isinstance(address, tuple) and address else address
        if not isinstance(host, str):
            return False
        if host.casefold() == "localhost":
            return True
        try:
            parsed = ipaddress.ip_address(host)
        except ValueError:
            return False
        return parsed.is_loopback or (allow_local_network and parsed.is_private)

    def denied(address: object = "unknown") -> None:
        attempted.append(str(address))
        raise RuntimeError(
            "External network access is disabled in tests; use "
            "allow_local_network only for intentional local-only networking tests."
        )

    def connect(sock: socket.socket, address: object) -> object:
        if not is_allowed_local_address(address):
            denied(address)
        return original_connect(sock, address)

    def connect_ex(sock: socket.socket, address: object) -> object:
        if not is_allowed_local_address(address):
            denied(address)
        return original_connect_ex(sock, address)

    def sendto(
        sock: socket.socket, data: bytes, *args: object, **kwargs: object
    ) -> object:
        address = args[-1] if args else kwargs.get("address")
        if not is_allowed_local_address(address):
            denied(address)
        return original_sendto(sock, data, *args, **kwargs)

    def create_connection(
        address: object, *args: object, **kwargs: object
    ) -> socket.socket:
        if not is_allowed_local_address(address):
            denied(address)
        return original_create_connection(address, *args, **kwargs)

    def getaddrinfo(host: object, *args: object, **kwargs: object) -> object:
        if not is_allowed_local_address(host):
            denied(host)
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    monkeypatch.setattr(socket.socket, "sendto", sendto)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    yield
    if attempted:
        pytest.fail(
            f"Test attempted external network access to {attempted[0]}",
            pytrace=False,
        )


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip explicitly marked slow tests on CI while keeping them local-runnable."""
    if os.getenv("CI", "").casefold() not in {"1", "true", "yes"}:
        return
    skip_slow = pytest.mark.skip(reason="slow test skipped in CI")
    for item in items:
        if item.get_closest_marker("slow"):
            item.add_marker(skip_slow)


@pytest.fixture
def test_engine() -> Generator[Engine, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(test_engine: Engine) -> Generator[Session, None, None]:
    session_factory = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )
    session = session_factory()
    yield session
    session.close()


@pytest.fixture
def client(test_engine: Engine) -> Generator[TestClient, None, None]:
    session_factory = sessionmaker(
        bind=test_engine,
        autoflush=False,
        expire_on_commit=False,
    )

    def override_get_db() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def access_token_for(user_id: int) -> str:
    """Create a short-lived signed test access token."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "typ": "access",
            "jti": "test-access-token",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        get_settings().jwt_secret_key,
        algorithm=get_settings().jwt_algorithm,
    )
