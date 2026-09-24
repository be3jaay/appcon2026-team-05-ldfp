"""End-of-session Tagalog analysis: one LLM call over the transcript/claims/evidence the
client already has, then one Soniox TTS call to speak it.

Like `evidence_judge`, this makes exactly one LLM call (not per-segment, not per-claim) and
never adds SDK-level retries: any retry goes through the caller's shared `RateLimiter` and the
provider fallback chain. A TTS failure degrades gracefully (text-only response) instead of
failing the whole request, matching how `evidence_judge.judge` returns `None` on failure rather
than raising.
"""

import base64
import json
import logging
import re

from ..clients import soniox_tts_client
from ..clients.soniox_tts_client import SonioxTTSConfigError, SonioxTTSRequestError
from ..config import settings
from ..models.claims import Claim, TranscriptSegment
from ..models.session_summary import SessionSummaryRequest, SessionSummaryResponse
from ..models.verification import VerificationResponse
from .claims.classifier import LLMClient, LLMConfigError, RetryableLLMError
from .claims.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You write a short, spoken-style closing summary in Tagalog for a live fact-checking session \
(SISA) that just ended. You receive the session's TRANSCRIPT, the CLAIMS the system detected \
in it, and the VERIFICATION RESULTS (evidence) the system already gathered for some of those \
claims.

Write ONE spoken Tagalog summary, as if a narrator were reading it aloud right after the \
session ends. It must:
- Be entirely in Tagalog (natural, conversational; proper nouns, numbers and peso amounts may \
stay as written).
- Briefly say what the session was about, based on the transcript.
- Say how many claims were found, then for each claim that has a verification result, state \
the claim and its verdict in plain spoken words. Map SUPPORTED -> "napatunayang tama o \
tumutugma sa opisyal na datos", CONTRADICTED -> "sumasalungat sa opisyal na datos", \
NEEDS_CONTEXT -> "kailangan pa ng karagdagang konteksto", INSUFFICIENT_EVIDENCE -> "kulang ang \
ebidensyang nahanap", NO_SOURCE -> "walang available na opisyal na source para dito", \
ERROR -> "hindi natapos ma-verify dahil sa isang teknikal na problema".
- Never invent a verdict for a claim that has no verification result; call those "hindi pa \
na-verify" or "wala pang ebidensyang nakalap para dito".
- Stay neutral and conservative: say only what each verdict's own explanation supports, never \
declare a claim "totoo" or "mali" beyond that.
- Use plain spoken language only: no markdown, no bullet points, no headers, no emojis - a \
text-to-speech voice will read this aloud exactly as written.
- Keep it concise: a few short spoken paragraphs, meant to be heard in under two minutes.

Return ONLY JSON of this shape: {"summary_tl": "..."}
"""

_SCHEMA = {
    "type": "object",
    "properties": {"summary_tl": {"type": "string"}},
    "required": ["summary_tl"],
}

# Keep the prompt bounded regardless of how long the live session ran.
_MAX_TRANSCRIPT_CHARS = 6000
_MAX_CLAIMS = 40
_MAX_EVIDENCE = 40


class SessionSummaryError(RuntimeError):
    """The Tagalog summary text could not be produced (no LLM configured, all providers
    failed, or the LLM's output was unusable). Unlike TTS, this fails the whole request:
    there is nothing to speak without it."""


def _transcript_block(transcript: list[TranscriptSegment]) -> str:
    lines = [f"Speaker {seg.speaker}: {seg.text.strip()}" for seg in transcript if seg.text.strip()]
    text = "\n".join(lines)
    if len(text) > _MAX_TRANSCRIPT_CHARS:
        text = "...\n" + text[-_MAX_TRANSCRIPT_CHARS:]  # keep the most recent part of a long session
    return text or "(walang transcript na natanggap)"


def _claims_block(claims: list[Claim]) -> str:
    if not claims:
        return "(walang na-detect na claim)"
    lines = [f'- [{c.check_type}] "{c.text}"' for c in claims[:_MAX_CLAIMS]]
    return "\n".join(lines)


def _evidence_block(evidence: list[VerificationResponse]) -> str:
    if not evidence:
        return "(walang natanggap na verification result)"
    lines = [
        f'- "{item.claim.text}" -> {item.assessment.status}: {item.assessment.explanation}'
        for item in evidence[:_MAX_EVIDENCE]
    ]
    return "\n".join(lines)


def build_user_prompt(
    transcript: list[TranscriptSegment], claims: list[Claim], evidence: list[VerificationResponse]
) -> str:
    return (
        f"TRANSCRIPT:\n{_transcript_block(transcript)}\n\n"
        f"CLAIMS FOUND ({len(claims)}):\n{_claims_block(claims)}\n\n"
        f"VERIFICATION RESULTS ({len(evidence)}):\n{_evidence_block(evidence)}"
    )


def parse_summary(raw: str) -> str | None:
    """None when the LLM's output could not be read as {"summary_tl": "..."}."""
    text = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text[text.find("{") : text.rfind("}") + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    summary = str(data.get("summary_tl") or "").strip()
    return summary or None


async def _synthesize_audio(summary_text: str) -> tuple[str | None, str | None]:
    """(audio_base64, audio_error). Never raises: a TTS outage must not lose the text summary."""
    try:
        audio = await soniox_tts_client.synthesize(
            summary_text,
            api_key=settings.soniox_api_key,
            url=settings.soniox_tts_url,
            model=settings.soniox_tts_model,
            language=settings.soniox_tts_language,
            voice=settings.soniox_tts_voice,
            audio_format=settings.soniox_tts_audio_format,
            timeout_seconds=settings.soniox_tts_timeout_seconds,
        )
    except (SonioxTTSConfigError, SonioxTTSRequestError) as exc:
        logger.warning("session summary audio unavailable: %s", exc)
        return None, str(exc)
    return base64.b64encode(audio).decode("ascii"), None


async def generate(
    req: SessionSummaryRequest, llm: LLMClient, rate_limiter: RateLimiter | None = None
) -> SessionSummaryResponse:
    """One LLM call for the Tagalog text, then one Soniox TTS call for the audio."""
    if rate_limiter is not None:
        await rate_limiter.acquire()

    user_prompt = build_user_prompt(req.transcript, req.claims, req.evidence)
    try:
        raw = await llm.generate(SYSTEM_PROMPT, user_prompt, _SCHEMA)
    except (RetryableLLMError, LLMConfigError) as exc:
        raise SessionSummaryError(f"LLM call failed: {exc}") from exc

    summary_text = parse_summary(raw)
    if not summary_text:
        logger.warning("session summary LLM returned unusable output: %.200r", raw)
        raise SessionSummaryError("The LLM returned an unusable summary.")

    audio_base64, audio_error = await _synthesize_audio(summary_text)

    return SessionSummaryResponse(
        summary_text=summary_text,
        audio_base64=audio_base64,
        audio_format=settings.soniox_tts_audio_format,
        audio_content_type=soniox_tts_client.content_type_for(settings.soniox_tts_audio_format),
        audio_error=audio_error,
    )
