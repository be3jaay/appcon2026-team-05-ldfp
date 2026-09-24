"""Web search models behind one `search(system, user) -> SearchAnswer` interface.

- `WebSearchClient`: OpenAI search-enabled chat model (e.g. gpt-5-search-api). The
  message carries `annotations` of type "url_citation" for the pages it used.
- `GroqBrowserSearchClient`: Groq's built-in `browser_search` tool on gpt-oss. The
  message carries `executed_tools` with the search results and the pages it opened.

Only URLs that come from the search itself are returned as citations; those are the
only sources the service trusts.
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


def _retry_after(response: httpx.Response, default: float = 20) -> float:
    retry = response.headers.get("retry-after")
    return float(retry) if retry and retry.replace(".", "").isdigit() else default


def _raise_for_status(response: httpx.Response, provider: str, model: str) -> None:
    code = response.status_code
    if code in (401, 403):
        raise WebSearchConfigError(503, f"The {provider} web search rejected the API key.")
    if code == 404 or (code == 400 and "model" in response.text.lower()):
        raise WebSearchConfigError(503, f"{provider} web search model unavailable ({model}): {response.text[:200]}")
    if code == 429:
        if "insufficient_quota" in response.text or "credit_balance" in response.text:
            # No credits left: every call fails the same way until someone tops up.
            raise WebSearchConfigError(503, f"The {provider} account has no credits left for web search.")
        raise WebSearchError(503, f"{provider} web search rate limit reached.", retry_after=_retry_after(response))
    if code >= 400:
        raise WebSearchError(502, f"The {provider} web search API returned HTTP {code}.")


async def _post(url: str, body: dict, headers: dict, timeout: float, transport, provider: str) -> httpx.Response:
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            return await client.post(url, json=body, headers=headers)
    except httpx.TimeoutException as exc:
        raise WebSearchError(504, f"The {provider} web search did not respond in time.", retry_after=5) from exc
    except httpx.RequestError as exc:
        raise WebSearchError(502, f"Could not reach the {provider} web search API: {exc}") from exc


class WebSearchClient:
    name = "openai"

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
        response = await _post(self._url, body, self._headers, self._timeout, self._transport, self.name)
        _raise_for_status(response, self.name, self.model)
        try:
            data = response.json()
        except ValueError as exc:
            raise WebSearchError(502, "The web search API returned malformed JSON.") from exc
        return parse_answer(data)


def parse_groq_answer(data: dict) -> SearchAnswer:
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise WebSearchError(502, "The web search model returned an unexpected response.") from exc
    citations, seen = [], set()
    for tool in message.get("executed_tools") or []:
        results = (tool.get("search_results") or {}).get("results") if isinstance(tool, dict) else None
        for item in results or []:
            url = item.get("url") if isinstance(item, dict) else None
            if url and url not in seen:
                seen.add(url)
                citations.append(Citation(url=url, title=(item.get("title") or "").strip() or None))
    return SearchAnswer(content=message.get("content") or "", citations=citations)


class GroqBrowserSearchClient:
    """Groq gpt-oss with the built-in `browser_search` tool (free tier, uses the Groq key)."""

    name = "groq"

    def __init__(
        self,
        api_key: str | None,
        model: str,
        base_url: str = "https://api.groq.com/openai/v1",
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        if not api_key:
            raise WebSearchConfigError(503, "GROQ_API_KEY is not set.")
        self.model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._timeout = timeout
        self._transport = transport

    async def search(self, system: str, user: str) -> SearchAnswer:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "tools": [{"type": "browser_search"}],
            "tool_choice": "required",
            "reasoning_effort": "low",
            "temperature": 0,
        }
        response = await _post(self._url, body, self._headers, self._timeout, self._transport, self.name)
        _raise_for_status(response, self.name, self.model)
        try:
            data = response.json()
        except ValueError as exc:
            raise WebSearchError(502, "The web search API returned malformed JSON.") from exc
        return parse_groq_answer(data)
