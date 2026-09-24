"""Official Gazette client/service/routes, offline.

Fixtures in tests/fixtures/official_gazette/ are real responses captured from
www.officialgazette.gov.ph (Sept 2026): search feeds and a Cloudflare block page.
"""

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from src.clients.official_gazette_client import (
    OfficialGazetteBlockedError,
    OfficialGazetteClient,
    OfficialGazetteClientError,
    OfficialGazetteURLError,
    parse_document_page,
    parse_feed,
    validate_document_url,
)
from src.main import app
from src.models.official_gazette import StructuredClaimContext, StructuredLegalClaim
from src.services import official_gazette_service as svc

FIXTURES = Path(__file__).parent / "fixtures" / "official_gazette"
FEED_EO_124 = (FIXTURES / "search_eo_124.xml").read_bytes()
FEED_RA = (FIXTURES / "search_republic_act.xml").read_bytes()
FEED_EMPTY = (FIXTURES / "search_empty.xml").read_bytes()
CHALLENGE = (FIXTURES / "cloudflare_challenge.html").read_bytes()
WAF_BLOCK = b"<html><head><title>Attention Required! | Cloudflare</title></head><body>Sorry, you have been blocked</body></html>"
RSS = {"content-type": "application/rss+xml; charset=UTF-8"}
EO_124_URL = "https://www.officialgazette.gov.ph/2026/09/08/executive-order-no-124-s-2026/"


class Site:
    """Fake officialgazette.gov.ph: routes requests to canned responses and records them."""

    def __init__(self, feeds: dict[str, bytes] | None = None, page: httpx.Response | None = None):
        self.feeds = feeds or {}
        self.page = page
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/feed/":
            q = request.url.params.get("s", "").lower()
            return httpx.Response(200, headers=RSS, content=self.feeds.get(q, FEED_EMPTY))
        return self.page or httpx.Response(403, headers={"cf-mitigated": "challenge"}, content=CHALLENGE)


@pytest.fixture
def site(monkeypatch):
    fake = Site(
        feeds={
            "executive order no. 124": FEED_EO_124,
            "republic act": FEED_RA,
            "executive order no 124 s 2026": FEED_EO_124,
        }
    )
    client = OfficialGazetteClient("https://www.officialgazette.gov.ph", transport=httpx.MockTransport(fake))
    monkeypatch.setattr(svc, "_client", client)
    monkeypatch.setattr(svc, "_cache", svc._TTLCache(600))
    return fake


# --- parsing -----------------------------------------------------------------------


def test_parse_real_feed():
    items = parse_feed(FEED_EO_124)
    assert len(items) == 10
    first = items[0]
    assert first.title == "Executive Order No. 124, s. 2026"
    assert first.url == EO_124_URL
    assert first.published == "2026-09-08"
    assert "Executive Orders" in first.categories
    assert first.excerpt.startswith("MALACAÑAN PALACE MANILA BY THE PRESIDENT OF THE PHILIPPINES")
    assert all(i.url.startswith("https://www.officialgazette.gov.ph/") for i in items)


def test_parse_empty_feed():
    assert parse_feed(FEED_EMPTY) == []


@pytest.mark.parametrize("content", [b"not xml", b"<html><body>hi</body></html>", b"<rss><nochannel/></rss>"])
def test_parse_malformed_feed(content):
    with pytest.raises(OfficialGazetteClientError) as exc:
        parse_feed(content)
    assert exc.value.status_code == 502


def test_feed_items_with_foreign_links_are_skipped():
    feed = (
        b"<rss><channel><item><title>X</title><link>https://evil.example.com/a/</link></item>"
        b"<item><title>Y</title><link>https://www.officialgazette.gov.ph/2026/01/01/y/</link></item></channel></rss>"
    )
    assert [i.title for i in parse_feed(feed)] == ["Y"]


@pytest.mark.parametrize(
    "url",
    [
        "http://www.officialgazette.gov.ph/2026/09/08/x/",
        "https://evil.example.com/2026/09/08/x/",
        "https://officialgazette.gov.ph.evil.com/x/",
        "https://user:pw@www.officialgazette.gov.ph/x/",
        "https://www.officialgazette.gov.ph:8443/x/",
        "https://www.officialgazette.gov.ph/",
        "javascript:alert(1)",
    ],
)
def test_url_validation_rejects(url):
    with pytest.raises(OfficialGazetteURLError):
        validate_document_url(url)


def test_url_validation_normalizes():
    assert (
        validate_document_url("https://officialgazette.gov.ph/2026/09/08/executive-order-no-124-s-2026?utm=x")
        == EO_124_URL
    )


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Executive Order No. 124", ("Executive Order", "124", None)),
        ("The President issued Executive Order No. 124", ("Executive Order", "124", None)),
        ("Executive Order No. 124, s. 2026", ("Executive Order", "124", "2026")),
        ("Proclamation No. 1449 s. 2026", ("Proclamation", "1449", "2026")),
        ("RA 11054", ("Republic Act", "11054", None)),
        ("EO 70 series of 2018", ("Executive Order", "70", "2018")),
        ("Batas Republika Blg. 10354", ("Republic Act", "10354", None)),
        ("1987 Constitution", None),
        ("para 2 taon na", None),
    ],
)
def test_parse_reference(text, expected):
    ref = svc.parse_reference(text)
    assert (ref and (ref.document_type, ref.number, ref.year)) == expected


def test_title_reference_must_open_the_title():
    assert svc.parse_reference("Roster of Presidential Awardees under Executive Order 236", title=True) is None


def test_parse_document_page_generic_wordpress():
    # Synthetic: real document pages are Cloudflare-protected, so their exact markup is unverified.
    page = """<html><head><title>Executive Order No. 1, s. 2099 | GOVPH</title>
    <meta property="og:title" content="Executive Order No. 1, s. 2099"/>
    <meta property="article:published_time" content="2099-01-02T10:00:00+00:00"/></head>
    <body><div class="entry-content"><p>BY THE PRESIDENT OF THE PHILIPPINES</p>
    <p>WHEREAS, ...</p><script>x()</script></div><footer>links</footer></body></html>"""
    parsed = parse_document_page(page)
    assert parsed == {
        "title": "Executive Order No. 1, s. 2099",
        "published": "2099-01-02",
        "text": "BY THE PRESIDENT OF THE PHILIPPINES\nWHEREAS, ...",
    }


# --- client --------------------------------------------------------------------------


def client_for(handler) -> OfficialGazetteClient:
    return OfficialGazetteClient("https://www.officialgazette.gov.ph", transport=httpx.MockTransport(handler))


async def test_client_uses_feed_search_with_user_agent():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, headers=RSS, content=FEED_EO_124)

    items = await client_for(handler).search_feed("Executive Order No. 124")
    assert len(items) == 10
    assert seen[0].url.path == "/feed/" and seen[0].url.params["s"] == "Executive Order No. 124"
    assert seen[0].headers["user-agent"].startswith("SISA-FactCheck")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403, headers={"cf-mitigated": "challenge"}, content=CHALLENGE),
        httpx.Response(403, content=CHALLENGE),
        httpx.Response(403, content=WAF_BLOCK),
    ],
)
async def test_client_detects_cloudflare_blocks(response):
    with pytest.raises(OfficialGazetteBlockedError):
        await client_for(lambda r: response).fetch_page(EO_124_URL)


@pytest.mark.parametrize(
    "response, status, text",
    [
        (httpx.Response(429, headers={"retry-after": "30"}), 503, "Retry after 30"),
        (httpx.Response(404), 404, "not found"),
        (httpx.Response(500), 502, "server error"),
        (httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html/>"), 502, "did not return a feed"),
    ],
)
async def test_client_http_errors(response, status, text):
    with pytest.raises(OfficialGazetteClientError) as exc:
        await client_for(lambda r: response).search_feed("x")
    assert exc.value.status_code == status and text in exc.value.message


async def test_client_timeout():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(OfficialGazetteClientError) as exc:
        await client_for(handler).search_feed("x")
    assert exc.value.status_code == 504


async def test_client_rejects_non_gazette_url_before_any_request():
    calls = []
    with pytest.raises(OfficialGazetteURLError):
        await client_for(lambda r: calls.append(r)).fetch_page("https://evil.example.com/x/")
    assert calls == []


# --- service -------------------------------------------------------------------------


async def test_search_marks_exact_document_direct_and_first(site):
    res = await svc.search("The President issued Executive Order No. 124")
    assert res.search_query == "Executive Order No. 124"  # the claim is searched in canonical form
    direct = [r for r in res.results if r.relevance == "DIRECT"]
    assert [r.title for r in direct] == ["Executive Order No. 124, s. 2026", "Executive Order No. 124, s. 2021"]
    assert res.results[: len(direct)] == direct
    assert direct[0].document_type == "Executive Order" and direct[0].series_year == "2026"
    assert res.source.base_url == "https://www.officialgazette.gov.ph/"


async def test_search_generic_query(site):
    res = await svc.search("Republic Act", limit=5)
    assert len(res.results) == 5
    assert all(r.relevance == "RELATED" for r in res.results)
    assert any(r.document_type == "Republic Act" for r in res.results)


async def test_search_no_results_retries_once_with_keywords(site):
    res = await svc.search("the unknowable zxqv document of nothing")
    assert res.results == []
    queries = [r.url.params["s"] for r in site.requests]
    assert queries == ["the unknowable zxqv document of nothing", "unknowable zxqv document nothing"]


async def test_search_is_cached(site):
    await svc.search("Executive Order No. 124")
    await svc.search("executive order no. 124")
    assert len(site.requests) == 1


async def test_year_in_query_limits_direct_matches(site):
    res = await svc.search("Executive Order No. 124, s. 2021")
    assert [r.series_year for r in res.results if r.relevance == "DIRECT"] == ["2021"]


def test_query_for_structured_claim():
    claim = StructuredLegalClaim(
        claim="The President issued Executive Order No. 124",
        subject="Executive Order",
        predicate="issued",
        object="124",
        context=StructuredClaimContext(date="September 2026", geography="Philippines"),
    )
    assert svc.query_for_claim(claim) == "Executive Order No. 124, s. 2026"
    assert svc.query_for_claim(StructuredLegalClaim(claim="Some law about rice")) == "Some law about rice"


async def test_get_document_falls_back_to_feed_when_blocked(site):
    doc = await svc.get_document(EO_124_URL)
    assert doc.text_scope == "FEED_EXCERPT"
    assert doc.title == "Executive Order No. 124, s. 2026"
    assert (doc.document_type, doc.document_number, doc.series_year) == ("Executive Order", "124", "2026")
    assert doc.date == "2026-09-08"
    assert doc.issuing_authority == "President of the Philippines"
    assert "EDUCATION PHILIPPINES (EDUPHIL) PROGRAM" in doc.text
    assert doc.url == EO_124_URL


async def test_get_document_blocked_and_not_in_feed(site):
    with pytest.raises(OfficialGazetteClientError) as exc:
        await svc.get_document("https://www.officialgazette.gov.ph/2026/01/01/unknown-document/")
    assert "browser" in exc.value.message


# --- routes --------------------------------------------------------------------------


def test_search_route(site):
    r = TestClient(app).post("/api/v1/official-gazette/search", json={"query": "Executive Order No. 124", "limit": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["source"]["source_type"] == "OFFICIAL_DOCUMENT"
    assert body["results"][0]["url"] == EO_124_URL
    assert len(body["results"]) == 3


def test_search_route_empty(site):
    r = TestClient(app).post("/api/v1/official-gazette/search", json={"query": "zxqvbnmlkjh"})
    assert r.status_code == 200 and r.json()["results"] == []


@pytest.mark.parametrize("body", [{}, {"query": ""}, {"query": "x" * 301}, {"query": "ok", "limit": 0}])
def test_search_route_validation(body):
    assert TestClient(app).post("/api/v1/official-gazette/search", json=body).status_code == 422


def test_document_route_rejects_foreign_url(site):
    r = TestClient(app).post("/api/v1/official-gazette/document", json={"url": "https://evil.example.com/x/"})
    assert r.status_code == 400
    assert site.requests == []


def test_upstream_error_maps_to_http(monkeypatch):
    client = OfficialGazetteClient(
        "https://www.officialgazette.gov.ph", transport=httpx.MockTransport(lambda r: httpx.Response(429))
    )
    monkeypatch.setattr(svc, "_client", client)
    monkeypatch.setattr(svc, "_cache", svc._TTLCache(600))
    r = TestClient(app).post("/api/v1/official-gazette/search", json={"query": "anything at all"})
    assert r.status_code == 503 and "rate limit" in r.json()["detail"]
