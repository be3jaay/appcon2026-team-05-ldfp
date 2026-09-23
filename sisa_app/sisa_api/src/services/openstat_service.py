import calendar
import re
from dataclasses import dataclass, field
from typing import Any

from ..clients.openstat_client import OpenStatClient
from ..config import settings
from ..models.openstat import (
    ClaimSummary,
    Evidence,
    OpenStatCheckResponse,
    OpenStatClaimRequest,
    OpenStatObservation,
    SourceCitation,
)
from . import verification_service
from .openstat_parser import (
    DataRow,
    OpenStatParseError,
    TableMetadata,
    parse_data,
    parse_metadata,
)


class UnsupportedMetricError(ValueError):
    pass


@dataclass(frozen=True)
class OpenStatDataset:
    metric: str
    api_url: str
    page_url: str
    source_name: str
    dataset_name: str
    unit: str
    geography: str
    year_dimension: str
    month_dimension: str
    annual_label: str
    # Non-time dimensions pinned to one value, given as labels. Codes are looked up
    # in the live metadata on every request because PXWeb codes are table-specific.
    fixed_selections: dict[str, str] = field(default_factory=dict)


UNEMPLOYMENT_DATASET = OpenStatDataset(
    metric="Unemployment Rate",
    api_url=settings.openstat_unemployment_url,
    page_url=settings.openstat_unemployment_page_url,
    source_name="Philippine Statistics Authority",
    dataset_name="Labor Force Survey (LFS)",
    unit="percent",
    # This table only publishes national figures; it has no geography dimension.
    geography="Philippines",
    # Year: resolved from the claim's period.
    year_dimension="Year",
    # Month: a specific month if the claim names one; otherwise all months plus "Annual",
    # so we can prefer the annual figure and fall back to the latest published month.
    month_dimension="Month",
    annual_label="Annual",
    fixed_selections={
        # The table mixes four rates (LFPR, employment, unemployment, underemployment).
        "Rates": "Unemployment Rate",
        # The headline national rate is the total for both sexes, not the male/female split.
        "Sex": "Both sexes",
    },
)

_NATIONAL_ALIASES = {"philippines", "the philippines", "ph", "phl", "national", "nationwide"}
_PERCENT_ALIASES = {"percent", "percentage", "%", "pct", "percent (%)"}


def resolve_dataset(metric: str) -> OpenStatDataset:
    if metric.strip().lower() == "unemployment rate":
        return UNEMPLOYMENT_DATASET
    raise UnsupportedMetricError("Metric is not currently supported by the OpenSTAT MVP.")


async def check_claim(req: OpenStatClaimRequest) -> OpenStatCheckResponse:
    dataset = resolve_dataset(req.metric)
    claim = ClaimSummary(
        text=req.claim,
        metric=req.metric,
        claimed_value=req.value,
        unit=req.unit,
        period=req.period,
        geography=req.geography,
    )

    if req.geography and req.geography.strip().lower() not in _NATIONAL_ALIASES:
        return OpenStatCheckResponse(
            status="INSUFFICIENT_EVIDENCE",
            message="The requested claim could not be matched to available OpenSTAT data.",
            explanation=(
                f"The selected OpenSTAT table only publishes national figures for the "
                f"{dataset.geography}, not for '{req.geography}'."
            ),
            claim=claim,
        )

    year_label, month_label = None, None
    if req.period:
        parsed = _parse_period(req.period)
        if parsed is None:
            return _period_error(
                req.period,
                claim,
                "The requested period could not be interpreted. "
                "Use a format like '2026', 'July 2026' or '2026-07'.",
            )
        year_label, month_label = parsed

    client = OpenStatClient(dataset.api_url, timeout=settings.openstat_timeout_seconds)
    metadata = parse_metadata(await client.get_metadata())

    year_var = metadata.variable(dataset.year_dimension)
    month_var = metadata.variable(dataset.month_dimension)

    if year_label is not None:
        year_code = year_var.code_for(year_label)
        if year_code is None:
            return _period_error(
                req.period, claim, "The requested period was not found in the OpenSTAT dataset."
            )
        year_codes = [year_code]
    else:
        year_codes = year_var.values[-2:]

    if month_label is not None:
        month_code = month_var.code_for(month_label)
        if month_code is None:
            return _period_error(
                req.period, claim, "The requested period was not found in the OpenSTAT dataset."
            )
        month_codes = [month_code]
    else:
        month_codes = list(month_var.values)

    selections = {year_var.code: year_codes, month_var.code: month_codes}
    selections.update(_resolve_fixed_selections(metadata, dataset))
    payload = _build_query(metadata, selections)

    rows = parse_data(await client.query(payload))
    selected = _select_observation(rows, metadata, dataset, year_codes, month_label, req.period)

    source = SourceCitation(
        name=dataset.source_name,
        dataset=dataset.dataset_name,
        table=metadata.title,
        url=dataset.page_url,
        api_url=dataset.api_url,
    )

    if selected is None:
        return OpenStatCheckResponse(
            status="INSUFFICIENT_EVIDENCE",
            message="The requested claim could not be matched to available OpenSTAT data.",
            explanation=(
                f"OpenSTAT has not published {dataset.metric.lower()} data"
                f"{f' for {req.period}' if req.period else ''} yet."
            ),
            requested_period=req.period,
            claim=claim,
            source=source,
        )

    observation, note = selected
    evidence = Evidence(
        value=observation.value,
        unit=observation.unit,
        period=observation.period,
        geography=observation.geography,
        note=note,
    )

    if req.value is None:
        return OpenStatCheckResponse(
            status="NEEDS_CONTEXT",
            explanation="The claim has no numerical value to compare against the official figure.",
            claim=claim,
            source=source,
            evidence=evidence,
        )

    if req.unit and req.unit.strip().lower() not in _PERCENT_ALIASES:
        return OpenStatCheckResponse(
            status="NEEDS_CONTEXT",
            explanation=(
                f"The claim is expressed in '{req.unit}', but the official figure is a "
                f"{dataset.unit} value, so the two cannot be compared directly."
            ),
            claim=claim,
            source=source,
            evidence=evidence,
        )

    status, explanation = verification_service.compare(req.value, observation)
    return OpenStatCheckResponse(
        status=status,
        explanation=explanation,
        claim=claim,
        source=source,
        evidence=evidence,
    )


def _parse_period(period: str) -> tuple[str, str | None] | None:
    text = period.strip()
    if re.fullmatch(r"\d{4}", text):
        return text, None

    if m := re.fullmatch(r"(\d{4})-(\d{1,2})", text):
        month = int(m.group(2))
        return (m.group(1), calendar.month_name[month]) if 1 <= month <= 12 else None

    if m := re.fullmatch(r"([A-Za-z]+)\.?\s+(\d{4})", text):
        word = m.group(1).casefold()
        for i in range(1, 13):
            if word in (calendar.month_name[i].casefold(), calendar.month_abbr[i].casefold()):
                return m.group(2), calendar.month_name[i]
    return None


def _resolve_fixed_selections(metadata: TableMetadata, dataset: OpenStatDataset) -> dict[str, list[str]]:
    resolved = {}
    for dim, label in dataset.fixed_selections.items():
        var = metadata.variable(dim)
        code = var.code_for(label)
        if code is None:
            raise OpenStatParseError(f"OpenSTAT dimension '{dim}' has no value '{label}'.")
        resolved[var.code] = [code]
    return resolved


def _build_query(metadata: TableMetadata, selections: dict[str, list[str]]) -> dict[str, Any]:
    missing = [v.code for v in metadata.variables if v.code not in selections]
    if missing:
        raise OpenStatParseError(f"OpenSTAT table has unhandled dimensions: {missing}.")

    return {
        "query": [
            {"code": code, "selection": {"filter": "item", "values": values}}
            for code, values in selections.items()
        ],
        "response": {"format": "json"},
    }


def _select_observation(
    rows: list[DataRow],
    metadata: TableMetadata,
    dataset: OpenStatDataset,
    year_codes: list[str],
    month_label: str | None,
    requested_period: str | None,
) -> tuple[OpenStatObservation, str | None] | None:
    year_var = metadata.variable(dataset.year_dimension)
    month_var = metadata.variable(dataset.month_dimension)
    annual_code = month_var.code_for(dataset.annual_label)
    values = {
        (row.key[year_var.code], row.key[month_var.code]): row.value
        for row in rows
        if row.value is not None
    }

    def observation(year_code: str, month_code: str) -> OpenStatObservation:
        month = month_var.label_for(month_code)
        year = year_var.label_for(year_code)
        period = f"{year} ({month.lower()})" if month_code == annual_code else f"{month} {year}"
        return OpenStatObservation(
            metric=dataset.metric,
            value=values[(year_code, month_code)],
            unit=dataset.unit,
            period=period,
            geography=dataset.geography,
        )

    def latest_month(year_code: str) -> str | None:
        for month_code in reversed(month_var.values):
            if month_code != annual_code and (year_code, month_code) in values:
                return month_code
        return None

    if month_label is not None:
        key = (year_codes[0], month_var.code_for(month_label))
        return (observation(*key), None) if key in values else None

    if requested_period is not None:
        year_code = year_codes[0]
        if annual_code is not None and (year_code, annual_code) in values:
            return observation(year_code, annual_code), None
        month_code = latest_month(year_code)
        if month_code is None:
            return None
        obs = observation(year_code, month_code)
        return obs, (
            f"No annual figure has been published for {year_var.label_for(year_code)} yet; "
            f"using the latest available month ({obs.period})."
        )

    # No period at all: the most recent published month.
    for year_code in reversed(year_codes):
        month_code = latest_month(year_code)
        if month_code is not None:
            obs = observation(year_code, month_code)
            return obs, f"The claim has no period; using the latest available figure ({obs.period})."
    return None


def _period_error(period: str | None, claim: ClaimSummary, message: str) -> OpenStatCheckResponse:
    return OpenStatCheckResponse(status="ERROR", message=message, requested_period=period, claim=claim)
