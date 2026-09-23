from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ClaimType = Literal["fact", "legal", "opinion", "promise", "sarcasm", "figurative", "vague"]
CLAIM_TYPES: tuple[str, ...] = ClaimType.__args__


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
    type: ClaimType
    checkworthiness: float = Field(ge=0, le=1)
    reason: str
    literal_claim: str | None = None


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

