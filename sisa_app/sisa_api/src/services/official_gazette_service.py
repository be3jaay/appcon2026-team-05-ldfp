"""Search and retrieve primary-source documents from the Official Gazette.

No LLM, no summaries: results carry the site's own titles, dates, URLs and text.
"""

import logging
import re
import time
from dataclasses import dataclass

from ..clients.official_gazette_client import (
    FeedItem,
    OfficialGazetteBlockedError,
    OfficialGazetteClient,
    OfficialGazetteClientError,
    parse_document_page,
    validate_document_url,
)
from ..config import settings
from ..models.official_gazette import (
    OfficialGazetteDocument,
    OfficialGazetteResult,
    OfficialGazetteSearchResponse,
    OfficialGazetteSource,
    StructuredLegalClaim,
)
from .claims.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# Canonical document type -> ways people write it (spoken, abbreviated, Filipino).
DOCUMENT_TYPES: dict[str, list[str]] = {
    "Executive Order": ["executive order", "e.o.", "eo"],
    "Republic Act": ["republic act", "batas republika", "r.a.", "ra"],
    "Proclamation": ["proclamation", "proklamasyon"],
    "Administrative Order": ["administrative order", "a.o.", "ao"],
    "Memorandum Order": ["memorandum order", "m.o.", "mo"],
    "Memorandum Circular": ["memorandum circular", "m.c.", "mc"],
    "Presidential Decree": ["presidential decree", "p.d.", "pd"],
    "Batas Pambansa": ["batas pambansa", "b.p.", "bp"],
    "Commonwealth Act": ["commonwealth act"],
    "Letter of Instruction": ["letter of instruction", "loi"],
    "General Order": ["general order"],
}
_ALIASES = sorted(
    ((alias, canonical) for canonical, aliases in DOCUMENT_TYPES.items() for alias in aliases),
    key=lambda pair: len(pair[0]),
    reverse=True,
)
_REFERENCE_RE = re.compile(
    r"(?<![\w.])(?P<type>" + "|".join(re.escape(a) for a, _ in _ALIASES) + r")"
    r"\s*(?:blg\.?|bilang|no\.?|nos\.?|number|#)?\s*(?P<number>\d{1,5}(?:-[a-z])?)\b"
    r"(?:\s*,?\s*(?:s\.|series\s+of|serye\s+ng)\s*(?P<year>\d{4}))?",
    re.IGNORECASE,
)
_ALIAS_TO_TYPE = {alias: canonical for alias, canonical in _ALIASES}

_STOPWORDS = frozenset(
    "the a an of on in at to by for that this these those is was were be been has have had "
    "it its and or as with from issued signed said says according president ang ng sa na ay "
    "si ni mga ito iyon noong".split()
)
_AUTHORITY_PATTERNS = [
    (re.compile(r"\bBY THE PRESIDENT OF THE PHILIPPINES\b", re.I), "President of the Philippines"),
    (re.compile(r"\bCONGRESS OF THE PHILIPPINES\b", re.I), "Congress of the Philippines"),
    (re.compile(r"\bOFFICE OF THE PRESIDENT\b", re.I), "Office of the President"),
]


@dataclass(frozen=True)
class DocumentReference:
    document_type: str
    number: str
    year: str | None = None

    @property
    def canonical(self) -> str:
        return f"{self.document_type} No. {self.number}"


def parse_reference(text: str, *, title: bool = False) -> DocumentReference | None:
    """Find 'Executive Order No. 124', 'EO 124', 'RA 11054', 'Batas Republika Blg. 123', ...
    With title=True the reference must open the text, so 'Roster of awardees under
    Executive Order 236' is not taken to *be* EO 236."""
    text = (text or "").strip()
    m = _REFERENCE_RE.match(text) if title else _REFERENCE_RE.search(text)
    if not m:
        return None
    doc_type = _ALIAS_TO_TYPE[m.group("type").lower()]
    return DocumentReference(doc_type, m.group("number").upper(), m.group("year"))


def issuing_authority(text: str | None) -> str | None:
    for pattern, authority in _AUTHORITY_PATTERNS:
        if text and pattern.search(text):
            return authority
    return None


def _keywords(query: str) -> str:
    words = [w for w in re.findall(r"[\w.]+", query.lower()) if w not in _STOPWORDS]
    return " ".join(words[:8])


class _TTLCache:
    def __init__(self, seconds: float, max_entries: int = 128):
        self.seconds = seconds
        self.max_entries = max_entries
        self._data: dict[str, tuple[float, list[FeedItem]]] = {}

    def get(self, key: str) -> list[FeedItem] | None:
        hit = self._data.get(key)
        if hit and time.monotonic() - hit[0] < self.seconds:
            return hit[1]
        self._data.pop(key, None)
        return None

    def put(self, key: str, value: list[FeedItem]) -> None:
        if len(self._data) >= self.max_entries:
            self._data.pop(next(iter(self._data)))
        self._data[key] = (time.monotonic(), value)


_client: OfficialGazetteClient | None = None
_cache = _TTLCache(settings.official_gazette_cache_seconds)


def get_client() -> OfficialGazetteClient:
    global _client
    if _client is None:
        _client = OfficialGazetteClient(
            base_url=settings.official_gazette_base_url,
            timeout=settings.official_gazette_timeout_seconds,
            user_agent=settings.official_gazette_user_agent,
            rate_limiter=RateLimiter(settings.official_gazette_rpm),
        )
    return _client


async def _search_feed(query: str) -> list[FeedItem]:
    key = query.strip().casefold()
    cached = _cache.get(key)
    if cached is not None:
        return cached
    items = await get_client().search_feed(query)
    _cache.put(key, items)
    return items


def _to_result(item: FeedItem, wanted: DocumentReference | None) -> OfficialGazetteResult:
    ref = parse_reference(item.title, title=True)
    direct = (
        wanted is not None
        and ref is not None
        and ref.document_type == wanted.document_type
        and ref.number == wanted.number
        and (wanted.year is None or ref.year is None or ref.year == wanted.year)
    )
    return OfficialGazetteResult(
        title=item.title,
        document_type=ref.document_type if ref else None,
        document_number=ref.number if ref else None,
        series_year=ref.year if ref else None,
        date=item.published,
        url=item.url,
        snippet=item.excerpt,
        categories=item.categories,
        relevance="DIRECT" if direct else "RELATED",
    )


async def search(query: str, limit: int = 10) -> OfficialGazetteSearchResponse:
    """Search the site. A document reference in the query ('... issued Executive Order
    No. 124') is searched in its canonical form; results naming that exact document are
    marked DIRECT and listed first."""
    wanted = parse_reference(query)
    search_query = wanted.canonical if wanted else query.strip()
    items = await _search_feed(search_query)

    # Natural-language claims can be too specific for the site's AND search: retry once
    # with content words only.
    if not items and wanted is None:
        fallback = _keywords(query)
        if fallback and fallback != search_query.lower():
            search_query = fallback
            items = await _search_feed(search_query)

    results = [_to_result(item, wanted) for item in items]
    results.sort(key=lambda r: r.relevance != "DIRECT")  # stable: keeps the site's order otherwise
    logger.info(
        "official gazette search %r -> %d results (%d direct)",
        search_query,
        len(results),
        sum(r.relevance == "DIRECT" for r in results),
    )
    return OfficialGazetteSearchResponse(
        source=OfficialGazetteSource(base_url=settings.official_gazette_base_url.rstrip("/") + "/"),
        query=query,
        search_query=search_query,
        results=results[:limit],
    )


def query_for_claim(claim: StructuredLegalClaim) -> str:
    """Build a search query from a structured legal claim (produced elsewhere)."""
    if claim.subject and claim.object:
        ref = parse_reference(f"{claim.subject} No. {claim.object}")
        if ref:
            year = re.search(r"\b(19|20)\d{2}\b", claim.context.date or "")
            return ref.canonical + (f", s. {year.group(0)}" if year else "")
    return claim.claim


async def search_for_claim(claim: StructuredLegalClaim, limit: int = 10) -> OfficialGazetteSearchResponse:
    return await search(query_for_claim(claim), limit=limit)


async def get_document(url: str) -> OfficialGazetteDocument:
    """Retrieve one document. When the page is behind the site's browser challenge, fall
    back to the document's own entry in the site feed (title, date, opening text)."""
    url = validate_document_url(url)
    try:
        page = await get_client().fetch_page(url)
        parsed = parse_document_page(page)
        ref = parse_reference(parsed["title"], title=True)
        return OfficialGazetteDocument(
            title=parsed["title"],
            document_type=ref.document_type if ref else None,
            document_number=ref.number if ref else None,
            series_year=ref.year if ref else None,
            date=parsed["published"],
            issuing_authority=issuing_authority(parsed["text"]),
            text=parsed["text"],
            text_scope="FULL_PAGE",
            url=url,
        )
    except OfficialGazetteBlockedError:
        logger.info("document page blocked, using feed entry: %s", url)

    slug = url.rstrip("/").rsplit("/", 1)[-1]
    items = await _search_feed(slug.replace("-", " "))
    item = next((i for i in items if i.url == url), None)
    if item is None:
        raise OfficialGazetteClientError(
            502,
            "The document page is protected by a browser challenge, and the document was not "
            "found in the site's feed. Open the URL in a browser.",
        )
    ref = parse_reference(item.title, title=True)
    return OfficialGazetteDocument(
        title=item.title,
        document_type=ref.document_type if ref else None,
        document_number=ref.number if ref else None,
        series_year=ref.year if ref else None,
        date=item.published,
        issuing_authority=issuing_authority(item.excerpt),
        text=item.excerpt,
        text_scope="FEED_EXCERPT",
        url=url,
        categories=item.categories,
    )
