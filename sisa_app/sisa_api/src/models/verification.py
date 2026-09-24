from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .claims import CheckType, ClaimEntities
from .openstat import VerificationStatus

VerifiedClaimType = Literal["STATISTICAL", "LEGAL_ISSUANCE", "OTHER"]
SourceType = Literal["OFFICIAL_STATISTICS", "OFFICIAL_DOCUMENT", "GOVERNMENT_DATASET", "PUBLISHED_FACT_CHECK"]


class VerifyClaimRequest(BaseModel):
    """A detected claim with its structured parts (from the claim detector)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "claim": "The unemployment rate was 5% in July 2026",
                    "claim_type": "STATISTICAL",
                    "entities": {
                        "metric": "unemployment rate",
                        "value": 5,
                        "unit": "percent",
                        "date": "July 2026",
                        "geography": "Philippines",
                    },
                },
                {
                    "claim": "The President issued Executive Order No. 124",
                    "claim_type": "LEGAL",
                    "entities": {"document_type": "Executive Order", "document_number": "124"},
                },
            ]
        }
    )

    claim: str = Field(min_length=3, max_length=500)
    search_text: str | None = Field(
        None, max_length=500, description="English version of the claim (the detector's text_en), used to search fact-checks."
    )
    claim_type: CheckType
    entities: ClaimEntities = ClaimEntities()


class VerifiedClaim(BaseModel):
    text: str
    type: VerifiedClaimType


AssessmentMethod = Literal["OFFICIAL_DATA", "DOCUMENT_MATCH", "AI_COMPARISON", "PUBLISHED_FACT_CHECK", "NONE"]


class Assessment(BaseModel):
    status: VerificationStatus
    explanation: str
    method: AssessmentMethod = Field(
        "NONE",
        description=(
            "OFFICIAL_DATA: compared with a published figure; DOCUMENT_MATCH: the named document was "
            "(not) found; AI_COMPARISON: an LLM compared the claim with the official text shown as evidence; "
            "PUBLISHED_FACT_CHECK: an independent fact-checker's published rating of the same claim."
        ),
    )


class EvidenceSource(BaseModel):
    name: str
    publisher: str
    source_type: SourceType
    url: str
    title: str | None = None
    date: str | None = None
    document_type: str | None = None
    document_number: str | None = None
    dataset: str | None = None
    table: str | None = None


class EvidenceData(BaseModel):
    relevant_text: str | None = Field(None, description="Verbatim text from the source (no summaries).")
    document_reference: str | None = None
    value: float | None = None
    unit: str | None = None
    period: str | None = None
    geography: str | None = None
    rating: str | None = Field(None, description="A fact-checker's own rating, verbatim (e.g. 'False').")
    claimant: str | None = Field(None, description="Who made the claim that was fact-checked.")


class EvidenceItem(BaseModel):
    source: EvidenceSource
    data: EvidenceData
    relevance: Literal["DIRECT", "RELATED"]


class VerificationResponse(BaseModel):
    claim: VerifiedClaim
    assessment: Assessment
    evidence: list[EvidenceItem] = []
