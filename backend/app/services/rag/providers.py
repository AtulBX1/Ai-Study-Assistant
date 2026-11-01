"""LLM provider interface and implementations (Gemini, Ollama, Extractive QA, Fake)."""

import json
import logging
import re
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

import httpx

from app.core.config import Settings, get_settings
from app.services.rag.safety import redact_secrets

logger = logging.getLogger(__name__)
_provider_instances: dict[str, Any] = {}


def provider_cooldown_status(name: str) -> str | None:
    """Return a provider's active cooldown timestamp without exposing credentials."""
    provider = _provider_instances.get(name)
    until = getattr(provider, "cooldown_until", None)
    if until and until > datetime.now(UTC):
        return until.isoformat()
    return None


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(
                0.0,
                (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds(),
            )
        except (TypeError, ValueError, OverflowError):
            return None


class ProviderError(Exception):
    """Base error raised during LLM generation or communication."""


class RateLimitError(ProviderError):
    """Raised on 429 Too Many Requests."""

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ProviderUnavailableError(ProviderError):
    """Raised when service cannot be reached or configuration is missing."""


class LLMProvider(Protocol):
    """Common interface for generative and extractive RAG providers."""

    name: str
    is_external: bool

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        """Return the complete answer text synchronously."""

    def stream(self, prompt: str, system_prompt: str | None = None) -> Iterator[str]:
        """Yield answer tokens or fragments sequentially."""


class GeminiProvider:
    """Google Gemini API implementation using REST streaming endpoints."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        initial_backoff: float = 0.5,
    ) -> None:
        settings: Settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.gemini_api_key
        self.model_name = model_name if model_name is not None else settings.llm_model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.initial_backoff = initial_backoff
        self.name = "gemini"
        self.is_external = True
        self.last_token_count: int = 0
        self.last_latency_ms: float = 0.0

    def _ensure_api_key(self) -> str:
        if not self.api_key or not self.api_key.strip():
            raise ProviderUnavailableError("GEMINI_API_KEY is missing or empty.")
        return self.api_key.strip()

    def _build_payload(
        self, prompt: str, system_prompt: str | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": get_settings().llm_max_output_tokens,
            },
        }
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}
        return payload

    def stream(self, prompt: str, system_prompt: str | None = None) -> Iterator[str]:
        api_key = self._ensure_api_key()
        model = self.model_name.strip()
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent"
            f"?key={api_key}&alt=sse"
        )
        payload = self._build_payload(prompt, system_prompt)

        backoff = self.initial_backoff
        start_time = time.perf_counter()
        token_count = 0

        for attempt in range(self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    with client.stream("POST", url, json=payload) as response:
                        if response.status_code == 429:
                            try:
                                retry_after = response.headers.get("Retry-After")
                                retry_seconds = (
                                    float(retry_after) if retry_after else None
                                )
                            except ValueError:
                                retry_seconds = None
                            raise RateLimitError(
                                "Gemini rate limit (429) encountered.", retry_seconds
                            )
                        if response.status_code >= 500:
                            raise ProviderError(
                                f"Gemini server error: {response.status_code}"
                            )
                        if response.status_code != 200:
                            raw_body = response.read().decode("utf-8", errors="replace")
                            safe_body = redact_secrets(raw_body, [api_key])
                            raise ProviderError(
                                f"Gemini API returned status "
                                f"{response.status_code}: {safe_body}"
                            )

                        for line in response.iter_lines():
                            if line.startswith("data: "):
                                raw_json = line[6:].strip()
                                if not raw_json:
                                    continue
                                data = json.loads(raw_json)
                                candidates = data.get("candidates", [])
                                if candidates:
                                    parts = (
                                        candidates[0]
                                        .get("content", {})
                                        .get("parts", [])
                                    )
                                    for part in parts:
                                        chunk_text = part.get("text", "")
                                        if chunk_text:
                                            # Estimate ~1 token per 4 characters
                                            token_count += max(1, len(chunk_text) // 4)
                                            yield chunk_text

                                # If usage metadata is provided by the API
                                if "usageMetadata" in data:
                                    total_toks = data["usageMetadata"].get(
                                        "candidatesTokenCount"
                                    )
                                    if total_toks:
                                        token_count = total_toks

                self.last_token_count = token_count
                self.last_latency_ms = (time.perf_counter() - start_time) * 1000.0
                return

            except (RateLimitError, ProviderError, httpx.RequestError) as exc:
                if attempt < self.max_retries - 1:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                # Scrub any potential leak of the api key in exc message
                safe_msg = redact_secrets(str(exc), [api_key])
                if isinstance(exc, RateLimitError):
                    raise RateLimitError(
                        safe_msg,
                        retry_after_seconds=getattr(exc, "retry_after_seconds", None),
                    ) from None
                raise ProviderError(safe_msg) from None

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        chunks = list(self.stream(prompt, system_prompt))
        return "".join(chunks)


class GroqProvider:
    """Groq chat completions through its OpenAI-compatible API."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
        client_factory: Any = httpx.Client,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.groq_api_key
        self.model_name = model_name if model_name is not None else settings.groq_model
        self.base_url = (base_url or settings.groq_base_url).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.client_factory = client_factory
        self.name, self.is_external = "groq", True
        self.last_token_count, self.last_latency_ms = 0, 0.0
        self.request_count = 0
        self.last_diagnostics: dict[str, Any] = {
            "model": self.model_name,
            "finish_reason": None,
            "input_tokens": None,
            "completion_tokens": None,
            "reasoning_tokens": None,
            "raw_output": "",
        }
        self.cooldown_until: datetime | None = None
        self.rpm_limit = settings.groq_requests_per_minute
        self.tpm_limit = settings.groq_tokens_per_minute
        _provider_instances[self.name] = self

    def _check_key(self) -> str:
        if not self.api_key or not self.api_key.strip():
            raise ProviderUnavailableError("GROQ_API_KEY is missing or empty.")
        if not self.model_name or not self.model_name.strip():
            raise ProviderUnavailableError("GROQ_MODEL is missing or empty.")
        return self.api_key.strip()

    def _request(
        self,
        prompt: str,
        system_prompt: str | None,
        *,
        stream: bool,
        json_mode: bool = False,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
        _reasoning_retry: bool = True,
        _json_retry: bool = True,
    ) -> Iterator[str]:
        key = self._check_key()
        from app.core.config import get_settings

        settings = get_settings()
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": (
                [{"role": "system", "content": system_prompt}] if system_prompt else []
            )
            + [{"role": "user", "content": prompt}],
            "stream": stream,
            "max_tokens": max_tokens or settings.llm_max_output_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        start = time.perf_counter()
        self.last_diagnostics = {
            "model": self.model_name,
            "finish_reason": None,
            "input_tokens": None,
            "completion_tokens": None,
            "reasoning_tokens": None,
            "raw_output": "",
            "rate_limits": {},
        }
        self.request_count += 1
        try:
            with self.client_factory(timeout=self.timeout_seconds) as client:
                with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                ) as response:
                    self._observe_headers(response.headers)
                    if response.status_code == 429:
                        if (
                            self.cooldown_until is None
                            or self.cooldown_until <= datetime.now(UTC)
                        ):
                            self.cooldown_until = datetime.now(UTC) + timedelta(
                                seconds=60
                            )
                        retry_seconds = _retry_after_seconds(
                            response.headers.get("retry-after")
                        )
                        raise RateLimitError(
                            "Groq rate limit (429) encountered.", retry_seconds
                        )
                    if response.status_code >= 500:
                        raise ProviderError(
                            f"Groq server error: {response.status_code}"
                        )
                    if response.status_code != 200:
                        body_text = response.read().decode("utf-8", errors="replace")
                        safe_body = redact_secrets(body_text, [key])
                        unsupported_effort = (
                            response.status_code == 400
                            and _reasoning_retry
                            and "reasoning_effort" in safe_body.casefold()
                        )
                        unsupported_json = (
                            response.status_code == 400
                            and _json_retry
                            and "response_format" in safe_body.casefold()
                        )
                        if unsupported_effort:
                            yield from self._request(
                                prompt,
                                system_prompt,
                                stream=stream,
                                json_mode=json_mode,
                                max_tokens=max_tokens,
                                _reasoning_retry=False,
                                _json_retry=_json_retry,
                            )
                            return
                        if unsupported_json:
                            yield from self._request(
                                prompt,
                                system_prompt,
                                stream=stream,
                                json_mode=False,
                                max_tokens=max_tokens,
                                reasoning_effort=reasoning_effort,
                                _reasoning_retry=_reasoning_retry,
                                _json_retry=False,
                            )
                            return
                        raise ProviderError(
                            f"Groq API returned status {response.status_code}: "
                            f"{safe_body}"
                        )
                    for line in response.iter_lines():
                        line = line.removeprefix("data: ").strip()
                        if not line or line == "[DONE]":
                            continue
                        body = json.loads(line)
                        choices = body.get("choices", [])
                        usage = body.get("usage") or {}
                        if choices:
                            choice = choices[0]
                            self.last_diagnostics["finish_reason"] = choice.get(
                                "finish_reason"
                            )
                            details = usage.get("completion_tokens_details") or {}
                            self.last_diagnostics.update(
                                {
                                    "input_tokens": usage.get("prompt_tokens"),
                                    "completion_tokens": usage.get("completion_tokens"),
                                    "reasoning_tokens": details.get("reasoning_tokens"),
                                }
                            )
                            self.last_diagnostics["rate_limits"] = {
                                key: value
                                for key, value in response.headers.items()
                                if key.lower().startswith("x-ratelimit-")
                            }
                        content = (
                            (
                                choices[0].get("delta", {}).get("content", "")
                                if stream
                                else choices[0].get("message", {}).get("content", "")
                            )
                            if choices
                            else ""
                        )
                        if content:
                            self.last_diagnostics["raw_output"] += content
                            yield content
                        self.last_token_count = usage.get(
                            "total_tokens",
                            self.last_diagnostics.get("completion_tokens")
                            or self.last_token_count,
                        )
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError("Groq request timed out.") from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailableError("Groq request failed.") from exc
        finally:
            self.last_latency_ms = (time.perf_counter() - start) * 1000

    def _observe_headers(self, headers: Any) -> None:
        for header, attr in (
            ("x-ratelimit-limit-requests", "rpm_limit"),
            ("x-ratelimit-limit-tokens", "tpm_limit"),
        ):
            try:
                if headers.get(header):
                    setattr(self, attr, int(headers[header]))
            except (TypeError, ValueError):
                pass
        retry = headers.get("retry-after")
        reset = headers.get("x-ratelimit-reset-requests") or headers.get(
            "x-ratelimit-reset-tokens"
        )
        seconds = _retry_after_seconds(retry)
        if seconds is None and reset:
            try:
                value = str(reset).strip().lower()
                seconds = float(value[:-1]) * (60 if value.endswith("m") else 1)
            except ValueError:
                pass
        if seconds is not None:
            self.cooldown_until = datetime.now(UTC) + timedelta(seconds=max(0, seconds))
        logger.info(
            "Groq rate limits model=%s requests=%s tokens=%s remaining_requests=%s "
            "remaining_tokens=%s reset_requests=%s reset_tokens=%s",
            self.model_name,
            self.rpm_limit,
            self.tpm_limit,
            headers.get("x-ratelimit-remaining-requests"),
            headers.get("x-ratelimit-remaining-tokens"),
            headers.get("x-ratelimit-reset-requests"),
            headers.get("x-ratelimit-reset-tokens"),
        )

    def stream(self, prompt: str, system_prompt: str | None = None) -> Iterator[str]:
        return self._request(prompt, system_prompt, stream=True)

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        return "".join(self.stream(prompt, system_prompt))

    def generate_json(
        self,
        prompt: str,
        system_prompt: str | None = None,
        *,
        max_tokens: int | None = None,
        reasoning_effort: str | None = "low",
        **_: Any,
    ) -> str:
        return "".join(
            self._request(
                prompt,
                system_prompt,
                stream=False,
                json_mode=True,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            )
        )


class ProviderChain:
    """Ordered provider fallback with process-local cooldowns and safe diagnostics."""

    def __init__(
        self,
        providers: list[Any],
        *,
        context_budget: int = 6000,
        failure_delay_seconds: float = 0,
        max_requests: int | None = None,
        fallback_only_on_cooldown: bool = False,
    ) -> None:
        self.providers, self.context_budget = providers, context_budget
        self.name, self.is_external = "chain", False
        self.last_token_count, self.last_latency_ms = 0, 0.0
        self.last_provider = ""
        self.skipped: list[dict[str, str]] = []
        self.history: list[dict[str, str]] = []
        self.request_count = 0
        self.failure_delay_seconds = max(0, failure_delay_seconds)
        self.max_requests = max_requests
        self.fallback_only_on_cooldown = fallback_only_on_cooldown
        self.rate_limited = False
        self.last_error_type = ""
        self.last_error_message = ""
        self.last_diagnostics: dict[str, Any] = {}
        self.response_counts: dict[str, int] = {}
        self.is_external = any(
            getattr(provider, "is_external", False) for provider in providers
        )
        self._usage: dict[str, tuple[float, int, int]] = {}

    def status(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        return {
            "chain": [p.name for p in self.providers],
            "providers": {
                p.name: {
                    "cooldown_until": p.cooldown_until.isoformat()
                    if getattr(p, "cooldown_until", None) and p.cooldown_until > now
                    else None,
                    "rpm_limit": getattr(p, "rpm_limit", None),
                    "tpm_limit": getattr(p, "tpm_limit", None),
                }
                for p in self.providers
            },
        }

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return max(1, (len(text) + 3) // 4)

    def _trim(self, prompt: str, system_prompt: str | None) -> tuple[str, str | None]:
        budget = self.context_budget - self.estimate_tokens(system_prompt or "")
        if self.estimate_tokens(prompt) <= budget:
            return prompt, system_prompt
        # RAG context is ordered by retrieval/rerank score; preserve question tail.
        marker = "\n\nUser Question:"
        if marker in prompt:
            context, question = prompt.split(marker, 1)
            allowance = max(
                0,
                budget - self.estimate_tokens(question) - self.estimate_tokens(marker),
            )
            prompt = context[: allowance * 4] + marker + question
        else:
            prompt = prompt[: max(0, budget) * 4]
        return prompt, system_prompt

    def stream(self, prompt: str, system_prompt: str | None = None) -> Iterator[str]:
        prompt, system_prompt = self._trim(prompt, system_prompt)
        self.skipped = []
        for provider in self.providers:
            if self._over_limit(provider, prompt, system_prompt):
                self.skipped.append(
                    {"provider": provider.name, "reason": "local_rate_limit"}
                )
                continue
            if getattr(provider, "is_external", False) and not getattr(
                provider, "api_key", True
            ):
                self.skipped.append(
                    {"provider": provider.name, "reason": "missing_key"}
                )
                continue
            if (
                getattr(provider, "is_external", False)
                and getattr(provider, "cooldown_until", None)
                and provider.cooldown_until > datetime.now(UTC)
            ):
                self.skipped.append({"provider": provider.name, "reason": "cooldown"})
                continue
            try:
                # Buffer each attempt so a failed stream can safely fall through.
                output = list(provider.stream(prompt, system_prompt))
                self.last_provider = provider.name
                self.last_token_count = getattr(provider, "last_token_count", 0)
                yield from output
                return
            except (RateLimitError, ProviderError, ProviderUnavailableError) as exc:
                reason = (
                    "rate_limit"
                    if isinstance(exc, RateLimitError)
                    else (
                        "timeout"
                        if "timed out" in str(exc).lower()
                        else "provider_error"
                    )
                )
                self.skipped.append({"provider": provider.name, "reason": reason})
        raise ProviderUnavailableError("All configured providers are unavailable.")

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        return "".join(self.stream(prompt, system_prompt))

    def _over_limit(
        self, provider: Any, prompt: str, system_prompt: str | None
    ) -> bool:
        rpm, tpm = (
            getattr(provider, "rpm_limit", None),
            getattr(provider, "tpm_limit", None),
        )
        if not rpm and not tpm:
            return False
        now = time.monotonic()
        started, requests, tokens = self._usage.get(provider.name, (now, 0, 0))
        if now - started >= 60:
            started, requests, tokens = now, 0, 0
        estimated = self.estimate_tokens(prompt) + self.estimate_tokens(
            system_prompt or ""
        )
        if provider.name == "groq" and tpm:
            estimated = max(estimated, 2500)
        if (rpm and requests >= rpm) or (tpm and tokens + estimated > tpm):
            self._usage[provider.name] = (started, requests, tokens)
            if hasattr(provider, "cooldown_until"):
                provider.cooldown_until = datetime.now(UTC) + timedelta(
                    seconds=max(1, 60 - int(now - started))
                )
            return True
        self._usage[provider.name] = (started, requests + 1, tokens + estimated)
        return False

    def generate_json(
        self, prompt: str, system_prompt: str | None = None, **kwargs: Any
    ) -> str:
        # Prefer provider's strict JSON method and maintain same ordered fallback.
        prompt, system_prompt = self._trim(prompt, system_prompt)
        self.skipped = []
        rate_limit_error: RateLimitError | None = None
        rate_limit_message = ""
        for provider_index, provider in enumerate(self.providers):
            if self._over_limit(provider, prompt, system_prompt):
                self.skipped.append(
                    {"provider": provider.name, "reason": "local_rate_limit"}
                )
                continue
            if getattr(provider, "is_external", False) and not getattr(
                provider, "api_key", True
            ):
                self.skipped.append(
                    {"provider": provider.name, "reason": "missing_key"}
                )
                if self.fallback_only_on_cooldown:
                    break
                continue
            if getattr(
                provider, "cooldown_until", None
            ) and provider.cooldown_until > datetime.now(UTC):
                self.skipped.append({"provider": provider.name, "reason": "cooldown"})
                continue
            method = getattr(provider, "generate_json", None)
            provider_request_count = None
            try:
                if (
                    self.max_requests is not None
                    and self.request_count >= self.max_requests
                ):
                    self.skipped.append(
                        {"provider": provider.name, "reason": "request_budget"}
                    )
                    break
                self.request_count += 1
                provider_request_count = getattr(provider, "request_count", None)
                if method is None:
                    result = provider.generate(prompt, system_prompt)
                else:
                    result = method(prompt, system_prompt=system_prompt, **kwargs)
                if provider_request_count is not None:
                    self.request_count += max(
                        0, provider.request_count - provider_request_count - 1
                    )
                self.last_provider = provider.name
                self.last_diagnostics = dict(getattr(provider, "last_diagnostics", {}))
                self.response_counts[provider.name] = (
                    self.response_counts.get(provider.name, 0) + 1
                )
                return result
            except (RateLimitError, ProviderError, ProviderUnavailableError) as exc:
                if provider_request_count is not None:
                    self.request_count += max(
                        0, provider.request_count - provider_request_count - 1
                    )
                is_rate_limited = isinstance(exc, RateLimitError)
                reason = (
                    "rate_limit"
                    if is_rate_limited
                    else (
                        "timeout"
                        if "timed out" in str(exc).lower()
                        else "provider_error"
                    )
                )
                safe_message = redact_secrets(
                    str(exc), [getattr(provider, "api_key", None)]
                ).replace("\n", " ")
                record = {
                    "provider": provider.name,
                    "reason": reason,
                    "error_type": type(exc).__name__,
                    "message": safe_message,
                }
                self.skipped.append(record)
                self.history.append(record)
                self.last_error_type, self.last_error_message = (
                    type(exc).__name__,
                    safe_message,
                )
                if is_rate_limited:
                    self.rate_limited = True
                    rate_limit_error = exc
                    rate_limit_message = safe_message
                delay = self.failure_delay_seconds
                if is_rate_limited:
                    delay = max(delay, exc.retry_after_seconds or 0)
                has_later_provider = any(
                    not getattr(later, "is_external", False)
                    or bool(getattr(later, "api_key", True))
                    for later in self.providers[provider_index + 1 :]
                )
                if delay and has_later_provider:
                    time.sleep(delay)
                if self.fallback_only_on_cooldown and not (
                    getattr(provider, "cooldown_until", None)
                    and provider.cooldown_until > datetime.now(UTC)
                ):
                    break
        if rate_limit_error:
            raise RateLimitError(
                rate_limit_message or str(rate_limit_error),
                retry_after_seconds=rate_limit_error.retry_after_seconds,
            )
        raise ProviderUnavailableError("All configured providers are unavailable.")


class OllamaProvider:
    """Local Ollama provider strictly bounded to 1B-3B models."""

    ALLOWED_MODEL_PATTERN = re.compile(r"(1b|2b|3b|tiny|mini|small)", re.IGNORECASE)

    def __init__(
        self,
        base_url: str | None = None,
        model_name: str | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        settings: Settings = get_settings()
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model_name = (model_name or settings.ollama_model).strip()
        self.timeout_seconds = timeout_seconds
        self.name = "ollama"
        self.is_external = False
        self.last_token_count: int = 0
        self.last_latency_ms: float = 0.0

        if not self.ALLOWED_MODEL_PATTERN.search(self.model_name):
            raise ValueError(
                "Ollama provider only permits 1B-3B parameter models; "
                f"got '{self.model_name}'."
            )

    def stream(self, prompt: str, system_prompt: str | None = None) -> Iterator[str]:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "system": system_prompt or "",
            "stream": True,
        }
        start_time = time.perf_counter()
        token_count = 0

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                with client.stream("POST", url, json=payload) as response:
                    if response.status_code != 200:
                        raise ProviderUnavailableError(
                            f"Ollama returned HTTP {response.status_code}"
                        )
                    for line in response.iter_lines():
                        if not line.strip():
                            continue
                        data = json.loads(line)
                        token = data.get("response", "")
                        if token:
                            token_count += 1
                            yield token
                        if data.get("done", False):
                            break
            self.last_token_count = token_count
            self.last_latency_ms = (time.perf_counter() - start_time) * 1000.0
        except Exception as exc:
            raise ProviderUnavailableError(f"Ollama unreachable: {exc}") from exc

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        return "".join(self.stream(prompt, system_prompt))


class ExtractiveProvider:
    """Non-LLM provider using fine-tuned DistilBERT QA from Step 10."""

    def __init__(
        self,
        confidence_threshold: float = 0.05,
    ) -> None:
        self.confidence_threshold = confidence_threshold
        self.name = "extractive"
        self.is_external = False
        self.last_token_count: int = 0
        self.last_latency_ms: float = 0.0

    def answer_with_chunks(
        self, question: str, chunks: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Find the highest-confidence answer span across retrieved candidate chunks."""
        from app.services.transformer_inference import answer_chunk

        best_answer: str | None = None
        best_confidence = -1.0
        best_citation: dict[str, Any] | None = None

        start_time = time.perf_counter()

        for chunk in chunks:
            text = chunk.get("text", "")
            if not text.strip():
                continue
            res = answer_chunk(question, text, self.confidence_threshold)
            if res.get("found") and res.get("confidence", 0.0) > best_confidence:
                best_confidence = res["confidence"]
                best_answer = res["answer"]
                doc_title = (
                    chunk.get("document_title") or f"doc_{chunk.get('document_id')}"
                )
                page = chunk.get("page") or chunk.get("page_start") or 1
                best_citation = {
                    "document_id": chunk.get("document_id"),
                    "document_title": doc_title,
                    "page": page,
                    "chunk_id": chunk.get("chunk_id"),
                    "confidence": round(best_confidence, 4),
                    "text": best_answer,
                }

        self.last_latency_ms = (time.perf_counter() - start_time) * 1000.0

        if best_answer and best_citation:
            doc_title = best_citation["document_title"]
            page = best_citation["page"]
            formatted_text = f"{best_answer} [{doc_title}, p.{page}]"
            self.last_token_count = len(formatted_text.split())
            return formatted_text, [best_citation]

        not_found = "not found in the document"
        self.last_token_count = len(not_found.split())
        return not_found, []

    def stream(self, prompt: str, system_prompt: str | None = None) -> Iterator[str]:
        """Stream a single precomputed or parsed answer word-by-word."""
        words = prompt.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        return prompt


class FakeProvider:
    """CI-safe mock provider for unit testing without network or weights."""

    def __init__(
        self,
        name: str = "fake",
        response_text: str = (
            "TF-IDF stands for Term Frequency-Inverse Document Frequency "
            "[test.pdf, p.1]."
        ),
        should_rate_limit: bool = False,
        should_fail: bool = False,
        is_external: bool = True,
    ) -> None:
        self.name = name
        self.response_text = response_text
        self.should_rate_limit = should_rate_limit
        self.should_fail = should_fail
        self.is_external = is_external
        self.last_token_count: int = 10
        self.last_latency_ms: float = 5.0
        self.last_prompt: str | None = None
        self.last_system_prompt: str | None = None

    def stream(self, prompt: str, system_prompt: str | None = None) -> Iterator[str]:
        self.last_prompt = prompt
        self.last_system_prompt = system_prompt

        if self.should_rate_limit:
            raise RateLimitError("Mock 429 Too Many Requests")
        if self.should_fail:
            raise ProviderError("Mock provider failure")

        words = self.response_text.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        return "".join(self.stream(prompt, system_prompt))
