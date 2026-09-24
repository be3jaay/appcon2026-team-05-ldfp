"""OpenAI-compatible client (Groq/Cerebras/OpenRouter) and the provider fallback chain, offline."""

import json

import httpx
import pytest

from src.clients import llm_chain
from src.clients.llm_chain import FallbackLLMClient, build_llm_client
from src.clients.openai_compat_client import OpenAICompatClient
from src.config import settings
from src.services.claims.classifier import LLMConfigError, RetryableLLMError

OK_BODY = {
    "choices": [{"message": {"content": '{"claims": []}'}}],
    "usage": {"prompt_tokens": 1400, "completion_tokens": 50},
}


def client(handler, model="openai/gpt-oss-120b", **kw) -> OpenAICompatClient:
    return OpenAICompatClient("groq", "test-key", model, transport=httpx.MockTransport(handler), **kw)


async def test_sends_openai_chat_request_with_json_mode():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=OK_BODY)

    out = await client(handler, reasoning_effort="low").generate("SYS", "USER")
    assert out == '{"claims": []}'
    req = seen[0]
    assert str(req.url) == "https://api.groq.com/openai/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer test-key"
    body = json.loads(req.content)
    assert body["messages"] == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}]
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0
    assert body["reasoning_effort"] == "low"


async def test_reasoning_effort_only_sent_to_reasoning_models():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=OK_BODY)

    await client(handler, model="llama-3.3-70b", reasoning_effort="low").generate("s", "u")
    assert "reasoning_effort" not in seen[0]


@pytest.mark.parametrize(
    "response, retry_after, exponential",
    [
        (httpx.Response(429, headers={"retry-after": "7"}), 7.0, False),
        (httpx.Response(429, headers={"x-ratelimit-reset-tokens": "1m2.5s"}), 62.5, False),
        (httpx.Response(429, headers={"x-ratelimit-reset-tokens": "697ms"}), 0.697, False),
        (httpx.Response(429), 20.0, True),
        # A per-minute token limit waits for the token window, not the daily request window.
        (httpx.Response(429, json={"error": {"message": "Rate limit reached on tokens per minute (TPM)"}},
                        headers={"x-ratelimit-reset-requests": "25m55s", "x-ratelimit-reset-tokens": "7.5s"}), 7.5, False),
        # Groq's own "try again in" wins, e.g. for a daily token limit.
        (httpx.Response(429, json={"error": {"message": "Rate limit reached on tokens per day (TPD): Limit 200000, "
                                             "Used 199400, Requested 2600. Please try again in 14m24.5s. Need more"}},
                        headers={"x-ratelimit-reset-tokens": "7.5s"}), 864.5, False),
        (httpx.Response(429, json={"error": {"message": "Rate limit reached on requests per day (RPD)"}},
                        headers={"x-ratelimit-reset-requests": "25m", "x-ratelimit-reset-tokens": "7.5s"}), 1500.0, False),
        (httpx.Response(503), 2.0, True),
        (httpx.Response(503, headers={"x-ratelimit-reset-tokens": "30s"}), 2.0, True),  # reset headers only count on 429
        (httpx.Response(400, json={"error": {"code": "json_validate_failed"}}), 2.0, True),
    ],
)
async def test_transient_errors_are_retryable(response, retry_after, exponential):
    with pytest.raises(RetryableLLMError) as exc:
        await client(lambda r: response).generate("s", "u")
    assert exc.value.retry_after == pytest.approx(retry_after)
    assert exc.value.exponential is exponential


async def test_timeout_is_retryable():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(RetryableLLMError):
        await client(handler).generate("s", "u")


async def test_bad_key_is_a_config_error():
    with pytest.raises(LLMConfigError, match="API key rejected"):
        await client(lambda r: httpx.Response(401)).generate("s", "u")


async def test_unknown_model_lists_available_models():
    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "openai/gpt-oss-120b"}, {"id": "qwen/qwen3.8-27b"}]})
        return httpx.Response(404, json={"error": {"code": "model_not_found", "message": "The model `x` does not exist"}})

    with pytest.raises(LLMConfigError) as exc:
        await client(handler, model="x").generate("s", "u")
    assert "available models: openai/gpt-oss-120b, qwen/qwen3.8-27b" in str(exc.value)


async def test_malformed_success_body_is_retryable():
    with pytest.raises(RetryableLLMError):
        await client(lambda r: httpx.Response(200, json={"choices": []})).generate("s", "u")


def test_missing_key_is_a_config_error():
    with pytest.raises(LLMConfigError):
        OpenAICompatClient("groq", None, "m")


# --- fallback chain ------------------------------------------------------------------


class Stub:
    def __init__(self, name, *outcomes):
        self.name = name
        self.outcomes = list(outcomes)
        self.calls = 0

    async def generate(self, system, user, response_schema=None):
        self.calls += 1
        outcome = self.outcomes[min(self.calls - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


async def test_primary_answers_when_healthy():
    a, b = Stub("groq", "A"), Stub("gemini", "B")
    assert await FallbackLLMClient([a, b]).generate("s", "u") == "A"
    assert (a.calls, b.calls) == (1, 0)


async def test_busy_primary_falls_back_immediately():
    a = Stub("groq", RetryableLLMError("503", 2.0, exponential=True))
    b = Stub("gemini", "B")
    assert await FallbackLLMClient([a, b]).generate("s", "u") == "B"


async def test_rate_limited_provider_sits_out_its_delay():
    clock = Clock()
    a = Stub("groq", RetryableLLMError("429", 30.0), "A")
    b = Stub("gemini", "B")
    chain = FallbackLLMClient([a, b], clock=clock)
    assert await chain.generate("s", "u") == "B"
    clock.t += 10
    assert await chain.generate("s", "u") == "B"  # groq still cooling down: not called
    assert a.calls == 1
    clock.t += 25
    assert await chain.generate("s", "u") == "A"


async def test_all_busy_raises_retryable_with_shortest_wait():
    a = Stub("groq", RetryableLLMError("429", 30.0))
    b = Stub("gemini", RetryableLLMError("503", 5.0, exponential=True))
    with pytest.raises(RetryableLLMError) as exc:
        await FallbackLLMClient([a, b]).generate("s", "u")
    assert exc.value.retry_after == 5.0


async def test_misconfigured_provider_is_skipped():
    a = Stub("groq", LLMConfigError("bad key"))
    b = Stub("gemini", "B")
    chain = FallbackLLMClient([a, b])
    assert await chain.generate("s", "u") == "B"
    assert await chain.generate("s", "u") == "B"
    assert a.calls == 1  # not retried while cooling down


async def test_all_misconfigured_raises_config_error():
    with pytest.raises(LLMConfigError):
        await FallbackLLMClient([Stub("a", LLMConfigError("x"))]).generate("s", "u")


def test_build_chain_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "g")
    monkeypatch.setattr(settings, "gemini_api_key", "k")
    chain = build_llm_client(["groq", "gemini"])
    assert isinstance(chain, FallbackLLMClient)
    assert chain.name.startswith("groq:") and " > gemini:" in chain.name


def test_build_skips_providers_without_keys(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "g")
    monkeypatch.setattr(settings, "cerebras_api_key", None)
    single = build_llm_client(["cerebras", "groq"])
    assert isinstance(single, OpenAICompatClient) and single.provider == "groq"


def test_build_with_nothing_configured(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", None)
    with pytest.raises(LLMConfigError, match="GROQ_API_KEY"):
        build_llm_client(["groq"])


def test_unknown_provider_name():
    with pytest.raises(LLMConfigError, match="Unknown LLM provider"):
        llm_chain.build_provider("skynet")


async def test_output_budget_is_sent():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=OK_BODY)

    await client(handler, max_output_tokens=4096).generate("s", "u")
    assert seen[0]["max_tokens"] == 4096


async def test_rate_limit_message_is_kept_for_the_logs():
    response = httpx.Response(429, json={"error": {"message": "Rate limit reached on tokens per minute (TPM)"}})
    with pytest.raises(RetryableLLMError) as exc:
        await client(lambda r: response).generate("s", "u")
    assert "tokens per minute" in str(exc.value)
