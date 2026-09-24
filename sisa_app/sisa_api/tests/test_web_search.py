"""AI web search fallback (OpenAI search model), offline.

Responses follow the documented Chat Completions shape for search models:
choices[0].message.content + annotations[{type: "url_citation", url_citation: {url, title}}].
"""

import json

import httpx
import pytest

from src.clients.web_search_client import (
    Citation,
    SearchAnswer,
    WebSearchClient,
    WebSearchConfigError,
    WebSearchError,
    parse_answer,
)
from src.config import settings
from src.models.claims import ClaimEntities
from src.models.verification import VerifyClaimRequest
from src.services import claim_verification_service as verification
from src.services import web_search_service as svc

URL = "https://api.openai.com/v1"


def completion(payload: dict | str, citations: list[tuple[str, str]]) -> dict:
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                    "annotations": [
                        {"type": "url_citation", "url_citation": {"url": u, "title": t, "start_index": 0, "end_index": 1}}
                        for u, t in citations
                    ],
                }
            }
        ]
    }


GOV = ("https://www.dmw.gov.ph/news/seafarers-first-margo", "DMW identifies 40 Filipino seafarers")
NEWS = ("https://news.abs-cbn.com/news/2026/9/24/seafarers?utm_source=openai", "40 Pinoy seafarers safe")
BLOG = ("https://random-blog.example.com/post", "My take")
WIKI = ("https://en.wikipedia.org/wiki/Singapore_Strait", "Singapore Strait")


class Api:
    def __init__(self, body=None, status=200, headers=None):
        self.body, self.status, self.headers = body, status, headers or {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request):
        self.requests.append(request)
        return httpx.Response(self.status, json=self.body, headers=self.headers)


@pytest.fixture
def api(monkeypatch):
    fake = Api()
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "factcheck_api_key", None)  # isolate from the fact-check step
    monkeypatch.setattr(svc, "_client", WebSearchClient("sk-test", "gpt-5-search-api", URL, transport=httpx.MockTransport(fake)))
    monkeypatch.setattr(svc, "_cache", svc._TTLCache(600))
    monkeypatch.setattr(svc, "_limiter", svc.RateLimiter(0))
    return fake


def other(claim, **kw):
    return VerifyClaimRequest(claim=claim, claim_type="OTHER", **kw)


# --- client --------------------------------------------------------------------------


def test_parse_answer_keeps_cited_urls_only_once():
    data = completion("{}", [GOV, GOV, NEWS])
    answer = parse_answer(data)
    assert [c.url for c in answer.citations] == [GOV[0], NEWS[0]]


async def test_client_request_shape():
    fake = Api(completion("{}", []))
    await WebSearchClient("sk", "gpt-5-search-api", URL, transport=httpx.MockTransport(fake)).search("S", "U")
    req = fake.requests[0]
    body = json.loads(req.content)
    assert str(req.url) == "https://api.openai.com/v1/chat/completions"
    assert req.headers["authorization"] == "Bearer sk"
    assert body["model"] == "gpt-5-search-api"
    assert body["web_search_options"]["user_location"]["approximate"]["country"] == "PH"
    assert "temperature" not in body  # search models reject sampling parameters


@pytest.mark.parametrize(
    "status, error",
    [(401, WebSearchConfigError), (404, WebSearchConfigError), (429, WebSearchError), (500, WebSearchError)],
)
async def test_client_errors(status, error):
    fake = Api({"error": {"message": "x"}}, status=status)
    with pytest.raises(error):
        await WebSearchClient("sk", "m", URL, transport=httpx.MockTransport(fake)).search("S", "U")


def test_client_requires_key():
    with pytest.raises(WebSearchConfigError):
        WebSearchClient(None, "m")


# --- interpretation guardrails ---------------------------------------------------------


@pytest.mark.parametrize(
    "url, level",
    [(GOV[0], "government"), ("https://pna.gov.ph/x", "government"), ("https://verafiles.org/a", "fact_checker"),
     (NEWS[0], "news"), (WIKI[0], "reference"), (BLOG[0], "other")],
)
def test_reliability(url, level):
    assert svc.reliability(url) == level


def test_sources_must_be_cited_by_the_search():
    answer = SearchAnswer(
        content=json.dumps({
            "verdict": "factual",
            "reasoning": "DMW confirmed it ([dmw.gov.ph](https://www.dmw.gov.ph/news/seafarers-first-margo)).",
            "sources": [
                {"url": "https://www.dmw.gov.ph/news/seafarers-first-margo/", "quote": "DMW identified 40 seafarers"},
                {"url": "https://made-up.example.com/not-cited", "quote": "invented"},
            ],
        }),
        citations=[Citation(*GOV)],
    )
    check = svc.interpret(answer)
    assert check.status == "SUPPORTED"
    assert [s.url for s in check.sources] == [GOV[0]]  # the uncited URL is dropped
    assert check.sources[0].quote == "DMW identified 40 seafarers"
    assert "](" not in check.reasoning  # inline citation markup removed


def test_weak_sources_cannot_settle_a_claim():
    answer = SearchAnswer(
        content=json.dumps({"verdict": "misleading", "reasoning": "A blog says otherwise.", "sources": [{"url": BLOG[0]}]}),
        citations=[Citation(*BLOG), Citation(*WIKI)],
    )
    check = svc.interpret(answer)
    assert check.status == "NEEDS_CONTEXT" and check.downgraded


def test_verdict_mapping_and_unusable_answers():
    for verdict, status in svc.VERDICT_STATUS.items():
        a = SearchAnswer(json.dumps({"verdict": verdict, "reasoning": "r", "sources": []}), [Citation(*GOV)])
        assert svc.interpret(a).status == status
    assert svc.interpret(SearchAnswer("not json", [])) is None
    assert svc.interpret(SearchAnswer(json.dumps({"verdict": "maybe"}), [])) is None


# --- verification --------------------------------------------------------------------


async def test_web_search_settles_a_claim_no_source_covers(api):
    api.body = completion(
        {"verdict": "factual", "reasoning": "The DMW identified 40 Filipino seafarers aboard the carrier.",
         "sources": [{"url": GOV[0], "quote": "40 Filipino seafarers"}, {"url": NEWS[0], "quote": "all safe"}]},
        [GOV, NEWS],
    )
    res = await verification.verify(
        other("The DMW identified around 40 Filipino seafarers aboard the carrier", checkworthiness=0.9,
              context="The Department of Migrant Workers has identified around 40 Filipino seafarers...")
    )
    assert res.assessment.status == "SUPPORTED"
    assert res.assessment.method == "AI_WEB_SEARCH"
    assert "2 sources, 2 reliable" in res.assessment.explanation
    first = res.evidence[0]
    assert first.source.source_type == "WEB_SEARCH_RESULT" and first.source.reliability == "government"
    assert first.data.relevant_text == "40 Filipino seafarers"
    prompt = json.loads(api.requests[0].content)["messages"][1]["content"]
    assert prompt.startswith("CLAIM: The DMW identified") and "SAID IN (transcript" in prompt


async def test_low_checkworthiness_skips_the_paid_search(api):
    res = await verification.verify(other("Some minor remark about the weather today", checkworthiness=0.2))
    assert res.assessment.status == "NO_SOURCE" and api.requests == []


async def test_no_key_means_no_search(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "factcheck_api_key", None)
    res = await verification.verify(other("A claim nobody covers", checkworthiness=0.9))
    assert res.assessment.status == "NO_SOURCE"


async def test_search_failure_keeps_the_previous_result(api):
    api.status, api.body = 500, {"error": {}}
    res = await verification.verify(other("A claim nobody covers", checkworthiness=0.9))
    assert res.assessment.status == "NO_SOURCE"


async def test_conclusive_data_never_triggers_web_search(api, monkeypatch):
    from src.services import openstat_service

    from .test_claim_verification import openstat_response

    async def fake_check(req):
        return openstat_response("CONTRADICTED")

    monkeypatch.setattr(openstat_service, "check_claim", fake_check)
    await verification.verify(
        VerifyClaimRequest(claim="Unemployment was 5%", claim_type="STATISTICAL", checkworthiness=0.9,
                           entities=ClaimEntities(metric="unemployment rate", value=5))
    )
    assert api.requests == []


async def test_results_are_cached(api):
    api.body = completion({"verdict": "unfounded", "reasoning": "No reports found.", "sources": []}, [])
    await verification.verify(other("The same claim twice", checkworthiness=0.9))
    await verification.verify(other("the same claim twice", checkworthiness=0.9))
    assert len(api.requests) == 1


async def test_published_fact_check_runs_before_web_search(api, monkeypatch):
    called = []

    async def fake_fc(text, result, llm, rate_limiter):
        called.append("factcheck")
        return result

    monkeypatch.setattr(verification, "_with_published_fact_checks", fake_fc)
    api.body = completion({"verdict": "unfounded", "reasoning": "Nothing.", "sources": []}, [])
    res = await verification.verify(other("Order of fallbacks", checkworthiness=0.9))
    assert called == ["factcheck"] and res.assessment.method == "AI_WEB_SEARCH"
    assert res.assessment.status == "INSUFFICIENT_EVIDENCE"


async def test_statistical_claim_without_metric_reaches_web_search(api):
    api.body = completion({"verdict": "factual", "reasoning": "DMW banned deployment to the Black Sea.",
                           "sources": [{"url": GOV[0]}]}, [GOV])
    res = await verification.verify(
        VerifyClaimRequest(claim="The DMW banned deployment of seafarers to the Northern Black Sea",
                           claim_type="STATISTICAL", checkworthiness=0.9, entities=ClaimEntities())
    )
    assert res.assessment.method == "AI_WEB_SEARCH" and res.assessment.status == "SUPPORTED"


async def test_rejected_key_disables_web_search(api, monkeypatch):
    monkeypatch.setattr(svc, "_disabled_reason", None)
    api.status, api.body = 401, {"error": {"message": "Incorrect API key provided"}}
    await verification.verify(other("First claim after a bad key", checkworthiness=0.9))
    await verification.verify(other("Second claim after a bad key", checkworthiness=0.9))
    assert len(api.requests) == 1  # no more calls once the key is rejected
    assert svc.is_configured() is False
