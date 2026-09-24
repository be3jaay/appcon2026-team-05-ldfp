"""Google Fact Check Tools integration, offline.

The response fixture follows the API's documented shape (claims[].claimReview[]);
the error bodies are the ones the live API returned without / with a bad key.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from src.clients.factcheck_client import FactCheckClient, FactCheckClientError, FactCheckConfigError, parse_claims
from src.config import settings
from src.main import app
from src.models.claims import ClaimEntities
from src.models.verification import VerifyClaimRequest
from src.services import claim_verification_service as verification
from src.services import factcheck_service as svc

from .conftest import FakeLLM

URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"


def review(url, rating, publisher="Rappler", text="Claim text", title="Fact check", date="2025-09-10T00:00:00Z"):
    return {
        "text": text,
        "claimant": "Social media",
        "claimDate": "2025-09-01T00:00:00Z",
        "claimReview": [
            {
                "publisher": {"name": publisher, "site": publisher.lower() + ".com"},
                "url": url,
                "title": title,
                "reviewDate": date,
                "textualRating": rating,
                "languageCode": "en",
            }
        ],
    }


BODY = {
    "claims": [
        review("https://fc.example/a", "False", text="The Senate flagged ₱20 billion in the 2026 DPWH budget"),
        review("https://fc.example/b", "Misleading", publisher="VERA Files", text="DPWH budget was cut in half"),
        review("https://fc.example/a", "False"),  # duplicate URL
    ],
    "nextPageToken": "x",
}
NO_KEY = {"error": {"code": 403, "message": "Method doesn't allow unregistered callers", "status": "PERMISSION_DENIED"}}
BAD_KEY = {"error": {"code": 400, "message": "API key not valid.", "status": "INVALID_ARGUMENT",
                     "details": [{"reason": "API_KEY_INVALID"}]}}


class Api:
    def __init__(self, bodies: dict[str, dict] | None = None, default: dict | None = None):
        self.bodies = bodies or {}
        self.default = default if default is not None else {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json=self.bodies.get(request.url.params["query"], self.default))


@pytest.fixture
def api(monkeypatch):
    fake = Api()
    monkeypatch.setattr(settings, "factcheck_api_key", "test-key")
    monkeypatch.setattr(svc, "_client", FactCheckClient("test-key", URL, transport=httpx.MockTransport(fake)))
    monkeypatch.setattr(svc, "_cache", svc._TTLCache(600))
    return fake


# --- client ----------------------------------------------------------------------------


def test_parse_claims_one_item_per_review():
    items = parse_claims(BODY)
    assert len(items) == 3
    first = items[0]
    assert (first.publisher, first.rating, first.review_date, first.claim_date) == ("Rappler", "False", "2025-09-10", "2025-09-01")
    assert first.claim_text.startswith("The Senate flagged")
    assert parse_claims({}) == []  # no fact-checks found


async def test_client_sends_query_key_and_page_size():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=BODY)

    client = FactCheckClient("k", URL, page_size=7, transport=httpx.MockTransport(handler))
    await client.search("DPWH budget", language="en")
    params = seen[0].url.params
    assert (params["query"], params["key"], params["pageSize"], params["languageCode"]) == ("DPWH budget", "k", "7", "en")


@pytest.mark.parametrize(
    "response, error",
    [
        (httpx.Response(403, json=NO_KEY), FactCheckConfigError),
        (httpx.Response(400, json=BAD_KEY), FactCheckConfigError),
        (httpx.Response(429), FactCheckClientError),
        (httpx.Response(500), FactCheckClientError),
        (httpx.Response(200, content=b"<html>"), FactCheckClientError),
    ],
)
async def test_client_errors(response, error):
    with pytest.raises(error):
        await FactCheckClient("k", URL, transport=httpx.MockTransport(lambda r: response)).search("x y z")


def test_client_requires_key():
    with pytest.raises(FactCheckConfigError):
        FactCheckClient(None, URL)


# --- service ---------------------------------------------------------------------------


async def test_search_dedupes_and_falls_back_to_keywords(api):
    api.bodies = {"senate flagged ₱20 billion 2026 dpwh budget": BODY}
    res = await svc.search("The Senate flagged more than ₱20 billion in the 2026 DPWH budget")
    assert [r.url for r in res.results] == ["https://fc.example/a", "https://fc.example/b"]
    assert [r.url.params["query"] for r in api.requests] == [
        "The Senate flagged more than ₱20 billion in the 2026 DPWH budget",
        "senate flagged ₱20 billion 2026 dpwh budget",
    ]


async def test_search_is_cached(api):
    await svc.search("same query here")
    await svc.search("Same Query Here")
    assert len(api.requests) == 1  # second search served from the cache


@pytest.mark.parametrize(
    "rating, status",
    [("False", "CONTRADICTED"), ("Mostly false", "CONTRADICTED"), ("Misleading", "CONTRADICTED"),
     ("Incorrect", "CONTRADICTED"), ("Hindi totoo", "CONTRADICTED"), ("True", "SUPPORTED"),
     ("Accurate", "SUPPORTED"), ("Half true", "NEEDS_CONTEXT"), ("Missing context", "NEEDS_CONTEXT"),
     ("Satire", None), (None, None)],
)
def test_rating_status(rating, status):
    assert svc.rating_status(rating) == status


async def test_match_uses_llm_decision():
    checks = parse_claims(BODY)[:2]
    llm = FakeLLM({"matches": [{"index": 1, "same_claim": True}, {"index": 2, "same_claim": False}]})
    m = await svc.match("Senate flagged ₱20B in the 2026 DPWH budget", checks, llm)
    assert [c.url for c in m.same] == ["https://fc.example/a"]
    assert [c.url for c in m.related] == ["https://fc.example/b"]
    assert "FACT-CHECK 1: reviewed claim: The Senate flagged" in llm.calls[0]["user"]


@pytest.mark.parametrize("llm", [None, FakeLLM("garbage"), FakeLLM({"matches": "x"})])
async def test_match_without_usable_llm_marks_nothing_same(llm):
    checks = parse_claims(BODY)[:2]
    m = await svc.match("claim", checks, llm)
    assert m.same == [] and len(m.related) == 2


# --- verification ----------------------------------------------------------------------


def other(claim):
    return VerifyClaimRequest(claim=claim, claim_type="OTHER")


async def test_no_key_means_no_source_and_no_request(monkeypatch):
    monkeypatch.setattr(settings, "factcheck_api_key", None)
    res = await verification.verify(other("More than 20 billion pesos in the 2026 DPWH budget were flagged"))
    assert res.assessment.status == "NO_SOURCE"
    assert "not checked" in res.assessment.explanation and "OpenSTAT" not in res.assessment.explanation


async def test_matching_fact_check_becomes_the_verdict(api):
    api.default = BODY
    llm = FakeLLM({"matches": [{"index": 1, "same_claim": True}, {"index": 2, "same_claim": False}]})
    res = await verification.verify(other("The Senate flagged ₱20 billion in the 2026 DPWH budget"), llm=llm)
    assert res.assessment.status == "CONTRADICTED"
    assert res.assessment.method == "PUBLISHED_FACT_CHECK"
    assert "Rappler rated a matching claim “False” (2025-09-10)" in res.assessment.explanation
    direct, related = res.evidence[0], res.evidence[1]
    assert direct.source.source_type == "PUBLISHED_FACT_CHECK" and direct.relevance == "DIRECT"
    assert direct.data.rating == "False" and direct.source.url == "https://fc.example/a"
    assert related.relevance == "RELATED" and related.data.rating == "Misleading"


async def test_unrelated_fact_checks_are_listed_but_do_not_decide(api):
    api.default = BODY
    llm = FakeLLM({"matches": [{"index": 1, "same_claim": False}, {"index": 2, "same_claim": False}]})
    res = await verification.verify(other("Something else entirely about roads"), llm=llm)
    assert res.assessment.status == "NO_SOURCE"
    assert "Related published fact-checks are listed below." in res.assessment.explanation
    assert [e.relevance for e in res.evidence] == ["RELATED", "RELATED"]


async def test_conflicting_ratings_need_context(api):
    api.default = {"claims": [review("https://fc.example/x", "False"), review("https://fc.example/y", "True", publisher="Tsek.ph")]}
    llm = FakeLLM({"matches": [{"index": 1, "same_claim": True}, {"index": 2, "same_claim": True}]})
    res = await verification.verify(other("A disputed claim about a budget"), llm=llm)
    assert res.assessment.status == "NEEDS_CONTEXT"
    assert "rated this claim differently" in res.assessment.explanation


async def test_unmapped_rating_does_not_decide(api):
    api.default = {"claims": [review("https://fc.example/s", "Satire")]}
    llm = FakeLLM({"matches": [{"index": 1, "same_claim": True}]})
    res = await verification.verify(other("A satirical claim about a budget"), llm=llm)
    assert res.assessment.status == "NO_SOURCE"
    assert res.evidence[0].data.rating == "Satire"


async def test_fact_check_errors_keep_the_original_result(monkeypatch):
    monkeypatch.setattr(settings, "factcheck_api_key", "k")
    monkeypatch.setattr(svc, "_client", FactCheckClient("k", URL, transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    monkeypatch.setattr(svc, "_cache", svc._TTLCache(600))
    res = await verification.verify(other("Some claim about the budget"))
    assert res.assessment.status == "NO_SOURCE"


async def test_conclusive_data_results_skip_fact_checks(api, monkeypatch):
    from src.services import openstat_service

    from .test_claim_verification import openstat_response

    async def fake_check(req):
        return openstat_response("CONTRADICTED")

    monkeypatch.setattr(openstat_service, "check_claim", fake_check)
    res = await verification.verify(
        VerifyClaimRequest(claim="Unemployment was 5%", claim_type="STATISTICAL",
                           entities=ClaimEntities(metric="unemployment rate", value=5))
    )
    assert res.assessment.method == "OFFICIAL_DATA"
    assert api.requests == []  # official data answered; no fact-check lookup


async def test_unsupported_statistic_falls_through_to_fact_checks(api):
    api.default = BODY
    llm = FakeLLM({"matches": [{"index": 1, "same_claim": True}]})
    res = await verification.verify(
        VerifyClaimRequest(
            claim="More than 20 billion pesos in the proposed 2026 public works budget were flagged by the Senate",
            claim_type="STATISTICAL",
            entities=ClaimEntities(metric="budget amount flagged", value=20e9, unit="pesos", date="2026"),
        ),
        llm=llm,
    )
    assert res.assessment.method == "PUBLISHED_FACT_CHECK" and res.assessment.status == "CONTRADICTED"


# --- routes ----------------------------------------------------------------------------


def test_search_route_without_key_is_503(monkeypatch):
    monkeypatch.setattr(settings, "factcheck_api_key", None)
    monkeypatch.setattr(svc, "_client", None)
    r = TestClient(app).post("/api/v1/fact-checks/search", json={"query": "DPWH budget"})
    assert r.status_code == 503 and "FACTCHECK_API_KEY" in r.json()["detail"]


def test_search_route(api):
    api.default = BODY
    r = TestClient(app).post("/api/v1/fact-checks/search", json={"query": "DPWH budget flagged"})
    assert r.status_code == 200
    assert [x["rating"] for x in r.json()["results"]] == ["False", "Misleading"]


def test_sources_status(monkeypatch):
    monkeypatch.setattr(settings, "factcheck_api_key", None)
    body = TestClient(app).get("/api/v1/sources/status").json()
    assert body["factcheck"] is False and isinstance(body["llm"], bool)


async def test_search_uses_english_text_when_given(api):
    api.bodies = {"Davao City did not receive any national funds": BODY}
    llm = FakeLLM({"matches": [{"index": 1, "same_claim": True}]})
    res = await verification.verify(
        VerifyClaimRequest(
            claim="Walang natanggap na pondo ang Davao City mula sa national government",
            search_text="Davao City did not receive any national funds",
            claim_type="OTHER",
        ),
        llm=llm,
    )
    assert api.requests[0].url.params["query"] == "Davao City did not receive any national funds"
    assert res.assessment.method == "PUBLISHED_FACT_CHECK"


async def test_says_when_no_fact_check_was_found(api):
    res = await verification.verify(other("A brand new claim nobody has checked yet"))
    assert res.assessment.status == "NO_SOURCE"
    assert res.assessment.explanation.endswith("No published fact-check of it was found either.")
