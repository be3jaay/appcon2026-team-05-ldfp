from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .claims import Claim, TranscriptSegment
from .verification import VerificationResponse


class SessionSummaryRequest(BaseModel):
    """Everything from one finished live session: the transcript, the claims the detector
    found in it, and whatever verification results the frontend already collected for them.
    There is no backend session store (see the README's "no persistence" gap), so the client
    sends what it already has in memory."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "transcript": [
                        {"segment_id": "1", "text": "Ang badyet ng ahensya ay ₱125 milyon.", "speaker": "1"}
                    ],
                    "claims": [],
                    "evidence": [],
                }
            ]
        }
    )

    transcript: list[TranscriptSegment] = Field(default_factory=list, description="Finished segments, in order.")
    claims: list[Claim] = Field(default_factory=list, description="Claims the detector found during the session.")
    evidence: list[VerificationResponse] = Field(
        default_factory=list,
        description="Verification results (assessment + evidence) the frontend already collected, one per checked claim.",
    )


class SessionSummaryResponse(BaseModel):
    language: Literal["tl"] = "tl"
    summary_text: str = Field(description="Spoken-style Tagalog analysis of the whole session.")
    audio_base64: str | None = Field(
        None, description="Base64-encoded audio of `summary_text`; None if TTS failed or is not configured."
    )
    audio_format: str = "mp3"
    audio_content_type: str = "audio/mpeg"
    audio_error: str | None = Field(
        None, description="Set when audio_base64 is None because the audio could not be generated."
    )
