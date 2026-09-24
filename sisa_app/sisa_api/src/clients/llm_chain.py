"""Provider fallback for claim classification.

`FallbackLLMClient` tries providers in order. A provider that is busy (5xx),
rate-limited (429) or misconfigured is skipped for this call and the next one
answers, so one overloaded free tier doesn't stall the live transcript.
Rate-limited providers sit out their retry delay; misconfigured ones sit out
longer. When every provider is busy, a RetryableLLMError with the shortest
wait goes back to the detector, which retries through the shared limiter.
"""

import logging
import time

from ..config import settings
from ..services.claims.classifier import LLMClient, LLMConfigError, RetryableLLMError
from .gemini_client import GeminiClient
from .openai_compat_client import OpenAICompatClient

logger = logging.getLogger(__name__)

_CONFIG_ERROR_COOLDOWN_S = 300.0


class FallbackLLMClient:
    def __init__(self, clients: list[LLMClient], clock=time.monotonic):
        if not clients:
            raise LLMConfigError("No LLM provider configured.")
        self.clients = clients
        self._clock = clock
        self._cooldown_until: dict[int, float] = {}

    @property
    def name(self) -> str:
        return " > ".join(getattr(c, "name", type(c).__name__) for c in self.clients)

    async def generate(self, system: str, user: str, response_schema: dict | None = None) -> str:
        now = self._clock()
        waits: list[float] = []
        last_config_error: LLMConfigError | None = None
        tried = 0

        for i, client in enumerate(self.clients):
            label = getattr(client, "name", type(client).__name__)
            until = self._cooldown_until.get(i, 0.0)
            if until > now:
                waits.append(until - now)
                continue
            tried += 1
            try:
                return await client.generate(system, user, response_schema)
            except RetryableLLMError as exc:
                logger.warning("LLM %s unavailable (%s); trying next provider", label, exc)
                waits.append(exc.retry_after)
                if not exc.exponential:  # the provider told us how long to back off
                    self._cooldown_until[i] = self._clock() + exc.retry_after
            except LLMConfigError as exc:
                logger.error("LLM %s misconfigured: %s", label, exc)
                last_config_error = exc
                self._cooldown_until[i] = self._clock() + _CONFIG_ERROR_COOLDOWN_S

        if waits:
            raise RetryableLLMError(
                f"all LLM providers busy ({tried} tried)", max(0.5, min(waits)), exponential=tried > 0
            )
        raise last_config_error or LLMConfigError("No LLM provider could be used.")


def build_provider(name: str) -> LLMClient:
    common = {"timeout_seconds": settings.llm_timeout_seconds, "reasoning_effort": settings.llm_reasoning_effort}
    if name == "gemini":
        return GeminiClient(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
            timeout_seconds=settings.gemini_timeout_seconds,
            thinking_level=settings.gemini_thinking_level,
        )
    if name == "groq":
        return OpenAICompatClient("groq", settings.groq_api_key, settings.groq_model, **common)
    if name == "cerebras":
        return OpenAICompatClient("cerebras", settings.cerebras_api_key, settings.cerebras_model, **common)
    if name == "openrouter":
        return OpenAICompatClient("openrouter", settings.openrouter_api_key, settings.openrouter_model, **common)
    raise LLMConfigError(f"Unknown LLM provider '{name}'. Use groq, cerebras, openrouter or gemini.")


def build_llm_client(providers: list[str] | None = None) -> LLMClient:
    """The configured chain (LLM_PROVIDERS, or every provider with a key)."""
    names = providers if providers is not None else settings.llm_providers
    clients: list[LLMClient] = []
    for name in names:
        try:
            clients.append(build_provider(name))
        except LLMConfigError as exc:
            logger.warning("skipping LLM provider %s: %s", name, exc)
    if not clients:
        raise LLMConfigError(
            "No LLM provider configured. Set GROQ_API_KEY (or CEREBRAS_API_KEY, OPENROUTER_API_KEY, "
            "GEMINI_API_KEY) in sisa_api/.env."
        )
    return clients[0] if len(clients) == 1 else FallbackLLMClient(clients)
