from typing import Literal

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

ClaimType = Literal["fact", "legal", "opinion", "promise", "sarcasm", "figurative", "vague"]
CLAIM_TYPES: tuple[str, ...] = ClaimType.__args__


# Which official source can check a claim: STATISTICAL -> PSA OpenSTAT,
# LEGAL -> Official Gazette, OTHER -> no automated source yet.
CheckType = Literal["STATISTICAL", "LEGAL", "OTHER"]
CHECK_TYPES: tuple[str, ...] = CheckType.__args__


class ClaimEntities(BaseModel):
    """What the claim says, as structured fields. Only the fields that apply are set."""

    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=True)

    # STATISTICAL
    metric: str | None = Field(None, examples=["unemployment rate"])
    value: float | None = None
    unit: str | None = Field(None, examples=["percent"])
    geography: str | None = Field(None, examples=["Philippines"])
    # LEGAL
    document_type: str | None = Field(None, examples=["Executive Order"])
    document_number: str | None = Field(None, examples=["124"])
    subject: str | None = Field(None, description="What the document is claimed to do/contain; null for existence-only claims.")
    # both
    date: str | None = Field(None, examples=["July 2026"])

    @field_validator("value", mode="before")
    @classmethod
    def _number(cls, v):
        # LLMs write "5%", "₱125,000,000" or "3.9 percent"; anything unparseable becomes None.
        if v is None or isinstance(v, (int, float)):
            return v
        m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(v))
        return float(m.group(0).replace(",", "")) if m else None

    @field_validator("*", mode="before")
    @classmethod
    def _blank_is_none(cls, v):
        return None if isinstance(v, str) and not v.strip() else v


class TranscriptSegment(BaseModel):
    """One finished transcript segment, as closed by the frontend Soniox hook
    (Soniox endpoint `<end>`, speaker change, or stop)."""

    model_config = ConfigDict(coerce_numbers_to_str=True)

    segment_id: str
    text: str
    speaker: str = "1"
    start_ms: int | None = None
    end_ms: int | None = None


class Claim(BaseModel):
    id: str
    segment_id: str
    timestamp: int | None = Field(None, description="Segment start in ms from stream start.")
    speaker: str
    text: str
    quote: str | None = Field(None, description="Verbatim words in the segment; None if not found.")
    type: ClaimType
    checkworthiness: float = Field(ge=0, le=1)
    reason: str
    literal_claim: str | None = None
    check_type: CheckType = "OTHER"
    entities: ClaimEntities | None = None


class SkippedSegment(BaseModel):
    segment_id: str
    reason: str


class DetectionResult(BaseModel):
    claims: list[Claim] = []
    skipped: list[SkippedSegment] = []
    llm_calls: int = 0
    llm_errors: int = 0


# --- websocket protocol ---------------------------------------------------


class SegmentMessage(BaseModel):
    type: Literal["segment"]
    segment: TranscriptSegment

