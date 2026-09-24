"""AI web search: the LAST fallback, for claims no data source or published
fact-check settles (idea from the feat/pdm-test branch, rebuilt with guardrails).

- One search-enabled LLM call per claim, paced and cached (paid API).
- Only pages the search actually used (url_citation annotations) count as
  sources; URLs the model merely lists are dropped.
- Each source is labelled by reliability (government, fact-checker, news,
  reference, other). A factual/misleading verdict that rests only on weak or
  unverified sources is downgraded to NEEDS_CONTEXT.
- It judges the claim only; it never guesses speakers' motives.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..clients.web_search_client import SearchAnswer, WebSearchClient, WebSearchConfigError, WebSearchError
from ..config import settings
from .claims.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

SEARCH_PROMPT = """\
You fact-check one claim heard in live Philippine public speech, using web search.

Search for reliable reports about the claim. Prefer, in order: official Philippine government \
sources (.gov.ph), established fact-checkers, established news organisations. Treat Wikipedia, \
blogs, forums and social media as weak. Judge the claim exactly as stated, including any \
amount, date, person or place. Do not guess anyone's motives or intentions.

Verdicts:
- "factual": reliable sources confirm the claim as stated.
- "misleading": reliable sources show it is false, or distorts the facts (wrong amount, \
wrong person, wrong date, missing key context that reverses its meaning).
- "needscontext": sources partly support it, disagree, or it is too early/unclear to say.
- "unfounded": no reliable source reports it.

Return ONLY JSON, no markdown:
{"verdict": "factual|misleading|needscontext|unfounded",
 "reasoning": "two or three plain sentences saying what the sources report",
 "sources": [{"url": "...", "quote": "the sentence from that page that supports your verdict"}]}
Only list pages you actually used.
"""

VERDICT_STATUS = {
    "factual": "SUPPORTED",
    "misleading": "CONTRADICTED",
    "needscontext": "NEEDS_CONTEXT",
    "unfounded": "INSUFFICIENT_EVIDENCE",
}

# Reliability by domain. Extend these lists as needed.
_FACT_CHECKERS = ("verafiles.org", "factrakers.org", "tsek.ph", "factcheck.afp.com", "pressone.ph", "snopes.com",
                  "politifact.com", "factcheck.org", "fullfact.org")
_NEWS = ("rappler.com", "inquirer.net", "philstar.com", "abs-cbn.com", "gmanetwork.com", "mb.com.ph",
         "bworldonline.com", "manilatimes.net", "pna.gov.ph", "news.tv5.com.ph", "onenews.ph", "sunstar.com.ph",
         "reuters.com", "apnews.com", "afp.com", "bbc.com", "bbc.co.uk", "aljazeera.com", "cnn.com",
         "bloomberg.com", "nikkei.com", "scmp.com", "straitstimes.com", "nytimes.com", "washingtonpost.com")
_REFERENCE = ("wikipedia.org", "britannica.com")
_STRONG = {"government", "fact_checker", "news"}


def reliability(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if host.endswith(".gov.ph") or host == "gov.ph" or host.endswith(".gov"):
        return "government"
    if any(host == d or host.endswith("." + d) for d in _FACT_CHECKERS):
        return "fact_checker"
    if any(host == d or host.endswith("." + d) for d in _NEWS):
        return "news"
    if any(host == d or host.endswith("." + d) for d in _REFERENCE):
        return "reference"
    return "other"


def normalize_url(url: str) -> str:
    """Drop tracking parameters (utm_*) and trailing slashes so cited and listed URLs compare equal."""
    parts = urlsplit(url.strip())
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_")])
    return urlunsplit((parts.scheme.lower(), (parts.hostname or "").lower(), parts.path.rstrip("/"), query, ""))


@dataclass(frozen=True)
class WebSource:
    url: str
    title: str | None
    reliability: str
    quote: str | None = None


@dataclass(frozen=True)
class WebCheck:
    status: str
    verdict: str
    reasoning: str
    sources: list[WebSource] = field(default_factory=list)
    downgraded: bool = False


def _parse_json(text: str) -> dict | None:
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text[text.find("{") : text.rfind("}") + 1])
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def interpret(answer: SearchAnswer) -> WebCheck | None:
    """Turn the model's answer into a checked result, or None if unusable."""
    data = _parse_json(answer.content)
    if data is None:
        return None
    verdict = str(data.get("verdict", "")).strip().lower().replace(" ", "").replace("_", "")
    if verdict not in VERDICT_STATUS:
        return None
    reasoning = str(data.get("reasoning") or "").strip()
    # Strip the model's inline citation markup "([site](url))" from the prose.
    reasoning = re.sub(r"\s*\(\[[^\]]*\]\([^)]*\)\)", "", reasoning).strip()

    cited = {normalize_url(c.url): c for c in answer.citations}
    sources: list[WebSource] = []
    for item in data.get("sources") or []:
        url = item.get("url") if isinstance(item, dict) else item if isinstance(item, str) else None
        if not url or normalize_url(url) not in cited:
            continue  # not a page the search actually returned
        c = cited[normalize_url(url)]
        quote = str(item.get("quote") or "").strip() if isinstance(item, dict) else ""
        sources.append(WebSource(url=c.url, title=c.title, reliability=reliability(c.url), quote=quote or None))
    if not sources:  # model listed nothing usable: fall back to what the search cited
        sources = [WebSource(url=c.url, title=c.title, reliability=reliability(c.url)) for c in answer.citations]
    seen, unique = set(), []
    for s in sources:
        if normalize_url(s.url) not in seen:
            seen.add(normalize_url(s.url))
            unique.append(s)
    order = {"government": 0, "fact_checker": 1, "news": 2, "reference": 3, "other": 4}
    unique.sort(key=lambda s: order[s.reliability])

    status = VERDICT_STATUS[verdict]
    downgraded = False
    if status in ("SUPPORTED", "CONTRADICTED") and not any(s.reliability in _STRONG for s in unique):
        status, downgraded = "NEEDS_CONTEXT", True
    return WebCheck(status=status, verdict=verdict, reasoning=reasoning, sources=unique[:5], downgraded=downgraded)


class _TTLCache:
    def __init__(self, seconds: float, max_entries: int = 256):
        self.seconds, self.max_entries = seconds, max_entries
        self._data: dict[str, tuple[float, WebCheck | None]] = {}

    def get(self, key: str):
        hit = self._data.get(key)
        if hit and time.monotonic() - hit[0] < self.seconds:
            return hit
        self._data.pop(key, None)
        return None

    def put(self, key: str, value: WebCheck | None) -> None:
        if len(self._data) >= self.max_entries:
            self._data.pop(next(iter(self._data)))
        self._data[key] = (time.monotonic(), value)


_client: WebSearchClient | None = None
_cache = _TTLCache(settings.web_search_cache_seconds)
_limiter = RateLimiter(settings.web_search_rpm)


# Set when the API rejects the key or model: stop calling (every call would fail the same way)
# and report web search as not connected until the server restarts with a working key.
_disabled_reason: str | None = None


def is_configured() -> bool:
    return bool(settings.openai_api_key) and _disabled_reason is None


def get_client() -> WebSearchClient:
    global _client
    if _client is None:
        _client = WebSearchClient(
            settings.openai_api_key,
            settings.web_search_model,
            base_url=settings.openai_base_url,
            timeout=settings.web_search_timeout_seconds,
        )
    return _client


async def check(claim: str, context: str | None = None) -> WebCheck | None:
    """None when the search failed or its answer was unusable (the caller keeps its result)."""
    key = claim.strip().casefold()
    hit = _cache.get(key)
    if hit is not None:
        return hit[1]
    user = f"CLAIM: {claim.strip()}"
    if context:
        user += f"\nSAID IN (transcript, may contain speech-recognition errors): {context.strip()[:1500]}"
    await _limiter.acquire()
    try:
        answer = await get_client().search(SEARCH_PROMPT, user)
    except WebSearchConfigError as exc:
        global _disabled_reason
        _disabled_reason = exc.message
        logger.error("web search disabled until restart: %s", exc.message)
        return None
    except WebSearchError as exc:
        logger.warning("web search failed: %s", exc.message)
        if exc.retry_after:
            _limiter.penalize(exc.retry_after)
        return None
    result = interpret(answer)
    if result is None:
        logger.warning("web search answer unusable: %.200r", answer.content)
    else:
        logger.info("web search: %s via %d sources (%s)", result.verdict, len(result.sources),
                    ", ".join(s.reliability for s in result.sources))
    _cache.put(key, result)
    return result
