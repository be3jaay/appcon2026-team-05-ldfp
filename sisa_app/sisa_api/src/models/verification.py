from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .claims import CheckType, ClaimEntities
from .openstat import VerificationStatus

VerifiedClaimType = Literal["STATISTICAL", "LEGAL_ISSUANCE", "OTHER"]
SourceType = Literal["OFFICIAL_STATISTICS", "OFFICIAL_DOCUMENT"]


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
    claim_type: CheckType
    entities: ClaimEntities = ClaimEntities()


class VerifiedClaim(BaseModel):
    text: str
    type: VerifiedClaimType


class Assessment(BaseModel):
    status: VerificationStatus
    explanation: str


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


class EvidenceItem(BaseModel):
    source: EvidenceSource
    data: EvidenceData
    relevance: Literal["DIRECT", "RELATED"]


class VerificationResponse(BaseModel):
    claim: VerifiedClaim
    assessment: Assessment
    evidence: list[EvidenceItem] = []
