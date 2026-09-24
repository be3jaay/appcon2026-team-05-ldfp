"""Route a detected claim to the official source that can check it.

STATISTICAL -> PSA OpenSTAT (existing openstat_service, unchanged)
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
from . import evidence_judge, official_gazette_service, openstat_service
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
