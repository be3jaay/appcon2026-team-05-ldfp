from typing import Literal

from pydantic import BaseModel, ConfigDict

VerificationStatus = Literal[
    "SUPPORTED",
    "CONTRADICTED",
    "NEEDS_CONTEXT",
    "INSUFFICIENT_EVIDENCE",
    "ERROR",
]


class OpenStatClaimRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "claim": "The unemployment rate is 10%",
                    "metric": "unemployment rate",
                    "value": 10,
                    "unit": "percent",
                    "period": "2026",
                    "geography": "Philippines",
                }
            ]
        }
    )

    claim: str
    metric: str
    value: float | None = None
    unit: str | None = None
    period: str | None = None
    geography: str | None = None


class OpenStatObservation(BaseModel):

    metric: str
    value: float
    unit: str | None
    period: str | None
    geography: str | None


class ClaimSummary(BaseModel):
    text: str
    metric: str
    claimed_value: float | None
    unit: str | None
    period: str | None
    geography: str | None


class SourceCitation(BaseModel):
    name: str
    dataset: str
    table: str
    url: str
    api_url: str


class Evidence(BaseModel):
    value: float
    unit: str | None
    period: str | None
    geography: str | None
    note: str | None = None


class OpenStatCheckResponse(BaseModel):
    status: VerificationStatus
    message: str | None = None
    requested_period: str | None = None
    claim: ClaimSummary | None = None
    source: SourceCitation | None = None
    evidence: Evidence | None = None
    explanation: str | None = None
