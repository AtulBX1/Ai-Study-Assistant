from datetime import UTC, datetime, timedelta

from app.services.rag.providers import (
    FakeProvider,
    GroqProvider,
    ProviderChain,
    RateLimitError,
)


class LimitedProvider(FakeProvider):
    def stream(self, prompt, system_prompt=None):
        raise RateLimitError("429")
        yield ""


def test_chain_falls_back_for_rate_limit_and_missing_key():
    missing = GroqProvider(api_key="", model_name="test-model")
    fallback = FakeProvider(name="backup", response_text="ok")
    chain = ProviderChain([missing, LimitedProvider(name="limited"), fallback])
    assert chain.generate("question") == "ok"
    assert chain.last_provider == "backup"
    assert [row["reason"] for row in chain.skipped] == ["missing_key", "rate_limit"]


def test_chain_falls_back_after_server_error():
    chain = ProviderChain(
        [
            FakeProvider(name="broken", should_fail=True),
            FakeProvider(name="backup", response_text="ok"),
        ]
    )
    assert chain.generate("question") == "ok"
    assert chain.skipped[0]["reason"] == "provider_error"


def test_chain_skips_provider_during_cooldown():
    cooled = FakeProvider(name="cooled", response_text="wrong")
    cooled.cooldown_until = datetime.now(UTC) + timedelta(minutes=1)
    ready = FakeProvider(name="ready", response_text="answer")
    chain = ProviderChain([cooled, ready])
    assert chain.generate("q") == "answer"
    assert chain.skipped == [{"provider": "cooled", "reason": "cooldown"}]


def test_chain_trims_prompt_to_budget():
    chain = ProviderChain([FakeProvider()], context_budget=10)
    prompt, _ = chain._trim("x" * 100 + "\n\nUser Question: q", None)
    assert chain.estimate_tokens(prompt) <= 10
    assert "User Question" in prompt


def test_groq_json_mode_uses_openai_response_format():
    class Response:
        status_code = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_lines(self):
            yield '{"choices":[{"message":{"content":"{\\"items\\": []}"}}]}'

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url, **kwargs):
            assert url.endswith("/chat/completions")
            assert kwargs["json"]["response_format"] == {"type": "json_object"}
            return Response()

    provider = GroqProvider(
        api_key="test-secret", model_name="test-model", client_factory=Client
    )
    assert provider.generate_json("make JSON") == '{"items": []}'


def test_provider_status_never_includes_keys():
    chain = ProviderChain([GroqProvider(api_key="secret", model_name="model")])
    assert "secret" not in str(chain.status())


def test_groq_reads_only_content_and_records_reasoning_usage_without_leaking_it():
    import json

    class Response:
        status_code = 200
        headers = {
            "x-ratelimit-limit-requests": "25",
            "x-ratelimit-limit-tokens": "5000",
        }

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_lines(self):
            yield json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps({"questions": []}),
                                "reasoning": "must never be returned",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 200,
                        "completion_tokens": 48,
                        "total_tokens": 248,
                        "completion_tokens_details": {"reasoning_tokens": 34},
                    },
                }
            )

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url, **kwargs):
            payload = kwargs["json"]
            assert payload["response_format"] == {"type": "json_object"}
            assert payload["reasoning_effort"] == "low"
            assert payload["max_tokens"] == 1800
            return Response()

    provider = GroqProvider(
        api_key="secret-token", model_name="test-model", client_factory=Client
    )
    output = provider.generate_json("make json", max_tokens=1800)
    assert output == '{"questions": []}'
    assert "must never be returned" not in output
    assert provider.last_diagnostics["finish_reason"] == "stop"
    assert provider.last_diagnostics["input_tokens"] == 200
    assert provider.last_diagnostics["completion_tokens"] == 48
    assert provider.last_diagnostics["reasoning_tokens"] == 34
    assert (
        provider.last_diagnostics["rate_limits"]["x-ratelimit-limit-tokens"] == "5000"
    )
