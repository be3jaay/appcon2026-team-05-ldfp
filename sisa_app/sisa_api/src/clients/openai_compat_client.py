"""LLM client for OpenAI-compatible chat APIs (Groq, Cerebras, OpenRouter, ...).

Implements the claims `LLMClient` protocol with plain httpx. Uses JSON mode
(`response_format: json_object`), which these providers support widely; the
system prompt already spells out the JSON shape.
"""

import logging
import re
import time

import httpx

from ..services.claims.classifier import LLMConfigError, RetryableLLMError

logger = logging.getLogger(__name__)

_RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504, 529}
_OVERLOAD_BACKOFF_S = 2.0
_RATE_LIMIT_BACKOFF_S = 20.0


# Known providers: name -> base URL.
PROVIDERS: dict[str, str] = {
    "groq": "https://api.groq.com/openai/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


def _error_message(response: httpx.Response) -> str:
    try:
        error = response.json().get("error") or {}
        return str(error.get("message") or "") if isinstance(error, dict) else str(error)
    except ValueError:
        return response.text[:500]


def _parse_duration(raw: str) -> float | None:
    """ "7", "7.5s", "1m2.5s", "697ms", "2h3m" -> seconds."""
    raw = raw.strip().lower()
    try:
        return float(raw.rstrip("s"))
    except ValueError:
        pass
    total, number = 0.0, ""
    for part in raw.replace("ms", "u"):
        if part.isdigit() or part == ".":
            number += part
        elif number:
            total += float(number) * {"h": 3600, "m": 60, "s": 1, "u": 0.001}.get(part, 0)
            number = ""
    return total or None


def _retry_after(response: httpx.Response) -> float | None:
    if response.status_code == 429:
        # Groq says how long in the message ("Please try again in 4m20.5s"), including for
        # daily limits, where the reset headers describe other windows.
        if m := re.search(r"try again in ([\d.hms]+)", _error_message(response)):
            return _parse_duration(m.group(1).rstrip("."))
    headers = ["retry-after"]
    if response.status_code == 429:
        # Groq's x-ratelimit-reset-requests is the DAILY request window (can be ~25 min): only
        # wait for it when the error is about requests; a per-minute token limit resets in seconds.
        per_day = "requests per day" in _error_message(response).lower()
        headers += ["x-ratelimit-reset-requests"] if per_day else ["x-ratelimit-reset-tokens"]
    for header in headers:
        raw = response.headers.get(header, "").strip()
        if raw and (seconds := _parse_duration(raw)):
            return seconds
    return None


def _is_reasoning_model(model: str) -> bool:
    # Only these accept `reasoning_effort`; other models may reject the field.
    return any(tag in model.lower() for tag in ("gpt-oss", "qwen3", "deepseek-r1", "o3", "o4"))


class OpenAICompatClient:
    def __init__(
        self,
        provider: str,
        api_key: str | None,
        model: str,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
        reasoning_effort: str | None = None,
        max_output_tokens: int = 8192,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not api_key:
            raise LLMConfigError(f"{provider}: API key is not set.")
        self.provider = provider
        self.model = model
        self.base_url = (base_url or PROVIDERS[provider]).rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._timeout = timeout_seconds
        self.reasoning_effort = reasoning_effort
        self.max_output_tokens = max_output_tokens
        self._transport = transport

    @property
    def name(self) -> str:
        return f"{self.provider}:{self.model}"

    async def generate(self, system: str, user: str, response_schema: dict | None = None) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "max_tokens": self.max_output_tokens,
        }
        if self.reasoning_effort and _is_reasoning_model(self.model):
            body["reasoning_effort"] = self.reasoning_effort
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(f"{self.base_url}/chat/completions", json=body, headers=self._headers)
        except httpx.TimeoutException as exc:
            raise RetryableLLMError(f"{self.provider} timeout", _OVERLOAD_BACKOFF_S, exponential=True) from exc
        except httpx.RequestError as exc:
            raise RetryableLLMError(f"{self.provider} unreachable: {exc}", _OVERLOAD_BACKOFF_S, exponential=True) from exc

        if response.status_code in _RETRYABLE:
            delay = _retry_after(response)
            detail = _error_message(response)
            message = f"{self.provider} {response.status_code}" + (f": {detail[:240]}" if detail else "")
            if delay is not None:
                raise RetryableLLMError(message, delay)
            fallback = _RATE_LIMIT_BACKOFF_S if response.status_code == 429 else _OVERLOAD_BACKOFF_S
            raise RetryableLLMError(message, fallback, exponential=True)
        if response.status_code == 400 and "json_validate_failed" in response.text:
            # The model produced invalid JSON; a retry (or the next provider) usually works.
            raise RetryableLLMError(f"{self.provider} returned invalid JSON", _OVERLOAD_BACKOFF_S, exponential=True)
        if response.status_code in (401, 403):
            raise LLMConfigError(f"{self.provider}: API key rejected ({response.status_code}).")
        if response.status_code >= 400:
            detail = response.text[:300]
            if response.status_code == 404 or "model" in detail.lower():
                detail += await self._available_models_hint()
            raise LLMConfigError(f"{self.provider} {response.status_code}: {detail}")

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise RetryableLLMError(f"{self.provider} returned an unexpected body", _OVERLOAD_BACKOFF_S) from exc
        if data["choices"][0].get("finish_reason") == "length":
            logger.warning("%s hit the output limit (%d tokens); the answer may be cut off", self.name, self.max_output_tokens)

        usage = data.get("usage") or {}
        logger.info(
            "%s answered in %.1fs: prompt=%s cached=%s output=%s",
            self.name,
            time.perf_counter() - started,
            usage.get("prompt_tokens"),
            (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
            usage.get("completion_tokens"),
        )
        return content

    async def _available_models_hint(self) -> str:
        """When the configured model is wrong or retired, say which ones exist."""
        try:
            async with httpx.AsyncClient(timeout=10, transport=self._transport) as client:
                r = await client.get(f"{self.base_url}/models", headers=self._headers)
            ids = sorted(m["id"] for m in r.json().get("data", []) if "id" in m)
        except Exception:
            return ""
        return f" | available models: {', '.join(ids[:40])}" if ids else ""
