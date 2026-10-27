"""LLM provider interface and implementations (Gemini, Ollama, Extractive QA, Fake)."""

import json
import logging
import re
import time
from collections.abc import Iterator
from typing import Any, Protocol

import httpx

from app.core.config import Settings, get_settings
from app.services.rag.safety import redact_secrets

logger = logging.getLogger(__name__)


class ProviderError(Exception):
    """Base error raised during LLM generation or communication."""


class RateLimitError(ProviderError):
    """Raised on 429 Too Many Requests."""


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
                "maxOutputTokens": 2048,
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
                            raise RateLimitError("Gemini rate limit (429) encountered.")
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
                    raise RateLimitError(safe_msg) from None
                raise ProviderError(safe_msg) from None

    def generate(self, prompt: str, system_prompt: str | None = None) -> str:
        chunks = list(self.stream(prompt, system_prompt))
        return "".join(chunks)


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
