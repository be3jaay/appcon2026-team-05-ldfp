"""Published fact-checks (Google Fact Check Tools API) for claims no data source covers.

Fact-checks are a SECONDARY source: another organisation's verdict on a claim.
A result only decides our verdict when (1) an LLM confirms it reviews the same
claim and (2) its rating maps clearly onto ours. Otherwise it is shown as a
related fact-check and the verdict is unchanged.
"""

import json
import logging
import re
import time
from dataclasses import dataclass

from ..clients.factcheck_client import FactCheckClient, FactCheckConfigError
from ..config import settings
from ..models.factcheck import FactCheckSearchResponse, PublishedFactCheck
from .claims.classifier import LLMClient, LLMConfigError, RetryableLLMError
from .claims.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

_STOPWORDS = frozenset(
    "the a an of on in at to by for that this is was were be been has have had it its and or as with from "
    "more than over about said says ang ng sa na ay mga si ni ito iyon noong raw daw po lang".split()
)

# Rating words -> our status. First match wins, so specific phrases come before general ones.
# Unmapped ratings (e.g. "Satire", "Explainer") never change the verdict.
# Order matters: "incorrect"/"inaccurate" must be caught before "correct"/"accurate".
_RATING_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"missing context|needs context|lacks context|kulang sa konteksto|half[ -]true|"
                r"unproven|unverified|no evidence|walang ebidensya|\bmixed\b|partly true", re.I), "NEEDS_CONTEXT"),
    (re.compile(r"false|fake|hoax|pants on fire|mislead|incorrect|inaccurate|fabricated|distorted|"
                r"exaggerat|no basis|\bwrong\b|\bmali\b|hindi totoo|\bpeke\b|nakaliligaw|\bscam\b|altered|"
                r"not true|untrue", re.I), "CONTRADICTED"),
    (re.compile(r"\btrue\b|\baccurate\b|\bcorrect\b|\btotoo\b|\btama\b", re.I), "SUPPORTED"),
]


def rating_status(rating: str | None) -> str | None:
    if not rating:
        return None
    for pattern, status in _RATING_RULES:
        if pattern.search(rating):
            return status
    return None


def keywords(text: str, limit: int = 8) -> str:
    words = [w for w in re.findall(r"[\w₱%.-]+", text.lower()) if w not in _STOPWORDS]
    return " ".join(words[:limit])


class _TTLCache:
    def __init__(self, seconds: float, max_entries: int = 256):
        self.seconds, self.max_entries = seconds, max_entries
        self._data: dict[str, tuple[float, list[PublishedFactCheck]]] = {}

    def get(self, key: str):
        hit = self._data.get(key)
        if hit and time.monotonic() - hit[0] < self.seconds:
            return hit[1]
        self._data.pop(key, None)
        return None

    def put(self, key: str, value: list[PublishedFactCheck]) -> None:
        if len(self._data) >= self.max_entries:
            self._data.pop(next(iter(self._data)))
        self._data[key] = (time.monotonic(), value)


_client: FactCheckClient | None = None
_cache = _TTLCache(settings.factcheck_cache_seconds)


def is_configured() -> bool:
    return bool(settings.factcheck_api_key)


def get_client() -> FactCheckClient:
    global _client
    if _client is None:
        _client = FactCheckClient(
            settings.factcheck_api_key,
            settings.factcheck_api_url,
            timeout=settings.factcheck_timeout_seconds,
            page_size=settings.factcheck_page_size,
        )
    return _client


async def _search_once(query: str, language: str | None) -> list[PublishedFactCheck]:
    key = f"{language or '*'}|{query.strip().casefold()}"
    cached = _cache.get(key)
    if cached is not None:
        return cached
    results = await get_client().search(query, language)
    _cache.put(key, results)
    return results


async def search(query: str, language: str | None = None, max_results: int = 10) -> FactCheckSearchResponse:
    """Search by the full text first; the API matches on words, so retry once with
    content words only when a long sentence finds nothing."""
    results = await _search_once(query, language)
    if not results:
        short = keywords(query)
        if short and short != query.lower():
            results = await _search_once(short, language)
    seen, unique = set(), []
    for r in results:
        if r.url not in seen:
            seen.add(r.url)
            unique.append(r)
    return FactCheckSearchResponse(query=query, results=unique[:max_results])


# --- same-claim matching ---------------------------------------------------------------

MATCH_PROMPT = """\
You decide whether published fact-checks review the SAME claim as a claim heard in a live \
Philippine transcript (English, Tagalog or Taglish).

"Same claim" means the fact-check assesses the same assertion: same subject, same key figure \
or event, same time frame when one is stated. A fact-check about the same topic but a \
different assertion, figure, person or period is NOT the same claim.

Return ONLY JSON: {"matches": [{"index": <number>, "same_claim": true|false}]} with one entry \
per numbered fact-check.
"""

_MATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"index": {"type": "integer"}, "same_claim": {"type": "boolean"}},
                "required": ["index", "same_claim"],
            },
        }
    },
    "required": ["matches"],
}


@dataclass(frozen=True)
class MatchResult:
    same: list[PublishedFactCheck]
    related: list[PublishedFactCheck]


def build_match_prompt(claim: str, checks: list[PublishedFactCheck]) -> str:
    lines = [f"CLAIM: {claim.strip()}", ""]
    for i, c in enumerate(checks, start=1):
        lines.append(f"FACT-CHECK {i}: reviewed claim: {c.claim_text or '(not given)'}")
        lines.append(f"  title: {c.title or '(none)'} | claimant: {c.claimant or '(unknown)'} | date: {c.claim_date or c.review_date or '?'}")
    return "\n".join(lines)


def parse_matches(raw: str, count: int) -> set[int] | None:
    text = (raw or "").strip()
    try:
        data = json.loads(text[text.find("{") : text.rfind("}") + 1])
    except (ValueError, TypeError):
        return None
    items = data.get("matches") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None
    same = set()
    for item in items:
        if isinstance(item, dict) and item.get("same_claim") is True:
            try:
                index = int(item.get("index"))
            except (TypeError, ValueError):
                continue
            if 1 <= index <= count:
                same.add(index)
    return same


async def match(
    claim: str, checks: list[PublishedFactCheck], llm: LLMClient | None, rate_limiter: RateLimiter | None = None
) -> MatchResult:
    """Without an LLM (or if it fails) nothing counts as the same claim."""
    if not checks or llm is None:
        return MatchResult(same=[], related=checks)
    if rate_limiter is not None:
        await rate_limiter.acquire()
    try:
        raw = await llm.generate(MATCH_PROMPT, build_match_prompt(claim, checks), _MATCH_SCHEMA)
    except (RetryableLLMError, LLMConfigError) as exc:
        logger.warning("fact-check matching unavailable: %s", exc)
        return MatchResult(same=[], related=checks)
    indices = parse_matches(raw, len(checks))
    if indices is None:
        logger.warning("fact-check matching returned unusable output: %.200r", raw)
        return MatchResult(same=[], related=checks)
    same = [c for i, c in enumerate(checks, start=1) if i in indices]
    related = [c for i, c in enumerate(checks, start=1) if i not in indices]
    return MatchResult(same=same, related=related)


__all__ = ["FactCheckConfigError", "is_configured", "search", "match", "rating_status", "keywords"]
