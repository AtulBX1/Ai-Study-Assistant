"""Feature routing tests use only in-memory providers and fake credentials."""

from app.core.config import Settings
from app.services.feature_ai import (
    _caches,
    _clients,
    _limiters,
    ai_status,
    feature_provider,
)
from app.services.rag.providers import ExtractiveProvider, ProviderChain


def setup_function() -> None:
    _clients.clear()
    _limiters.clear()
    _caches.clear()


def test_feature_clients_and_state_are_isolated() -> None:
    settings = Settings(
        feature_chat_provider="groq",
        feature_chat_api_key="fake",
        feature_chat_model="fake-model",
    )
    chat = feature_provider("chat", settings=settings)
    quiz = feature_provider("quiz", settings=settings)
    assert chat is not quiz
    assert _caches["chat"] is not _caches["quiz"]
    assert _limiters["chat"] is not _limiters["quiz"]


def test_feature_provider_precedes_global_local_fallback() -> None:
    settings = Settings(
        feature_quiz_provider="groq",
        feature_quiz_api_key="fake",
        llm_provider_chain="ollama,extractive",
    )
    provider = feature_provider("quiz", settings=settings)
    assert isinstance(provider, ProviderChain)
    assert [item.name for item in provider.providers] == [
        "groq",
        "ollama",
        "extractive",
    ]


def test_local_only_returns_local_provider_and_status_never_contains_keys() -> None:
    settings = Settings(
        feature_chat_provider="groq",
        feature_chat_api_key="secret-test-key",
        llm_provider_chain="extractive",
    )
    provider = feature_provider("chat", local_only=True, settings=settings)
    assert isinstance(provider, ExtractiveProvider)
    assert not provider.is_external
    assert "secret-test-key" not in str(ai_status(settings))
