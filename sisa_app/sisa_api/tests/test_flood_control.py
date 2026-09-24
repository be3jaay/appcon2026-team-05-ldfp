"""DPWH flood control dataset (via BetterGov.ph), offline.

tests/fixtures/flood_control/sample.json holds 19 real records copied from the
dataset (same ArcGIS export shape), so totals below are computed from them.
"""

import json
import os
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.clients.bettergov_client import DatasetDownloadError
from src.config import settings
from src.main import app
from src.models.claims import ClaimEntities
from src.models.flood_control import FloodControlFilters
from src.models.verification import VerifyClaimRequest
from src.services import claim_verification_service as verification
from src.services import flood_control_service as svc

SAMPLE = Path(__file__).parent / "fixtures" / "flood_control" / "sample.json"
RAW = SAMPLE.read_bytes()
RECORDS = [f["attributes"] for f in json.loads(RAW)["features"]]


def total(pred) -> tuple[int, float]:
    rows = [r for r in RECORDS if pred(r)]
    return len(rows), round(sum(r["ContractCost"] for r in rows), 2)


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    """A fresh on-disk cache holding the sample; downloads fail loudly if attempted."""
    path = tmp_path / "flood_control.json"
    shutil.copy(SAMPLE, path)
    monkeypatch.setattr(settings, "flood_control_cache_path", str(path))
    monkeypatch.setattr(svc, "_projects", None)
    monkeypatch.setattr(svc, "_loaded_at", 0.0)

    async def no_download(*a, **k):
        raise AssertionError("should not download")

    monkeypatch.setattr(svc.bettergov_client, "download", no_download)
    return path


# --- parsing & filters ---------------------------------------------------------------


def test_parse_real_records():
    projects = svc.parse_dataset(RAW)
    assert len(projects) == len(RECORDS)
    p = projects[0]
    assert p.province and p.region and p.contractor and p.contract_cost > 0
    assert p.funding_year in range(2018, 2026)


@pytest.mark.parametrize("raw", [b"not json", b"{}", b'{"features": "x"}', b'{"features": []}'])
def test_parse_rejects_unexpected_format(raw):
    with pytest.raises(svc.FloodControlDataError):
        svc.parse_dataset(raw)


@pytest.mark.parametrize(
    "text, region",
    [("Central Luzon", "Region III"), ("region 3", "Region III"), ("NCR", "National Capital Region"),
     ("Metro Manila", "National Capital Region"), ("CALABARZON", "Region IV-A"), ("Bulacan", None)],
)
def test_resolve_region(text, region):
    assert svc.resolve_region(text) == region


def test_filters_for_geography():
    projects = svc.parse_dataset(RAW)
    assert svc.filters_for_geography("Philippines", projects) == FloodControlFilters()
    assert svc.filters_for_geography(None, projects) == FloodControlFilters()
    assert svc.filters_for_geography("Central Visayas", projects).region == "Region VII"
    assert svc.filters_for_geography("Bulacan", projects).province == "BULACAN"
    assert svc.filters_for_geography("Malolos", projects).municipality == "Malolos"
    assert svc.filters_for_geography("Atlantis", projects) is None


def test_summary_totals_match_the_rows():
    projects = svc.parse_dataset(RAW)
    s = svc.summarize(projects, FloodControlFilters(province="Bulacan", year=2023))
    n, cost = total(lambda r: r["Province"] == "BULACAN" and r["FundingYear"] == "2023")
    assert (s.projects, s.total_contract_cost) == (n, cost)
    assert sum(y.projects for y in s.by_year) == n
    assert s.top_contractors and s.top_contractors[0].contract_cost >= s.top_contractors[-1].contract_cost


def test_contractor_filter_is_word_based():
    projects = svc.parse_dataset(RAW)
    n, _ = total(lambda r: "LEGACY CONSTRUCTION" in r["Contractor"])
    assert svc.summarize(projects, FloodControlFilters(contractor="legacy construction")).projects == n
    assert svc.summarize(projects, FloodControlFilters(contractor="legacy const")).projects == 0


# --- loading -------------------------------------------------------------------------


async def test_loads_from_fresh_disk_cache_without_downloading(dataset):
    assert len(await svc.load_projects()) == len(RECORDS)


async def test_downloads_when_cache_missing(tmp_path, monkeypatch):
    path = tmp_path / "sub" / "fc.json"
    monkeypatch.setattr(settings, "flood_control_cache_path", str(path))
    monkeypatch.setattr(svc, "_projects", None)
    calls = []

    async def fake_download(url, timeout):
        calls.append(url)
        return RAW

    monkeypatch.setattr(svc.bettergov_client, "download", fake_download)
    assert len(await svc.load_projects()) == len(RECORDS)
    assert path.exists() and calls == [settings.flood_control_data_url]


async def test_stale_cache_is_used_when_download_fails(dataset, monkeypatch):
    old = time.time() - (settings.flood_control_max_age_hours + 1) * 3600
    os.utime(dataset, (old, old))

    async def failing(*a, **k):
        raise DatasetDownloadError(502, "offline")

    monkeypatch.setattr(svc.bettergov_client, "download", failing)
    assert len(await svc.load_projects()) == len(RECORDS)


async def test_no_cache_and_no_download_is_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "flood_control_cache_path", str(tmp_path / "missing.json"))
    monkeypatch.setattr(svc, "_projects", None)

    async def failing(*a, **k):
        raise DatasetDownloadError(504, "Downloading the flood control dataset timed out.")

    monkeypatch.setattr(svc.bettergov_client, "download", failing)
    with pytest.raises(svc.FloodControlDataError) as exc:
        await svc.load_projects()
    assert exc.value.status_code == 504


# --- routes --------------------------------------------------------------------------


def test_summary_route(dataset):
    r = TestClient(app).get("/api/v1/flood-control/summary", params={"province": "Bulacan"})
    assert r.status_code == 200
    body = r.json()
    n, cost = total(lambda r: r["Province"] == "BULACAN")
    assert (body["projects"], body["total_contract_cost"]) == (n, cost)
    assert body["source"]["source_type"] == "GOVERNMENT_DATASET"
    assert "BetterGov.ph" in body["source"]["publisher"]


def test_projects_route_sorted_by_cost(dataset):
    r = TestClient(app).get("/api/v1/flood-control/projects", params={"region": "NCR", "limit": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == total(lambda r: r["Region"] == "National Capital Region")[0]
    costs = [p["contract_cost"] for p in body["projects"]]
    assert len(costs) == 2 and costs == sorted(costs, reverse=True)


# --- claim verification --------------------------------------------------------------


def stat(claim, **entities):
    return VerifyClaimRequest(claim=claim, claim_type="STATISTICAL", entities=ClaimEntities(**entities))


async def test_matching_amount_is_supported(dataset):
    n, cost = total(lambda r: r["Province"] == "BULACAN")
    res = await verification.verify(
        stat("Bulacan flood control", metric="flood control project cost", value=cost * 1.02, unit="pesos", geography="Bulacan")
    )
    assert res.assessment.status == "SUPPORTED" and res.assessment.method == "OFFICIAL_DATA"
    ev = res.evidence[0]
    assert ev.source.source_type == "GOVERNMENT_DATASET" and ev.data.value == cost and ev.data.unit == "pesos"


async def test_spoken_scale_words_are_applied(dataset):
    _, cost = total(lambda r: True)
    billions = round(cost / 1e9, 1)
    res = await verification.verify(
        stat(f"₱{billions} billion on flood control", metric="flood control spending", value=billions, unit="billion pesos")
    )
    assert res.assessment.status == "SUPPORTED"


async def test_inflated_amount_is_contradicted(dataset):
    _, cost = total(lambda r: r["Province"] == "BULACAN")
    res = await verification.verify(
        stat("A flood control claim", metric="flood control budget", value=cost * 6, unit="pesos", geography="Bulacan")
    )
    assert res.assessment.status == "CONTRADICTED"
    assert "6.0× the recorded figure" in res.assessment.explanation


async def test_roughly_right_needs_context(dataset):
    _, cost = total(lambda r: r["Province"] == "BULACAN")
    res = await verification.verify(stat("A flood control claim", metric="flood control cost", value=cost * 0.85, unit="pesos", geography="Bulacan"))
    assert res.assessment.status == "NEEDS_CONTEXT"


async def test_project_count_with_contractor(dataset):
    n, _ = total(lambda r: "LEGACY CONSTRUCTION" in r["Contractor"])
    res = await verification.verify(
        stat("A flood control claim", metric="number of flood control projects", value=n, unit="projects", contractor="Legacy Construction")
    )
    assert res.assessment.status == "SUPPORTED"
    assert f"{n} project record" in res.assessment.explanation


async def test_unknown_place_is_insufficient_not_contradicted(dataset):
    res = await verification.verify(stat("A flood control claim", metric="flood control projects", value=5, geography="Atlantis"))
    assert res.assessment.status == "INSUFFICIENT_EVIDENCE"


async def test_no_matching_rows_is_insufficient(dataset):
    res = await verification.verify(stat("A flood control claim", metric="flood control cost", value=1e9, unit="pesos", date="2011"))
    assert res.assessment.status == "INSUFFICIENT_EVIDENCE"


async def test_claim_without_number_shows_the_record(dataset):
    res = await verification.verify(stat("Marami ang flood control sa Malolos", metric="flood control projects", geography="Malolos"))
    assert res.assessment.status == "NEEDS_CONTEXT" and res.evidence


async def test_non_flood_statistics_still_go_to_openstat(dataset, monkeypatch):
    from src.clients.openstat_client import OpenStatClientError
    from src.services import openstat_service

    called = []

    async def fake_check(req):
        called.append(req)
        raise OpenStatClientError(504, "OpenSTAT did not respond in time.")

    monkeypatch.setattr(openstat_service, "check_claim", fake_check)
    res = await verification.verify(stat("Unemployment is 5%", metric="unemployment rate", value=5))
    assert called and res.assessment.status == "ERROR"  # routed to OpenSTAT, not the flood data


async def test_year_range_covers_every_year_in_it(dataset):
    _, cost = total(lambda r: True)
    years = sorted({int(r["FundingYear"]) for r in RECORDS})
    res = await verification.verify(
        stat(
            "Flood control spending from start to end",
            metric="flood control spending",
            value=cost,
            unit="pesos",
            date=f"mula {years[0]} hanggang {years[-1]}",
        )
    )
    assert res.assessment.status == "SUPPORTED"
    assert f"funded {years[0]}–{years[-1]}" in res.assessment.explanation


def test_year_range_filter():
    projects = svc.parse_dataset(RAW)
    n, _ = total(lambda r: 2023 <= int(r["FundingYear"]) <= 2024)
    assert svc.summarize(projects, FloodControlFilters(year_from=2023, year_to=2024)).projects == n
