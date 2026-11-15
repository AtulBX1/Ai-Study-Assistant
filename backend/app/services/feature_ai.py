"""Feature-scoped LLM routing, status, and privacy settings."""

from datetime import UTC, datetime
from threading import RLock
from typing import Any

from app.core.config import Settings, get_settings
from app.services.rag.providers import (
    ExtractiveProvider,
    GeminiProvider,
    GroqProvider,
    OllamaProvider,
    ProviderChain,
)
from app.services.rag.safety import AnswerCache, RateLimiter

FEATURES = ("chat", "quiz", "flashcards", "summary", "syllabus")
_lock = RLock()
_clients: dict[str, Any] = {}
_limiters: dict[str, RateLimiter] = {}
_caches: dict[str, AnswerCache] = {}


def feature_resources(feature: str) -> tuple[AnswerCache, RateLimiter]:
    """Return independent response cache and request limiter for a feature."""
    if feature not in FEATURES:
        raise ValueError("Unknown AI feature")
    with _lock:
        _caches.setdefault(feature, AnswerCache())
        _limiters.setdefault(feature, RateLimiter())
        return _caches[feature], _limiters[feature]


def feature_provider(
    feature: str, *, local_only: bool = False, settings: Settings | None = None
) -> Any:
    """Build isolated provider chain for one feature."""
    if feature not in FEATURES:
        raise ValueError("Unknown AI feature")
    cfg = settings or get_settings()
    with _lock:
        feature_resources(feature)
        if local_only or not cfg.allow_external_llm:
            return _local_provider(cfg)
        if feature in _clients:
            return _clients[feature]
        prefix = f"feature_{feature}_"
        name = getattr(cfg, prefix + "provider")
        providers: list[Any] = []
        if name:
            key = getattr(cfg, prefix + "api_key")
            model = getattr(cfg, prefix + "model") or (
                cfg.llm_model
                if name == "gemini"
                else cfg.groq_model or "llama-3.3-70b-versatile"
            )
            base = getattr(cfg, prefix + "base_url")
            if name == "gemini":
                providers.append(GeminiProvider(api_key=key, model_name=model))
            elif name in {"groq", "openai_compat"}:
                providers.append(
                    GroqProvider(api_key=key, model_name=model, base_url=base)
                )
        else:
            for fallback in cfg.llm_provider_chain.split(","):
                fallback = fallback.strip().lower()
                if fallback == "gemini" and cfg.gemini_api_key:
                    providers.append(
                        GeminiProvider(
                            api_key=cfg.gemini_api_key, model_name=cfg.llm_model
                        )
                    )
                elif fallback == "groq" and cfg.groq_api_key:
                    providers.append(GroqProvider())
                elif fallback == "ollama":
                    providers.append(
                        OllamaProvider(
                            base_url=cfg.ollama_base_url, model_name=cfg.ollama_model
                        )
                    )
        rpm = getattr(cfg, prefix + "rpm")
        tpm = getattr(cfg, prefix + "tpm")
        if name:
            local_chain = [
                item.strip().lower() for item in cfg.llm_provider_chain.split(",")
            ]
            if "ollama" in local_chain:
                providers.append(
                    OllamaProvider(
                        base_url=cfg.ollama_base_url, model_name=cfg.ollama_model
                    )
                )
        for provider in providers:
            if getattr(provider, "is_external", False):
                provider.rpm_limit = rpm or getattr(provider, "rpm_limit", None)
                provider.tpm_limit = tpm or getattr(provider, "tpm_limit", None)
        providers.append(
            ExtractiveProvider(confidence_threshold=cfg.transformer_no_answer_threshold)
        )
        client = ProviderChain(providers, context_budget=cfg.llm_context_token_budget)
        # Keep per-feature request state independent.
        _clients[feature] = client
        return client


def _local_provider(cfg: Settings) -> Any:
    for candidate in cfg.llm_provider_chain.split(","):
        if candidate.strip().lower() == "ollama":
            return OllamaProvider(
                base_url=cfg.ollama_base_url, model_name=cfg.ollama_model
            )
    return ExtractiveProvider(confidence_threshold=cfg.transformer_no_answer_threshold)


def ai_status(settings: Settings | None = None) -> dict[str, Any]:
    cfg = settings or get_settings()
    result = {}
    for feature in FEATURES:
        name = getattr(cfg, f"feature_{feature}_provider")
        if name is None:
            names = [
                part.strip().lower()
                for part in cfg.llm_provider_chain.split(",")
                if part.strip()
            ]
            name = names[0] if names else "local"
        default_models = {
            "gemini": cfg.llm_model,
            "groq": cfg.groq_model or "llama-3.3-70b-versatile",
            "openai_compat": cfg.groq_model or "llama-3.3-70b-versatile",
            "ollama": cfg.ollama_model,
        }
        model = getattr(cfg, f"feature_{feature}_model") or default_models.get(
            name, "extractive"
        )
        configured = name in {"ollama", "extractive", "local"} or bool(
            getattr(cfg, f"feature_{feature}_api_key")
            if getattr(cfg, f"feature_{feature}_provider")
            else (cfg.gemini_api_key if name == "gemini" else cfg.groq_api_key)
        )
        instance = _clients.get(feature)
        active_provider = next(
            (item for item in getattr(instance, "providers", []) if item.name == name),
            None,
        )
        until = getattr(active_provider, "cooldown_until", None)
        cooldown = (
            max(0, int((until - datetime.now(UTC)).total_seconds()))
            if until and until > datetime.now(UTC)
            else 0
        )
        result[feature] = {
            "provider": name,
            "model": model,
            "state": (
                "cooling" if cooldown else "ok" if configured else "not configured"
            ),
            "cooldown_seconds": cooldown,
        }
    return {"features": result}


def pipeline_stages(
    provider: Any,
    *,
    retrieval: str = "local hybrid + reranker",
    validation: str = "local QA + grounding",
) -> dict[str, str]:
    actual = getattr(provider, "last_provider", "") or getattr(
        provider, "name", "local"
    )
    model = getattr(provider, "model_name", None)
    return {
        "retrieval": retrieval,
        "generation": f"{actual}/{model}" if model else actual,
        "validation": validation,
    }
