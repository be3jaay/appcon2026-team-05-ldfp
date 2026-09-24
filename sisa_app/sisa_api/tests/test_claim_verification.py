"""Claim verification routing (STATISTICAL -> OpenSTAT, LEGAL -> Official Gazette), offline."""

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from src.clients.official_gazette_client import OfficialGazetteClient
from src.clients.openstat_client import OpenStatClientError
from src.main import app
from src.models.claims import ClaimEntities
from src.models.openstat import (
    ClaimSummary,
    Evidence,
    OpenStatCheckResponse,
    SourceCitation,
)
from src.models.verification import VerifyClaimRequest
from src.services import claim_verification_service as verification
from src.services import official_gazette_service, openstat_service

FIXTURES = Path(__file__).parent / "fixtures" / "official_gazette"
RSS = {"content-type": "application/rss+xml; charset=UTF-8"}


@pytest.fixture
def gazette(monkeypatch):
    feeds = {"executive order no. 124": (FIXTURES / "search_eo_124.xml").read_bytes()}
    empty = (FIXTURES / "search_empty.xml").read_bytes()

    def handler(request):
        return httpx.Response(200, headers=RSS, content=feeds.get(request.url.params["s"].lower(), empty))

    client = OfficialGazetteClient("https://www.officialgazette.gov.ph", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(official_gazette_service, "_client", client)
    monkeypatch.setattr(official_gazette_service, "_cache", official_gazette_service._TTLCache(600))


def legal(claim, **entities):
    return VerifyClaimRequest(claim=claim, claim_type="LEGAL", entities=ClaimEntities(**entities))


def statistical(claim, **entities):
    return VerifyClaimRequest(claim=claim, claim_type="STATISTICAL", entities=ClaimEntities(**entities))


# --- LEGAL ---------------------------------------------------------------------------


async def test_existence_claim_found_is_supported(gazette):
    res = await verification.verify(
        legal("The President issued Executive Order No. 124", document_type="Executive Order", document_number="124")
    )
    assert res.claim.type == "LEGAL_ISSUANCE"
    assert res.assessment.status == "SUPPORTED"
    assert "Executive Order No. 124, s. 2026" in res.assessment.explanation
    assert "More than one year" in res.assessment.explanation
    first = res.evidence[0]
    assert first.relevance == "DIRECT"
    assert first.source.source_type == "OFFICIAL_DOCUMENT"
    assert first.source.url.startswith("https://www.officialgazette.gov.ph/")
    assert first.data.document_reference == "Executive Order No. 124, s. 2026"
    assert "EDUCATION PHILIPPINES" in first.data.relevant_text


async def test_year_narrows_to_one_document(gazette):
    res = await verification.verify(
        legal("EO 124 of 2021", document_type="EO", document_number="124", date="2021")
    )
    assert res.assessment.status == "SUPPORTED"
    assert [e.source.title for e in res.evidence] == ["Executive Order No. 124, s. 2021"]
    assert "More than one year" not in res.assessment.explanation


async def test_content_claim_needs_context_not_supported(gazette):
    res = await verification.verify(
        legal(
            "EO 124 created a new tax",
            document_type="Executive Order",
            document_number="124",
            subject="created a new tax",
        )
    )
    assert res.assessment.status == "NEEDS_CONTEXT"
    assert res.evidence and res.evidence[0].relevance == "DIRECT"


async def test_missing_document_is_never_contradicted(gazette):
    res = await verification.verify(
        legal("Republic Act No. 99999 was signed", document_type="Republic Act", document_number="99999")
    )
    assert res.assessment.status == "INSUFFICIENT_EVIDENCE"
    assert "does not prove it does not exist" in res.assessment.explanation
    assert res.evidence == []  # unrelated hits are not evidence


async def test_gazette_error_is_reported(monkeypatch):
    client = OfficialGazetteClient(
        "https://www.officialgazette.gov.ph", transport=httpx.MockTransport(lambda r: httpx.Response(503))
    )
    monkeypatch.setattr(official_gazette_service, "_client", client)
    monkeypatch.setattr(official_gazette_service, "_cache", official_gazette_service._TTLCache(600))
    res = await verification.verify(legal("EO 5", document_type="Executive Order", document_number="5"))
    assert res.assessment.status == "ERROR"


# --- STATISTICAL ---------------------------------------------------------------------


def openstat_response(status="CONTRADICTED"):
    return OpenStatCheckResponse(
        status=status,
        explanation="differs by 1 percentage points",
        claim=ClaimSummary(text="x", metric="Unemployment Rate", claimed_value=5, unit="percent", period="July 2026", geography="Philippines"),
        source=SourceCitation(
            name="Philippine Statistics Authority",
            dataset="Labor Force Survey (LFS)",
            table="Rates Key Employment Indicators",
            url="https://openstat.psa.gov.ph/table",
            api_url="https://openstat.psa.gov.ph/api",
        ),
        evidence=Evidence(value=6.005, unit="percent", period="July 2026", geography="Philippines"),
    )


async def test_statistical_routes_to_openstat(monkeypatch):
    seen = []

    async def fake_check(req):
        seen.append(req)
        return openstat_response()

    monkeypatch.setattr(openstat_service, "check_claim", fake_check)
    res = await verification.verify(
        statistical(
            "The unemployment rate was 5% in July 2026",
            metric="unemployment",
            value="5%",
            unit="percent",
            date="July 2026",
            geography="Philippines",
        )
    )
    assert seen[0].metric == "unemployment rate"  # alias normalized
    assert (seen[0].value, seen[0].period) == (5.0, "July 2026")
    assert res.claim.type == "STATISTICAL"
    assert res.assessment.status == "CONTRADICTED"
    ev = res.evidence[0]
    assert ev.source.source_type == "OFFICIAL_STATISTICS" and ev.source.name == "PSA OpenSTAT"
    assert (ev.data.value, ev.data.period) == (6.005, "July 2026")


async def test_unsupported_metric_does_not_call_openstat(monkeypatch):
    async def boom(req):
        raise AssertionError("should not be called")

    monkeypatch.setattr(openstat_service, "check_claim", boom)
    res = await verification.verify(statistical("Inflation was 3.9%", metric="inflation rate", value=3.9))
    assert res.assessment.status == "INSUFFICIENT_EVIDENCE"
    assert "unemployment rate only" in res.assessment.explanation


async def test_statistical_without_metric():
    res = await verification.verify(statistical("It went up to 5%", value=5))
    assert res.assessment.status == "NEEDS_CONTEXT"


async def test_openstat_error_is_reported(monkeypatch):
    async def fail(req):
        raise OpenStatClientError(504, "OpenSTAT did not respond in time.")

    monkeypatch.setattr(openstat_service, "check_claim", fail)
    res = await verification.verify(statistical("Unemployment is 5%", metric="unemployment rate", value=5))
    assert res.assessment.status == "ERROR" and "did not respond" in res.assessment.explanation


async def test_other_claims_have_no_source():
    res = await verification.verify(VerifyClaimRequest(claim="Traffic is terrible", claim_type="OTHER"))
    assert res.claim.type == "OTHER" and res.assessment.status == "INSUFFICIENT_EVIDENCE"


# --- route ---------------------------------------------------------------------------


def test_verify_route_accepts_detector_shape(gazette):
    r = TestClient(app).post(
        "/api/v1/claims/verify",
        json={
            "claim": "The President issued Executive Order No. 124",
            "claim_type": "LEGAL",
            "entities": {"document_type": "Executive Order", "document_number": 124, "subject": None, "date": None},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["claim"] == {"text": "The President issued Executive Order No. 124", "type": "LEGAL_ISSUANCE"}
    assert body["assessment"]["status"] == "SUPPORTED"
    assert body["evidence"][0]["source"]["name"] == "Official Gazette of the Republic of the Philippines"


def test_verify_route_rejects_unknown_claim_type():
    r = TestClient(app).post("/api/v1/claims/verify", json={"claim": "abc def", "claim_type": "ASTROLOGY"})
    assert r.status_code == 422
