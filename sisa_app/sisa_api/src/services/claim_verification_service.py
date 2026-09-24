"""Route a detected claim to the official source that can check it.

STATISTICAL -> DPWH flood control project records (flood control claims), else
               PSA OpenSTAT (existing openstat_service, unchanged)
LEGAL       -> Official Gazette search
OTHER       -> no automated source yet

Assessments are conservative: a document that is not found in a search is
never reported as CONTRADICTED, and a found document only SUPPORTS claims
about its existence/issuance, not claims about its content.
"""

import logging
import re

from ..clients.official_gazette_client import OfficialGazetteClientError
from ..clients.openstat_client import OpenStatClientError
from ..models.claims import ClaimEntities
from ..models.official_gazette import OFFICIAL_GAZETTE_NAME, OFFICIAL_GAZETTE_PUBLISHER, OfficialGazetteResult
from ..models.openstat import OpenStatCheckResponse, OpenStatClaimRequest
from ..models.verification import (
    Assessment,
    EvidenceData,
    EvidenceItem,
    EvidenceSource,
    VerificationResponse,
    VerifiedClaim,
    VerifyClaimRequest,
)
from ..models.flood_control import FLOOD_CONTROL_PAGE_URL, FLOOD_CONTROL_PUBLISHER, FLOOD_CONTROL_SOURCE_NAME
from . import evidence_judge, flood_control_service, official_gazette_service, openstat_service
from .claims.classifier import LLMClient
from .claims.rate_limiter import RateLimiter
from .openstat_parser import OpenStatParseError

logger = logging.getLogger(__name__)

# Spoken/LLM metric names -> the names openstat_service supports.
_METRIC_ALIASES = {
    "unemployment rate": "unemployment rate",
    "unemployment": "unemployment rate",
    "jobless rate": "unemployment rate",
    "antas ng kawalan ng trabaho": "unemployment rate",
}
_MAX_EVIDENCE = 3


async def verify(
    req: VerifyClaimRequest, llm: LLMClient | None = None, rate_limiter: RateLimiter | None = None
) -> VerificationResponse:
    """`llm` is optional: without it, content claims about a found document stay NEEDS_CONTEXT."""
    if req.claim_type == "STATISTICAL":
        return await _verify_statistical(req.claim, req.entities)
    if req.claim_type == "LEGAL":
        return await _verify_legal(req.claim, req.entities, llm, rate_limiter)
    return VerificationResponse(
        claim=VerifiedClaim(text=req.claim, type="OTHER"),
        assessment=Assessment(
            status="INSUFFICIENT_EVIDENCE",
            explanation="No official source is connected for this kind of claim yet.",
        ),
    )


# --- STATISTICAL -> OpenSTAT ------------------------------------------------------


async def _verify_statistical(text: str, entities: ClaimEntities) -> VerificationResponse:
    claim = VerifiedClaim(text=text, type="STATISTICAL")

    def result(status, explanation, evidence=()):
        return VerificationResponse(
            claim=claim, assessment=Assessment(status=status, explanation=explanation), evidence=list(evidence)
        )

    if _is_flood_control(text, entities):
        return await _verify_flood_control(text, entities)
    if not entities.metric:
        return result("NEEDS_CONTEXT", "The claim does not name which statistic it is about.")
    metric = _METRIC_ALIASES.get(entities.metric.strip().lower(), entities.metric)
    try:
        openstat_service.resolve_dataset(metric)
    except openstat_service.UnsupportedMetricError:
        return result(
            "INSUFFICIENT_EVIDENCE",
            f"'{entities.metric}' is not connected yet. PSA OpenSTAT checks currently support the "
            "unemployment rate only.",
        )

    try:
        checked = await openstat_service.check_claim(
            OpenStatClaimRequest(
                claim=text,
                metric=metric,
                value=entities.value,
                unit=entities.unit,
                period=entities.date,
                geography=entities.geography,
            )
        )
    except OpenStatClientError as exc:
        return result("ERROR", exc.message)
    except OpenStatParseError:
        logger.warning("OpenSTAT response could not be interpreted for claim %r", text)
        return result("ERROR", "OpenSTAT returned data in an unexpected structure.")

    response = result(checked.status, checked.explanation or checked.message or "", _openstat_evidence(checked))
    if checked.evidence is not None:
        response.assessment.method = "OFFICIAL_DATA"
    return response


def _openstat_evidence(checked: OpenStatCheckResponse) -> list[EvidenceItem]:
    if checked.source is None or checked.evidence is None:
        return []
    return [
        EvidenceItem(
            source=EvidenceSource(
                name="PSA OpenSTAT",
                publisher=checked.source.name,
                source_type="OFFICIAL_STATISTICS",
                url=checked.source.url,
                title=checked.source.table,
                dataset=checked.source.dataset,
                table=checked.source.table,
            ),
            data=EvidenceData(
                value=checked.evidence.value,
                unit=checked.evidence.unit,
                period=checked.evidence.period,
                geography=checked.evidence.geography,
                relevant_text=checked.evidence.note,
            ),
            relevance="DIRECT",
        )
    ]


# --- STATISTICAL (flood control) -> DPWH flood control projects ---------------------

_FLOOD_RE = re.compile(r"flood|baha|dike|revetment|drainage|slope protection", re.I)
_AMOUNT_RE = re.compile(r"peso|php|₱|piso|cost|budget|spen[dt]|fund|pondo|amount|halaga|gastos|ginastos|contract value", re.I)
_COUNT_RE = re.compile(r"number|count|bilang|ilan|projects?\b|proyekto|contracts?\b", re.I)
_SCALE = [
    (re.compile(r"trillion|trilyon", re.I), 1e12),
    (re.compile(r"billion|bilyon|\bb\b|\bbn\b", re.I), 1e9),
    (re.compile(r"million|milyon|\bm\b|\bmn\b", re.I), 1e6),
    (re.compile(r"thousand|libo|\bk\b", re.I), 1e3),
]
# Spoken figures are rounded: within 5% supports the claim, beyond 25% contradicts it.
_CLOSE, _FAR = 0.05, 0.25


def _is_flood_control(text: str, entities: ClaimEntities) -> bool:
    return bool(_FLOOD_RE.search(entities.metric or "") or re.search(r"flood control|baha", text, re.I))


def _claimed_amount(value: float, unit: str | None, text: str) -> float:
    """'₱125 milyon' may arrive as value=125 + unit 'million pesos'; scale small values only."""
    if value >= 1e5:
        return value
    for pattern, factor in _SCALE:
        if pattern.search(unit or ""):
            return value * factor
    for pattern, factor in _SCALE:  # e.g. unit "pesos" but the claim says "547 billion"
        if re.search(rf"{re.escape(format(value, 'g'))}\s*({pattern.pattern})", text, re.I):
            return value * factor
    return value


def _peso(amount: float) -> str:
    for size, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(amount) >= size:
            return f"₱{amount / size:,.2f}{suffix}"
    return f"₱{amount:,.0f}"


def _scope(filters) -> str:
    parts = []
    if filters.contractor:
        parts.append(f"by contractors matching '{filters.contractor}'")
    place = filters.municipality or filters.legislative_district or filters.province or filters.region
    parts.append(f"in {place}" if place else "nationwide")
    if filters.year:
        parts.append(f"funded in {filters.year}")
    elif filters.year_from or filters.year_to:
        parts.append(f"funded {filters.year_from or '…'}–{filters.year_to or '…'}")
    return " ".join(parts)


def _years(date: str | None) -> dict:
    """'2023' -> year; '2018-2025' / 'mula 2018 hanggang 2025' -> an inclusive range."""
    years = sorted({int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", date or "")})
    if not years:
        return {}
    if len(years) == 1:
        return {"year": years[0]}
    return {"year_from": years[0], "year_to": years[-1]}


async def _verify_flood_control(text: str, entities: ClaimEntities) -> VerificationResponse:
    claim = VerifiedClaim(text=text, type="STATISTICAL")

    def result(status, explanation, evidence=(), method="NONE"):
        return VerificationResponse(
            claim=claim,
            assessment=Assessment(status=status, explanation=explanation, method=method),
            evidence=list(evidence),
        )

    try:
        projects = await flood_control_service.load_projects()
    except flood_control_service.FloodControlDataError as exc:
        return result("ERROR", exc.message)

    filters = flood_control_service.filters_for_geography(entities.geography, projects)
    if filters is None:
        return result(
            "INSUFFICIENT_EVIDENCE",
            f"'{entities.geography}' does not appear in the DPWH flood control project records "
            "(2018-2025; BARMM is not included).",
        )
    filters = filters.model_copy(update={**_years(entities.date), "contractor": entities.contractor})
    summary = flood_control_service.summarize(projects, filters)
    scope = _scope(filters)
    if summary.projects == 0:
        return result(
            "INSUFFICIENT_EVIDENCE",
            f"No flood control project records were found {scope}. The records cover DPWH projects "
            "funded 2018-2025 and may not list every project.",
        )

    is_amount = bool(_AMOUNT_RE.search(f"{entities.unit or ''} {entities.metric or ''}")) or (
        not _COUNT_RE.search(f"{entities.unit or ''} {entities.metric or ''}") and (entities.value or 0) >= 1e5
    )
    actual = summary.total_contract_cost if is_amount else float(summary.projects)
    records = f"{summary.projects:,} project record{'s' if summary.projects != 1 else ''}"
    shown = _peso(actual) if is_amount else records
    top = "; ".join(f"{c.contractor} ({c.projects}, {_peso(c.contract_cost)})" for c in summary.top_contractors[:3])
    evidence = EvidenceItem(
        source=EvidenceSource(
            name=FLOOD_CONTROL_SOURCE_NAME,
            publisher=FLOOD_CONTROL_PUBLISHER,
            source_type="GOVERNMENT_DATASET",
            url=FLOOD_CONTROL_PAGE_URL,
            title=f"Flood control projects {scope}",
            dataset="DPWH flood control project map (2018-2025)",
        ),
        data=EvidenceData(
            value=actual,
            unit="pesos" if is_amount else "projects",
            period=str(filters.year) if filters.year else f"{filters.year_from or 2018}-{filters.year_to or 2025}",
            geography=scope,
            relevant_text=(
                f"{records} {scope}; total contract cost "
                f"{_peso(summary.total_contract_cost)} (approved budget {_peso(summary.total_approved_budget)}). "
                f"Largest contractors: {top}."
            ),
        ),
        relevance="DIRECT",
    )

    if entities.value is None:
        return result(
            "NEEDS_CONTEXT",
            f"The claim gives no figure to compare. DPWH records show {shown} {scope}.",
            [evidence],
            "OFFICIAL_DATA",
        )

    claimed = _claimed_amount(entities.value, entities.unit, text) if is_amount else entities.value
    claimed_shown = _peso(claimed) if is_amount else f"{claimed:,.0f}"
    gap = abs(claimed - actual) / actual if actual else float("inf")
    if gap <= _CLOSE:
        status, verdict = "SUPPORTED", "which matches"
    elif gap <= _FAR:
        status, verdict = "NEEDS_CONTEXT", f"which is roughly in line but off by {gap:.0%}"
    elif claimed > actual:
        status, verdict = "CONTRADICTED", f"so the claim is about {claimed / actual:.1f}× the recorded figure"
    else:
        status, verdict = "CONTRADICTED", f"so the claim is {gap:.0%} below the recorded figure"
    note = " Totals are contract costs of projects listed in the DPWH flood control map." if is_amount else ""
    return result(
        status,
        f"The claim says {claimed_shown}; DPWH flood control records show {shown} {scope}, {verdict}.{note}",
        [evidence],
        "OFFICIAL_DATA",
    )


# --- LEGAL -> Official Gazette ---------------------------------------------------


def _legal_query(text: str, entities: ClaimEntities) -> str:
    if entities.document_type and entities.document_number:
        ref = official_gazette_service.parse_reference(f"{entities.document_type} No. {entities.document_number}")
        if ref:
            year = re.search(r"\b(?:19|20)\d{2}\b", entities.date or "")
            return ref.canonical + (f", s. {year.group(0)}" if year else "")
    return text


def _gazette_evidence(result: OfficialGazetteResult) -> EvidenceItem:
    reference = None
    if result.document_type and result.document_number:
        reference = f"{result.document_type} No. {result.document_number}"
        if result.series_year:
            reference += f", s. {result.series_year}"
    return EvidenceItem(
        source=EvidenceSource(
            name=OFFICIAL_GAZETTE_NAME,
            publisher=OFFICIAL_GAZETTE_PUBLISHER,
            source_type="OFFICIAL_DOCUMENT",
            url=result.url,
            title=result.title,
            date=result.date,
            document_type=result.document_type,
            document_number=result.document_number,
        ),
        data=EvidenceData(relevant_text=result.snippet, document_reference=reference),
        relevance=result.relevance,
    )


async def _verify_legal(
    text: str, entities: ClaimEntities, llm: LLMClient | None, rate_limiter: RateLimiter | None
) -> VerificationResponse:
    claim = VerifiedClaim(text=text, type="LEGAL_ISSUANCE")
    query = _legal_query(text, entities)
    try:
        found = await official_gazette_service.search(query, limit=10)
    except OfficialGazetteClientError as exc:
        return VerificationResponse(claim=claim, assessment=Assessment(status="ERROR", explanation=exc.message))

    direct = [r for r in found.results if r.relevance == "DIRECT"]
    wanted = official_gazette_service.parse_reference(query)
    # When a specific document was named, unrelated search hits are not evidence.
    shown = direct if (direct or wanted) else found.results
    evidence = [_gazette_evidence(r) for r in shown[:_MAX_EVIDENCE]]

    method = "DOCUMENT_MATCH" if wanted else "NONE"
    if direct and not entities.subject:
        titles = "; ".join(f"{r.title} (published {r.date})" if r.date else r.title for r in direct[:_MAX_EVIDENCE])
        explanation = f"A matching document was found in the Official Gazette: {titles}."
        if len({r.series_year for r in direct}) > 1 and not (wanted and wanted.year):
            explanation += " More than one year uses this number; the claim does not say which."
        status = "SUPPORTED"
    elif direct:
        status = "NEEDS_CONTEXT"
        explanation = (
            f"{direct[0].title} was found in the Official Gazette. Compare its text with what the "
            f"claim says it does ({entities.subject})."
        )
        judgement = None
        if llm is not None:
            judgement = await evidence_judge.judge(
                text,
                [evidence_judge.DocumentText(r.title, r.snippet) for r in direct[:_MAX_EVIDENCE]],
                llm,
                rate_limiter,
            )
        if judgement is not None:
            status, explanation, method = judgement.verdict, judgement.explanation, "AI_COMPARISON"
    elif wanted:
        status = "INSUFFICIENT_EVIDENCE"
        explanation = (
            f"No document titled {wanted.canonical}"
            f"{f', s. {wanted.year}' if wanted.year else ''} was found in the Official Gazette search. "
            "This does not prove it does not exist."
        )
    elif found.results:
        status = "NEEDS_CONTEXT"
        explanation = "The claim does not name a specific document; related Official Gazette documents are listed."
    else:
        status = "INSUFFICIENT_EVIDENCE"
        explanation = "No related documents were found in the Official Gazette search."

    return VerificationResponse(
        claim=claim, assessment=Assessment(status=status, explanation=explanation, method=method), evidence=evidence
    )
