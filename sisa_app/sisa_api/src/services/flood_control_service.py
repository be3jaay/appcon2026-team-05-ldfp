"""DPWH flood control projects (2018-2025), as compiled by BetterGov.ph.

The file is an ArcGIS feature export from the DPWH flood control map
(`features[].attributes`, one row per contract / project component). It is
downloaded on first use, cached on disk, and kept in memory. Every figure this
service returns is computed from those rows; nothing is estimated.
"""

import asyncio
import json
import logging
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..clients import bettergov_client
from ..clients.bettergov_client import DatasetDownloadError
from ..config import settings
from ..models.flood_control import (
    ContractorTotal,
    FloodControlFilters,
    FloodControlProject,
    FloodControlProjectsResponse,
    FloodControlSource,
    FloodControlSummary,
    YearTotal,
)

logger = logging.getLogger(__name__)

_API_ROOT = Path(__file__).resolve().parents[2]

# Spoken / English names -> the Region values used in the data.
REGION_ALIASES: dict[str, list[str]] = {
    "National Capital Region": ["ncr", "metro manila", "kamaynilaan", "national capital region"],
    "Cordillera Administrative Region": ["car", "cordillera", "cordillera administrative region"],
    "Region I": ["region i", "region 1", "ilocos region", "ilocos"],
    "Region II": ["region ii", "region 2", "cagayan valley"],
    "Region III": ["region iii", "region 3", "central luzon", "gitnang luzon"],
    "Region IV-A": ["region iv-a", "region 4a", "region 4-a", "calabarzon"],
    "Region IV-B": ["region iv-b", "region 4b", "region 4-b", "mimaropa"],
    "Region V": ["region v", "region 5", "bicol", "bicol region"],
    "Region VI": ["region vi", "region 6", "western visayas"],
    "Region VII": ["region vii", "region 7", "central visayas"],
    "Region VIII": ["region viii", "region 8", "eastern visayas"],
    "Region IX": ["region ix", "region 9", "zamboanga peninsula"],
    "Region X": ["region x", "region 10", "northern mindanao"],
    "Region XI": ["region xi", "region 11", "davao region"],
    "Region XII": ["region xii", "region 12", "soccsksargen"],
    "Region XIII": ["region xiii", "region 13", "caraga"],
}
_REGION_BY_ALIAS = {alias: region for region, aliases in REGION_ALIASES.items() for alias in aliases}
_NATIONAL = {"philippines", "the philippines", "ph", "national", "nationwide", "buong bansa", "pilipinas"}


class FloodControlDataError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# --- loading -------------------------------------------------------------------------


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _year(value: Any) -> int | None:
    m = re.search(r"\b(19|20)\d{2}\b", str(value or ""))
    return int(m.group(0)) if m else None


def parse_dataset(raw: bytes) -> list[FloodControlProject]:
    try:
        data = json.loads(raw)
        features = data["features"]
    except (ValueError, KeyError, TypeError) as exc:
        raise FloodControlDataError(502, "The flood control dataset has an unexpected format.") from exc
    if not isinstance(features, list):
        raise FloodControlDataError(502, "The flood control dataset has an unexpected format.")

    projects = []
    for feature in features:
        a = feature.get("attributes") if isinstance(feature, dict) else None
        if not isinstance(a, dict):
            continue
        projects.append(
            FloodControlProject(
                project_id=_text(a.get("ProjectID")),
                contract_id=_text(a.get("ContractID")),
                description=_text(a.get("ProjectDescription")),
                type_of_work=_text(a.get("TypeofWork")),
                region=_text(a.get("Region")),
                province=_text(a.get("Province")),
                municipality=_text(a.get("Municipality")),
                legislative_district=_text(a.get("LegislativeDistrict")),
                district_engineering_office=_text(a.get("DistrictEngineeringOffice")),
                contractor=_text(a.get("Contractor")),
                approved_budget=_number(a.get("ABC")),
                contract_cost=_number(a.get("ContractCost")),
                funding_year=_year(a.get("FundingYear")) or _year(a.get("InfraYear")),
                start_date=_text(a.get("StartDate")),
                completion_date=_text(a.get("CompletionDateActual")),
                latitude=_number(a.get("Latitude")),
                longitude=_number(a.get("Longitude")),
            )
        )
    if not projects:
        raise FloodControlDataError(502, "The flood control dataset contained no projects.")
    return projects


_projects: list[FloodControlProject] | None = None
_loaded_at = 0.0
_lock = asyncio.Lock()


def _cache_path() -> Path:
    path = Path(settings.flood_control_cache_path)
    return path if path.is_absolute() else _API_ROOT / path


async def load_projects() -> list[FloodControlProject]:
    """In memory if fresh; else the disk cache if fresh; else download (falling back to a
    stale disk copy if the download fails)."""
    global _projects, _loaded_at
    max_age = settings.flood_control_max_age_hours * 3600
    if _projects is not None and time.time() - _loaded_at < max_age:
        return _projects
    async with _lock:
        if _projects is not None and time.time() - _loaded_at < max_age:
            return _projects
        path = _cache_path()
        raw: bytes | None = None
        cached_at = path.stat().st_mtime if path.exists() else 0.0
        if path.exists() and time.time() - cached_at < max_age:
            raw = path.read_bytes()
        else:
            try:
                raw = await bettergov_client.download(
                    settings.flood_control_data_url, timeout=settings.flood_control_timeout_seconds
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                cached_at = time.time()
                logger.info("flood control dataset downloaded (%d bytes)", len(raw))
            except DatasetDownloadError as exc:
                if not path.exists():
                    raise FloodControlDataError(exc.status_code, exc.message) from exc
                logger.warning("flood control download failed (%s); using cached copy", exc.message)
                raw = path.read_bytes()
        _projects = parse_dataset(raw)
        _loaded_at = cached_at
        logger.info("flood control dataset loaded: %d records", len(_projects))
        return _projects


# --- filtering -----------------------------------------------------------------------


def _words(text: str | None) -> list[str]:
    return re.sub(r"[^a-z0-9ñ ]+", " ", (text or "").lower()).split()


def _contains(haystack: str | None, needle: str) -> bool:
    """All words of `needle` appear, in order, as whole words of `haystack`."""
    h, n = _words(haystack), _words(needle)
    if not n:
        return False
    for i in range(len(h) - len(n) + 1):
        if h[i : i + len(n)] == n:
            return True
    return False


def resolve_region(text: str) -> str | None:
    key = " ".join(_words(text))
    if key in _REGION_BY_ALIAS:
        return _REGION_BY_ALIAS[key]
    for region in REGION_ALIASES:
        if key == region.lower():
            return region
    return None


# Generic words that don't identify a contractor on their own.
_GENERIC_CONTRACTOR_WORDS = frozenset(
    "construction constructions builders builder corporation corp inc incorporated company co general gen "
    "contractor contractors development developers enterprises enterprise trading supply supplies services "
    "engineering and the of phil philippines formerly jv joint venture".split()
)


def contractor_keywords(projects: list[FloodControlProject]) -> dict[str, str]:
    """Distinctive first word of each contractor name -> that word, e.g. 'sunwest'.
    Only words of 5+ letters that aren't generic company words."""
    place_words = {w for p in projects for field in (p.province, p.municipality, p.region) for w in _words(field)}
    keys: dict[str, str] = {}
    for p in projects:
        words = _words(p.contractor)
        if (
            words
            and len(words[0]) >= 5
            and words[0] not in _GENERIC_CONTRACTOR_WORDS
            and words[0] not in place_words  # firms named "ORIENTAL ...", "BULACAN ..." would match places
        ):
            keys[words[0]] = words[0]
    return keys


def places_in_text(text: str, projects: list[FloodControlProject]) -> str | None:
    """A province (preferred) or region named in the text, as it appears in the data."""
    haystack = " ".join(_words(text))
    provinces = sorted({p.province for p in projects if p.province}, key=len, reverse=True)
    for province in provinces:
        if f" {' '.join(_words(province))} " in f" {haystack} ":
            return province
    for alias, region in sorted(_REGION_BY_ALIAS.items(), key=lambda kv: len(kv[0]), reverse=True):
        if len(alias) > 3 and f" {alias} " in f" {haystack} ":
            return region
    return None


def contractor_in_text(text: str, projects: list[FloodControlProject]) -> str | None:
    words = set(_words(text))
    for key in contractor_keywords(projects):
        if key in words:
            return key
    return None


def filters_for_geography(geography: str | None, projects: list[FloodControlProject]) -> FloodControlFilters | None:
    """Map a place name to filters: {} for national, None if the place isn't in the data.
    Tries region, then province, then municipality/city, then legislative district."""
    if not geography or " ".join(_words(geography)) in _NATIONAL:
        return FloodControlFilters()
    region = resolve_region(geography)
    if region:
        return FloodControlFilters(region=region)
    place = re.sub(r"^(province of|city of|municipality of|lalawigan ng|lungsod ng)\s+", "", geography.strip(), flags=re.I)
    if any((p.province or "").lower() == place.lower() for p in projects):
        return FloodControlFilters(province=place.upper())
    if any(_contains(p.municipality, place) for p in projects):
        return FloodControlFilters(municipality=place)
    if any(_contains(p.legislative_district, place) for p in projects):
        return FloodControlFilters(legislative_district=place)
    return None


def apply_filters(projects: list[FloodControlProject], f: FloodControlFilters) -> list[FloodControlProject]:
    def keep(p: FloodControlProject) -> bool:
        if f.year is not None and p.funding_year != f.year:
            return False
        if f.year_from is not None and (p.funding_year is None or p.funding_year < f.year_from):
            return False
        if f.year_to is not None and (p.funding_year is None or p.funding_year > f.year_to):
            return False
        if f.region and (p.region or "") != (resolve_region(f.region) or f.region):
            return False
        if f.province and (p.province or "").lower() != f.province.lower():
            return False
        if f.municipality and not _contains(p.municipality, f.municipality):
            return False
        if f.legislative_district and not _contains(p.legislative_district, f.legislative_district):
            return False
        if f.contractor and not _contains(p.contractor, f.contractor):
            return False
        if f.type_of_work and not _contains(p.type_of_work, f.type_of_work):
            return False
        return True

    return [p for p in projects if keep(p)]


def _source(projects: list[FloodControlProject]) -> FloodControlSource:
    years = sorted({p.funding_year for p in projects if p.funding_year})
    regions = len({p.region for p in projects if p.region})
    return FloodControlSource(
        data_url=settings.flood_control_data_url,
        coverage=f"Funding years {years[0]}-{years[-1]}, {regions} regions (no BARMM rows)" if years else "unknown",
        records=len(projects),
    )


def summarize(projects: list[FloodControlProject], filters: FloodControlFilters) -> FloodControlSummary:
    matched = apply_filters(projects, filters)
    years: dict[int, list[float]] = defaultdict(lambda: [0, 0.0])
    contractors: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    for p in matched:
        cost = p.contract_cost or 0.0
        if p.funding_year:
            years[p.funding_year][0] += 1
            years[p.funding_year][1] += cost
        if p.contractor:
            contractors[p.contractor][0] += 1
            contractors[p.contractor][1] += cost
    top = sorted(contractors.items(), key=lambda kv: kv[1][1], reverse=True)[:5]
    return FloodControlSummary(
        source=_source(projects),
        filters=filters,
        projects=len(matched),
        total_contract_cost=round(sum(p.contract_cost or 0 for p in matched), 2),
        total_approved_budget=round(sum(p.approved_budget or 0 for p in matched), 2),
        by_year=[YearTotal(year=y, projects=int(v[0]), contract_cost=round(v[1], 2)) for y, v in sorted(years.items())],
        top_contractors=[
            ContractorTotal(contractor=name, projects=int(v[0]), contract_cost=round(v[1], 2)) for name, v in top
        ],
    )


async def get_summary(filters: FloodControlFilters) -> FloodControlSummary:
    return summarize(await load_projects(), filters)


async def list_projects(filters: FloodControlFilters, limit: int = 50) -> FloodControlProjectsResponse:
    projects = await load_projects()
    matched = sorted(apply_filters(projects, filters), key=lambda p: p.contract_cost or 0, reverse=True)
    return FloodControlProjectsResponse(
        source=_source(projects), filters=filters, total=len(matched), projects=matched[:limit]
    )
