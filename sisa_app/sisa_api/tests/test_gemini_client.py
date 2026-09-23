"""Gemini error mapping, offline (no API calls)."""

import pytest
from google.genai import errors

from src.clients.gemini_client import GeminiClient, GeminiConfigError, retry_after_seconds


def api_error(code: int, status: str, details: list | None = None, message: str = "x") -> errors.APIError:
    return errors.APIError(code, {"error": {"code": code, "status": status, "message": message, "details": details or []}})


def test_retry_delay_from_retry_info():
    exc = api_error(429, "RESOURCE_EXHAUSTED", [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "38s"}])
    assert retry_after_seconds(exc) == 38


def test_retry_delay_from_message():
    exc = api_error(429, "RESOURCE_EXHAUSTED", message="Please retry in 3.669224848s.")
    assert retry_after_seconds(exc) == pytest.approx(3.669, abs=1e-3)


def test_no_delay_given_for_overload():
    assert retry_after_seconds(api_error(503, "UNAVAILABLE")) is None


def test_missing_key_is_a_config_error():
    with pytest.raises(GeminiConfigError):
        GeminiClient(api_key=None, model="gemini-3.6-flash")


async def test_retryable_status_becomes_retryable_error(monkeypatch):
    from src.services.claims.classifier import RetryableLLMError

    client = GeminiClient(api_key="fake", model="gemini-3.6-flash")

    async def boom(**_):
        raise api_error(503, "UNAVAILABLE")

    monkeypatch.setattr(client._client.aio.models, "generate_content", boom)
    with pytest.raises(RetryableLLMError) as exc:
        await client.generate("s", "u")
    assert exc.value.retry_after == 5.0 and exc.value.exponential


async def test_bad_request_is_not_retryable(monkeypatch):
    client = GeminiClient(api_key="fake", model="gemini-3.6-flash")

    async def boom(**_):
        raise api_error(400, "INVALID_ARGUMENT")

    monkeypatch.setattr(client._client.aio.models, "generate_content", boom)
    with pytest.raises(errors.APIError):
        await client.generate("s", "u")
