import logging
import re
from typing import Any

from google import genai
from google.genai import errors, types

from ..services.claims.classifier import LLMConfigError, RetryableLLMError

logger = logging.getLogger(__name__)

_RETRYABLE_CODES = {429, 500, 502, 503, 504}
_DEFAULT_BACKOFF_S = {429: 30.0}  # used when the response carries no retryDelay
_OVERLOAD_BACKOFF_S = 5.0


class GeminiConfigError(LLMConfigError):
    pass


def retry_after_seconds(exc: errors.APIError) -> float | None:
    """Gemini puts the wait in error.details[RetryInfo].retryDelay ("38s") and in the message.
    None when the response gives no delay."""
    details: Any = exc.details
    if isinstance(details, dict):
        for item in (details.get("error") or {}).get("details") or []:
            delay = isinstance(item, dict) and item.get("retryDelay")
            if isinstance(delay, str) and (m := re.fullmatch(r"([\d.]+)s", delay)):
                return float(m.group(1))
    if m := re.search(r"retry in ([\d.]+)s", str(exc)):
        return float(m.group(1))
    return None


class GeminiClient:
    """Implements the claims `LLMClient` protocol on Google Gemini.

    SDK-level retries are off: retries are paced by the detector through the
    shared rate limiter, so a retry never burns quota another session needs."""

    def __init__(
        self,
        api_key: str | None,
        model: str,
        timeout_seconds: float = 30.0,
        thinking_level: str | None = "low",
    ):
        if not api_key:
            raise GeminiConfigError(
                "Server is missing GEMINI_API_KEY. Add it to .env (get one from aistudio.google.com)."
            )
        self.model = model
        self.name = f"gemini:{model}"
        self.thinking_level = thinking_level.upper() if thinking_level else None
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=int(timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    async def generate(self, system: str, user: str, response_schema: dict | None = None) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0,
            response_mime_type="application/json",
            response_json_schema=response_schema,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        if self.thinking_level:
            config.thinking_config = types.ThinkingConfig(thinking_level=self.thinking_level)
        try:
            response = await self._client.aio.models.generate_content(
                model=self.model, contents=user, config=config
            )
        except errors.APIError as exc:
            if exc.code in (401, 403):
                raise LLMConfigError(f"gemini: API key rejected ({exc.code} {exc.status}).") from exc
            if exc.code in _RETRYABLE_CODES:
                delay = retry_after_seconds(exc)
                if delay is not None:
                    raise RetryableLLMError(f"{exc.code} {exc.status}", delay) from exc
                fallback = _DEFAULT_BACKOFF_S.get(exc.code, _OVERLOAD_BACKOFF_S)
                raise RetryableLLMError(f"{exc.code} {exc.status}", fallback, exponential=True) from exc
            raise
        usage = response.usage_metadata
        if usage is not None:
            logger.info(
                "gemini tokens: prompt=%s cached=%s output=%s",
                usage.prompt_token_count,
                usage.cached_content_token_count,
                usage.candidates_token_count,
            )
        return response.text or ""
