"""Route a detected claim to the official source that can check it.

STATISTICAL -> DPWH flood control project records (flood control claims), else
               PSA OpenSTAT (existing openstat_service, unchanged)
LEGAL       -> Official Gazette search
OTHER       -> no data source; like any claim our data cannot settle, it falls back to
               published fact-checks (Google Fact Check Tools) when FACTCHECK_API_KEY is set,
               then, last, to AI web search (OpenAI search model) when OPENAI_API_KEY is set

Assessments are conservative: a document that is not found in a search is
never reported as CONTRADICTED, and a found document only SUPPORTS claims
about its existence/issuance, not claims about its content.
"""

import logging
import re
from urllib.parse import urlsplit

from ..clients.official_gazette_client import OfficialGazetteClientError
from ..config import settings
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
from ..clients.factcheck_client import FactCheckClientError
from ..models.factcheck import PublishedFactCheck
from . import (
    evidence_judge,
    factcheck_service,
    flood_control_service,
    official_gazette_service,
    openstat_service,
    web_search_service,
)
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


_CONNECTED = (
    "Connected sources cover the unemployment rate (PSA), DPWH flood control projects, "
    "and laws and executive issuances (Official Gazette)."
)


def _no_source(topic: str | None = None) -> str:
    about = f"'{topic}'" if topic else "this kind of claim"
    return f"SISA has no data source for {about} yet, so it was not checked. {_CONNECTED}"


async def verify(
    req: VerifyClaimRequest, llm: LLMClient | None = None, rate_limiter: RateLimiter | None = None
) -> VerificationResponse:
    """`llm` is optional: without it, content claims about a found document stay NEEDS_CONTEXT
    and published fact-checks are only listed as related, never used as the verdict."""
    if req.claim_type == "STATISTICAL":
        result = await _verify_statistical(req.claim, req.entities, req.context)
    elif req.claim_type == "LEGAL":
        result = await _verify_legal(req.claim, req.entities, llm, rate_limiter)
    else:
        result = VerificationResponse(
            claim=VerifiedClaim(text=req.claim, type="OTHER"),
            assessment=Assessment(status="NO_SOURCE", explanation=_no_source()),
        )
    if result.assessment.status in ("NO_SOURCE", "INSUFFICIENT_EVIDENCE"):
        result = await _with_published_fact_checks(req.search_text or req.claim, result, llm, rate_limiter)
    if result.assessment.status in ("NO_SOURCE", "INSUFFICIENT_EVIDENCE") and _web_search_allowed(req):
        result = await _with_web_search(req, result)
    return result


# --- AI web search (last resort) ----------------------------------------------------

_RELIABILITY_LABEL = {
    "government": "government source",
    "fact_checker": "fact-checker",
    "news": "news report",
    "reference": "reference site",
    "other": "other website",
}


def _web_search_allowed(req: VerifyClaimRequest) -> bool:
    if not web_search_service.is_configured():
        return False
    # Paid call: skip low-value claims (callers that don't send a score are allowed).
    return req.checkworthiness is None or req.checkworthiness >= settings.web_search_min_checkworthiness


async def _with_web_search(req: VerifyClaimRequest, result: VerificationResponse) -> VerificationResponse:
    web = await web_search_service.check(req.search_text or req.claim, req.context)
    if web is None:
        return result
    explanation = web.reasoning or "The web search did not explain its verdict."
    if web.downgraded:
        explanation += " Only weak or unconfirmed sources were found, so this is not treated as settled."
    strong = sum(s.reliability in ("government", "fact_checker", "news") for s in web.sources)
    explanation += f" (AI web search: {len(web.sources)} source{'s' if len(web.sources) != 1 else ''}, {strong} reliable.)"
    evidence = [
        EvidenceItem(
            source=EvidenceSource(
                name=urlsplit(s.url).hostname or "website",
                publisher=_RELIABILITY_LABEL[s.reliability],
                source_type="WEB_SEARCH_RESULT",
                url=s.url,
                title=s.title,
                reliability=s.reliability,
            ),
            data=EvidenceData(relevant_text=s.quote),
            relevance="DIRECT" if s.reliability in ("government", "fact_checker", "news") else "RELATED",
        )
        for s in web.sources
    ]
    # Keep related published fact-checks that were already attached.
    kept = [e for e in result.evidence if e.source.source_type == "PUBLISHED_FACT_CHECK"]
    return VerificationResponse(
        claim=result.claim,
        assessment=Assessment(status=web.status, explanation=explanation, method="AI_WEB_SEARCH"),
        evidence=evidence + kept,
    )


# --- Published fact-checks (Google Fact Check Tools) ---------------------------------


def _fact_check_evidence(check: PublishedFactCheck, relevance: str) -> EvidenceItem:
    return EvidenceItem(
        source=EvidenceSource(
            name=check.publisher or check.publisher_site or "Fact-checker",
            publisher=check.publisher_site or check.publisher or "Fact-checker",
            source_type="PUBLISHED_FACT_CHECK",
            url=check.url,
            title=check.title,
            date=check.review_date,
        ),
        data=EvidenceData(relevant_text=check.claim_text, rating=check.rating, claimant=check.claimant),
        relevance=relevance,
    )


async def _with_published_fact_checks(
    text: str, result: VerificationResponse, llm: LLMClient | None, rate_limiter: RateLimiter | None
) -> VerificationResponse:
    """For claims our data couldn't settle: use a published fact-check of the SAME claim as
    the verdict (rating mapped to ours); list other hits as related. No key -> unchanged."""
    if not factcheck_service.is_configured():
        return result
    try:
        found = await factcheck_service.search(text, max_results=6)
    except FactCheckClientError as exc:
        logger.warning("fact-check search failed: %s", exc.message)
        return result
    if not found.results:
        result.assessment.explanation += " No published fact-check of it was found either."
        return result

    matched = await factcheck_service.match(text, found.results, llm, rate_limiter)
    related = [_fact_check_evidence(c, "RELATED") for c in matched.related[:_MAX_EVIDENCE]]
    rated = [(c, factcheck_service.rating_status(c.rating)) for c in matched.same]
    usable = [(c, s) for c, s in rated if s]

    if not usable:
        if matched.same or related:
            result.evidence.extend([_fact_check_evidence(c, "DIRECT") for c in matched.same] + related)
            result.assessment.explanation += " Related published fact-checks are listed below."
        return result

    statuses = {s for _, s in usable}
    lead, _ = usable[0]
    who = lead.publisher or lead.publisher_site or "A fact-checker"
    when = f" ({lead.review_date})" if lead.review_date else ""
    if len(statuses) > 1:
        status = "NEEDS_CONTEXT"
        explanation = "Fact-checkers rated this claim differently: " + "; ".join(
            f"{c.publisher or c.publisher_site}: “{c.rating}”" for c, _ in usable
        ) + "."
    else:
        status = statuses.pop()
        explanation = f"{who} rated a matching claim “{lead.rating}”{when}."
        if lead.claim_text:
            explanation += f" Reviewed claim: “{lead.claim_text}”."
    return VerificationResponse(
        claim=result.claim,
        assessment=Assessment(status=status, explanation=explanation, method="PUBLISHED_FACT_CHECK"),
        evidence=[_fact_check_evidence(c, "DIRECT") for c, _ in usable[:_MAX_EVIDENCE]] + related,
    )


# --- STATISTICAL -> OpenSTAT ------------------------------------------------------


async def _verify_statistical(text: str, entities: ClaimEntities, context: str | None = None) -> VerificationResponse:
    claim = VerifiedClaim(text=text, type="STATISTICAL")

    def result(status, explanation, evidence=()):
        return VerificationResponse(
            claim=claim, assessment=Assessment(status=status, explanation=explanation), evidence=list(evidence)
        )

    if _is_flood_control(f"{text} {context or ''}", entities):
        return await _verify_flood_control(text, entities, context)
    if not entities.metric:
        return result("NEEDS_CONTEXT", "The claim does not name which statistic it is about.")
    metric = _METRIC_ALIASES.get(entities.metric.strip().lower(), entities.metric)
    try:
        openstat_service.resolve_dataset(metric)
    except openstat_service.UnsupportedMetricError:
        return result("NO_SOURCE", _no_source(entities.metric))

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
# One project's cost ("the road dike cost ₱289M"): a record within 2% matches when the claim
# names a place/contractor/year; with no scope at all only a near-exact (0.5%) match counts.
_PROJECT_MATCH, _PROJECT_MATCH_UNSCOPED = 0.02, 0.005
# Words that make a peso figure a total rather than one project's cost.
_AGGREGATE_RE = re.compile(
    r"total|kabuuan|spending|spent|ginastos|gumastos|allocat|budget|badyet|pondo para|\ball\b|lahat|"
    r"overall|combined|sum\b|nationwide|buong bansa|napunta",
    re.I,
)
# Words that point at ONE project; a named structure also narrows the matching records.
_SINGLE_RE = re.compile(
    r"\b(the|this|that|one|a single) project\b|\bang proyekto\b|\bproyektong ito\b|cost of one project", re.I
)
_STRUCTURE_RE = re.compile(r"road dike|dike|revetment|seawall|sea wall|slope protection|river control|esplanade|drainage", re.I)


def _is_flood_control(text: str, entities: ClaimEntities) -> bool:
    return bool(_FLOOD_RE.search(entities.metric or "") or _FLOOD_RE.search(text))


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


async def _verify_flood_control(text: str, entities: ClaimEntities, context: str | None = None) -> VerificationResponse:
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

    # The detector sometimes drops the place or contractor named elsewhere in the same line;
    # recover them from names that actually appear in the DPWH records.
    words = f"{text} {context or ''}"
    national = not entities.geography or entities.geography.strip().lower() in ("philippines", "the philippines", "ph")
    recovered = {}
    if national and (place := flood_control_service.places_in_text(words, projects)):
        recovered["geography"] = place
    if not entities.contractor and (company := flood_control_service.contractor_in_text(words, projects)):
        recovered["contractor"] = company
    if recovered:
        entities = entities.model_copy(update=recovered)

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
    currency_note = ""
    if is_amount and re.search(r"dollar|usd|\$", f"{entities.unit or ''} {text}", re.I):
        currency_note = (
            " The claim says dollars, but DPWH contract costs are in pesos (the transcript may have "
            "misheard '₱'), so it was compared in pesos."
        )
    gap = abs(claimed - actual) / actual if actual else float("inf")

    # "The project cost ₱289M" is about ONE project: match individual records.
    about = f"{entities.metric or ''} {text}"
    single = _SINGLE_RE.search(about) or _STRUCTURE_RE.search(f"{about} {context or ''}")
    # A claim about ONE project is never compared with a total (two ₱250M dikes are not one ₱500M dike).
    if is_amount and single and not _AGGREGATE_RE.search(about):
        candidates = flood_control_service.apply_filters(projects, filters)
        structure = _STRUCTURE_RE.search(about) or _STRUCTURE_RE.search(context or "")
        if structure:
            word = structure.group(0).lower()
            named = [p for p in candidates if word in f"{p.description} {p.type_of_work}".lower()]
            candidates = named or candidates
        return _single_project_result(claim, claimed, candidates, filters, scope, currency_note)

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
        f"The claim says {claimed_shown}; DPWH flood control records show {shown} {scope}, {verdict}.{note}{currency_note}",
        [evidence],
        "OFFICIAL_DATA",
    )


def _project_evidence(p) -> EvidenceItem:
    place = ", ".join(x for x in (p.municipality, p.province) if x)
    return EvidenceItem(
        source=EvidenceSource(
            name=FLOOD_CONTROL_SOURCE_NAME,
            publisher=FLOOD_CONTROL_PUBLISHER,
            source_type="GOVERNMENT_DATASET",
            url=FLOOD_CONTROL_PAGE_URL,
            title=p.description or "Flood control project",
            dataset="DPWH flood control project map (2018-2025)",
        ),
        data=EvidenceData(
            value=p.contract_cost,
            unit="pesos",
            period=str(p.funding_year) if p.funding_year else None,
            geography=place or None,
            relevant_text=(
                f"Contract {p.contract_id or '?'} · {p.type_of_work or 'flood control'} · {place or 'location n/a'} · "
                f"contractor {p.contractor or 'n/a'} · funded {p.funding_year or 'n/a'} · "
                f"contract cost {_peso(p.contract_cost or 0)} (approved budget {_peso(p.approved_budget or 0)})"
                + (f" · completed {p.completion_date}" if p.completion_date else "")
            ),
        ),
        relevance="DIRECT",
    )


def _single_project_result(claim, claimed: float, candidates, filters, scope: str, currency_note: str):
    """Match a claimed single-project cost against individual contract records."""
    scoped = any([filters.region, filters.province, filters.municipality, filters.legislative_district,
                  filters.contractor, filters.year, filters.year_from, filters.year_to])
    tolerance = _PROJECT_MATCH if scoped else _PROJECT_MATCH_UNSCOPED
    close = sorted(
        (p for p in candidates if p.contract_cost and abs(p.contract_cost - claimed) / p.contract_cost <= tolerance),
        key=lambda p: abs(p.contract_cost - claimed),
    )
    if close:
        best = close[0]
        where = ", ".join(x for x in (best.municipality, best.province) if x)
        found = (
            f"A DPWH flood control record {scope} matches: “{best.description}” ({where}; contractor "
            f"{best.contractor}; funded {best.funding_year}) with a contract cost of {_peso(best.contract_cost)}"
        )
        if len(close) > 1:
            found += f", and {len(close) - 1} other record{'s' if len(close) > 2 else ''} with a similar cost"
        if scoped:
            status, explanation = "SUPPORTED", f"{found}. The claim says {_peso(claimed)}."
        else:
            status = "NEEDS_CONTEXT"
            explanation = (
                f"{found}. The claim says {_peso(claimed)}, but it didn't name the place or contractor, so it "
                "can't be confirmed as the same project."
            )
        return VerificationResponse(
            claim=claim,
            assessment=Assessment(status=status, explanation=explanation + currency_note, method="OFFICIAL_DATA"),
            evidence=[_project_evidence(p) for p in close[:_MAX_EVIDENCE]],
        )

    nearest = sorted((p for p in candidates if p.contract_cost), key=lambda p: abs(p.contract_cost - claimed))[:1]
    explanation = f"No single DPWH flood control record {scope} has a contract cost near {_peso(claimed)}."
    if nearest:
        explanation += f" The closest is {_peso(nearest[0].contract_cost)} (“{nearest[0].description}”)."
    return VerificationResponse(
        claim=claim,
        assessment=Assessment(
            status="INSUFFICIENT_EVIDENCE",
            explanation=explanation + " The records may not list every project." + currency_note,
            method="OFFICIAL_DATA",
        ),
        evidence=[_project_evidence(p) for p in nearest],
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
