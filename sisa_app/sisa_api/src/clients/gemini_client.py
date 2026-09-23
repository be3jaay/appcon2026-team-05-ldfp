import logging

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


class GeminiConfigError(RuntimeError):
    pass


class GeminiClient:
    """Implements the claims `LLMClient` protocol on Google Gemini."""

    def __init__(
        self,
        api_key: str | None,
        model: str,
        timeout_seconds: float = 30.0,
        thinking_level: str | None = "low",
        retry_attempts: int = 3,
    ):
        if not api_key:
            raise GeminiConfigError(
                "Server is missing GEMINI_API_KEY. Add it to .env (get one from aistudio.google.com)."
            )
        self.model = model
        self.thinking_level = thinking_level.upper() if thinking_level else None
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=int(timeout_seconds * 1000),
                # Gemini returns 503 under load and 429 past the per-minute quota.
                retry_options=types.HttpRetryOptions(
                    attempts=retry_attempts,
                    initial_delay=2.0,
                    max_delay=30.0,
                    http_status_codes=[429, 500, 503, 504],
                ),
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
        response = await self._client.aio.models.generate_content(
            model=self.model, contents=user, config=config
        )
        usage = response.usage_metadata
        if usage is not None:
            logger.debug(
                "gemini tokens: prompt=%s cached=%s output=%s",
                usage.prompt_token_count,
                usage.cached_content_token_count,
                usage.candidates_token_count,
            )
        return response.text or ""
