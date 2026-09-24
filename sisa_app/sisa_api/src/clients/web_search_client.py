"""OpenAI search-enabled chat model (e.g. gpt-5-search-api) via Chat Completions.

The response message carries `annotations` of type "url_citation" for the pages
the search actually used; those are the only URLs we trust as sources.
"""

import logging
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)


class WebSearchError(RuntimeError):
    def __init__(self, status_code: int, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.retry_after = retry_after


class WebSearchConfigError(WebSearchError):
    """Missing or rejected key, or unknown model: not worth retrying."""


@dataclass(frozen=True)
class Citation:
    url: str
    title: str | None = None


@dataclass(frozen=True)
class SearchAnswer:
    content: str
    citations: list[Citation] = field(default_factory=list)


def parse_answer(data: dict) -> SearchAnswer:
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise WebSearchError(502, "The web search model returned an unexpected response.") from exc
    citations, seen = [], set()
    for a in message.get("annotations") or []:
        c = a.get("url_citation") if isinstance(a, dict) else None
        if isinstance(c, dict) and c.get("url") and c["url"] not in seen:
            seen.add(c["url"])
            citations.append(Citation(url=c["url"], title=c.get("title")))
    return SearchAnswer(content=message.get("content") or "", citations=citations)


class WebSearchClient:
    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not api_key:
            raise WebSearchConfigError(503, "OPENAI_API_KEY is not set.")
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._timeout = timeout
        self._transport = transport

    async def search(self, system: str, user: str) -> SearchAnswer:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            # Bias results toward the Philippines.
            "web_search_options": {"user_location": {"type": "approximate", "approximate": {"country": "PH"}}},
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(self._url, json=body, headers=self._headers)
        except httpx.TimeoutException as exc:
            raise WebSearchError(504, "The web search did not respond in time.", retry_after=5) from exc
        except httpx.RequestError as exc:
            raise WebSearchError(502, f"Could not reach the web search API: {exc}") from exc

        if response.status_code in (401, 403):
            raise WebSearchConfigError(503, "The web search API rejected the key. Check OPENAI_API_KEY.")
        if response.status_code == 404 or (response.status_code == 400 and "model" in response.text.lower()):
            raise WebSearchConfigError(503, f"Web search model unavailable ({self.model}): {response.text[:200]}")
        if response.status_code == 429:
            retry = response.headers.get("retry-after")
            raise WebSearchError(503, "Web search rate limit or quota reached.", retry_after=float(retry) if retry and retry.replace(".", "").isdigit() else 20)
        if response.status_code >= 400:
            raise WebSearchError(502, f"The web search API returned HTTP {response.status_code}.")
        try:
            data = response.json()
        except ValueError as exc:
            raise WebSearchError(502, "The web search API returned malformed JSON.") from exc
        return parse_answer(data)
