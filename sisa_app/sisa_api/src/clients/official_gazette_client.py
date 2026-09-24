"""HTTP access to the Official Gazette (www.officialgazette.gov.ph).

How the site works, as observed (Sept 2026):
- It is WordPress behind Cloudflare. Normal HTML pages (home, /?s= search,
  document pages, /wp-json) answer 403 to automated clients, either with a
  JavaScript "managed challenge" or a WAF "Sorry, you have been blocked" page.
  We do not try to get around that.
- The RSS feed is served without the challenge, and WordPress applies its
  normal site search to it: GET /feed/?s=<query>[&paged=N] returns up to 10
  matching posts per page, each with title, permalink, publication date,
  categories and the opening text of the document.
- Document permalinks look like /YYYY/MM/DD/<slug>/ (e.g.
  /2026/09/08/executive-order-no-124-s-2026/); some are section pages.
"""

import html
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

import httpx

from ..services.claims.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

ALLOWED_HOSTS = frozenset({"www.officialgazette.gov.ph", "officialgazette.gov.ph"})
_FEED_TAIL_RE = re.compile(r"\s*(?:\[(?:…|&#8230;|\.\.\.)\]|The post .*? appeared first on .*)$", re.S)


class OfficialGazetteClientError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class OfficialGazetteBlockedError(OfficialGazetteClientError):
    """The page is behind Cloudflare's browser challenge or WAF block."""


class OfficialGazetteURLError(ValueError):
    pass


@dataclass(frozen=True)
class FeedItem:
    title: str
    url: str
    published: str | None  # YYYY-MM-DD
    categories: list[str] = field(default_factory=list)
    excerpt: str | None = None


def validate_document_url(url: str) -> str:
    """Accept only https URLs on the Official Gazette host; returns a normalized URL."""
    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:
        raise OfficialGazetteURLError("Not a valid URL.") from exc
    if parts.scheme != "https":
        raise OfficialGazetteURLError("Only https:// Official Gazette URLs are allowed.")
    if parts.username or parts.password or parts.port:
        raise OfficialGazetteURLError("URLs with credentials or ports are not allowed.")
    if (parts.hostname or "").lower() not in ALLOWED_HOSTS:
        raise OfficialGazetteURLError("Only officialgazette.gov.ph URLs are allowed.")
    if parts.path in ("", "/"):
        raise OfficialGazetteURLError("The URL must point to a document, not the home page.")
    path = parts.path if parts.path.endswith("/") else parts.path + "/"
    return urlunsplit(("https", "www.officialgazette.gov.ph", path, "", ""))


def clean_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", html.unescape(value))
    text = _FEED_TAIL_RE.sub("", text)
    text = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
    return text or None


def _published(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw.strip()).date().isoformat()
    except (TypeError, ValueError):
        return None


def parse_feed(content: bytes) -> list[FeedItem]:
    """Parse an RSS search feed. Items without a title or an Official Gazette link are skipped."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise OfficialGazetteClientError(502, "The Official Gazette returned a malformed feed.") from exc
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise OfficialGazetteClientError(502, "The Official Gazette returned an unexpected feed format.")

    items: list[FeedItem] = []
    for node in channel.findall("item"):
        title = clean_text(node.findtext("title"))
        link = (node.findtext("link") or "").strip()
        if not title or not link:
            continue
        try:
            url = validate_document_url(link)
        except OfficialGazetteURLError:
            logger.info("skipping feed item with non-Gazette link: %s", link)
            continue
        categories = list(dict.fromkeys(c.text.strip() for c in node.findall("category") if c.text and c.text.strip()))
        items.append(
            FeedItem(
                title=title,
                url=url,
                published=_published(node.findtext("pubDate")),
                categories=categories,
                excerpt=clean_text(node.findtext("description")),
            )
        )
    return items


class _PageParser(HTMLParser):
    """Best-effort WordPress article extraction: og:title, article:published_time and
    the text of the element whose class includes 'entry-content'."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._in_title = False
        self._skip = 0
        self._content_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta" and a.get("content"):
            key = a.get("property") or a.get("name")
            if key:
                self.meta[key] = a["content"]
        elif tag == "title":
            self._in_title = True
        elif tag in ("script", "style", "noscript"):
            self._skip += 1
        if self._content_depth:
            self._content_depth += 1
        elif "entry-content" in (a.get("class") or "").split():
            self._content_depth = 1
        if self._content_depth and tag in ("p", "br", "li", "h1", "h2", "h3", "h4", "div"):
            self.text_parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1
        if self._content_depth:
            self._content_depth -= 1

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title_parts.append(data)
        elif self._content_depth:
            self.text_parts.append(data)


def parse_document_page(page: str) -> dict:
    parser = _PageParser()
    parser.feed(page)
    title = clean_text(parser.meta.get("og:title") or "".join(parser.title_parts))
    if title:
        title = re.sub(r"\s*[|–-]\s*Official Gazette.*$", "", title, flags=re.I)
    text = "\n".join(
        line.strip() for line in re.sub(r"[ \t\xa0]+", " ", "".join(parser.text_parts)).splitlines() if line.strip()
    )
    if not title:
        raise OfficialGazetteClientError(502, "The Official Gazette page did not contain a recognizable document.")
    published = parser.meta.get("article:published_time")
    return {"title": title, "published": published[:10] if published else None, "text": text or None}


_CLOUDFLARE_MARKERS = (
    "_cf_chl_opt",  # JavaScript "managed challenge" ("Just a moment...")
    "Just a moment",
    "Attention Required! | Cloudflare",  # WAF block ("Sorry, you have been blocked")
    "cf-error-details",
)


def _is_cloudflare_block(response: httpx.Response) -> bool:
    """Cloudflare answers automated clients with either a JS challenge or a WAF block page."""
    if response.headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    if response.status_code in (403, 503):
        body = response.text[:6000]
        return any(marker in body for marker in _CLOUDFLARE_MARKERS)
    return False


class OfficialGazetteClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 20.0,
        user_agent: str = "SISA-FactCheck/0.1",
        rate_limiter: RateLimiter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.user_agent = user_agent
        self.rate_limiter = rate_limiter
        self._transport = transport

    async def search_feed(self, query: str, page: int = 1) -> list[FeedItem]:
        params: dict[str, str | int] = {"s": query}
        if page > 1:
            params["paged"] = page
        response = await self._get(f"{self.base_url}/feed/", params, accept="application/rss+xml")
        if "xml" not in response.headers.get("content-type", ""):
            raise OfficialGazetteClientError(502, "The Official Gazette search did not return a feed.")
        return parse_feed(response.content)

    async def fetch_page(self, url: str) -> str:
        response = await self._get(validate_document_url(url), None, accept="text/html")
        return response.text

    async def _get(self, url: str, params: dict | None, accept: str) -> httpx.Response:
        if self.rate_limiter is not None:
            await self.rate_limiter.acquire()
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                headers={"User-Agent": self.user_agent, "Accept": accept},
                follow_redirects=True,
                transport=self._transport,
            ) as client:
                response = await client.get(url, params=params)
        except httpx.TimeoutException as exc:
            logger.warning("Official Gazette timeout (%s): %s", url, exc)
            raise OfficialGazetteClientError(504, "The Official Gazette did not respond in time.") from exc
        except httpx.RequestError as exc:
            logger.warning("Official Gazette unreachable (%s): %s", url, exc)
            raise OfficialGazetteClientError(502, "Could not reach the Official Gazette.") from exc

        if (response.url.host or "").lower() not in ALLOWED_HOSTS:
            raise OfficialGazetteClientError(502, "The Official Gazette redirected to an unexpected host.")
        if _is_cloudflare_block(response):
            logger.info("Official Gazette page blocked by Cloudflare for automated clients: %s", response.url)
            raise OfficialGazetteBlockedError(
                503,
                "This Official Gazette page is protected by Cloudflare and cannot be fetched "
                "automatically. Open the URL in a browser.",
            )
        if response.status_code == 429:
            retry = response.headers.get("retry-after")
            wait = f" Retry after {retry} seconds." if retry else ""
            if self.rate_limiter is not None and retry and retry.isdigit():
                self.rate_limiter.penalize(float(retry))
            raise OfficialGazetteClientError(503, f"Official Gazette rate limit reached.{wait}")
        if response.status_code == 404:
            raise OfficialGazetteClientError(404, "The Official Gazette page was not found.")
        if response.status_code >= 500:
            raise OfficialGazetteClientError(502, "The Official Gazette is currently experiencing a server error.")
        if response.status_code >= 400:
            raise OfficialGazetteClientError(
                502, f"The Official Gazette returned an unexpected HTTP {response.status_code} response."
            )
        return response
