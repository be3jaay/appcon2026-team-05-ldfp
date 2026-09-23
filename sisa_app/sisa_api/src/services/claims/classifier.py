"""One LLM call per batch: label every claim-like statement in the batch.

The system prompt is a module constant so it is byte-identical on every call
(Gemini implicit prefix caching). Nothing in it may be specific to one video,
speaker or politician.
"""

import json
import logging
import re
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError, field_validator

from ...models.claims import CLAIM_TYPES, Claim, TranscriptSegment

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    async def generate(self, system: str, user: str, response_schema: dict | None = None) -> str: ...


class ClassifierError(RuntimeError):
    pass


SYSTEM_PROMPT = """\
You label claims in live transcripts of Philippine public speech (hearings, debates, \
interviews, speeches, news). Speech may be Tagalog, English or Taglish, and comes from \
automatic speech recognition, so expect missing punctuation and small transcription errors.

You receive numbered segments. Lines marked "[C1]", "[C2]" are CONTEXT only: use them to \
understand the numbered lines (e.g. to detect sarcasm or resolve "iyon"/"that"), but NEVER \
return a claim for a CONTEXT line.

For each numbered segment, find every statement that asserts something, and label each one. \
A statement is CHECKABLE only if all three hold:
  1. It asserts that something is or was the case (not a question, greeting or command).
  2. It is about facts, not feelings or values.
  3. It is specific enough to look up: a number, amount, date, name, event, document, law, \
institution or record.

Types (use exactly one):
- "fact": checkable assertion about the world: amounts, statistics, dates, events, who did \
or said what, what a report or document contains.
- "legal": checkable assertion about what a law, the Constitution, a rule, a court ruling or \
a legal procedure says or requires (e.g. "Ayon sa Article XI, Section 3…").
- "opinion": value judgment, feeling, praise or blame, or an unspecific prediction. Not checkable.
- "promise": commitment to future action ("gagawin namin", "I will build…"). Not checkable yet.
- "sarcasm": literal words mean the opposite of what is intended, usually clear only from \
context or tone markers ("ang galing naman", "wow, very transparent"). Put the intended \
checkable claim, if any, in literal_claim.
- "figurative": metaphor, idiom or hyperbole ("kinain ng buwaya ang pondo", "a mountain of \
debt"). Put the checkable claim inside it, if any, in literal_claim.
- "vague": sounds factual but lacks the detail needed to check it ("marami ang nawala", \
"some officials got money"). The reason MUST say which detail is missing (who, how much, \
when, which document…).

Rules:
- Split mixed sentences: an opinion plus a fact in one segment become two items with the \
same segment number (e.g. "Nakakahiya, ₱50 million ang ginastos sa isang araw" → opinion + fact).
- "Sa tingin ko", "I think", "parang", "I believe" in front of a factual statement does NOT \
make it an opinion: label the factual part as fact/legal.
- Quoting or citing a source ("Sabi ng COA…", "According to the PSA…") is a fact claim about \
what that source said; keep the source in the text.
- Hedged numbers ("mga ₱100M yata", "around 20 percent", "halos kalahati") are still fact claims.
- Rhetorical questions that clearly assert something ("Hindi ba't kayo ang pumirma noong 2022?") \
may be labelled; genuine questions are not claims.
- Greetings, thanks, procedure and filler produce no items.
- "text": the claim restated as one short, self-contained sentence in the speaker's language, \
resolving pronouns from context where obvious. Do not add facts that were not said.
- "checkworthiness": 0 to 1, how worth fact-checking it is: high (0.7–1) for specific, \
consequential fact/legal claims; medium for hedged or partly specific ones; low (0–0.3) for \
opinion, promise and vague.
- "reason": one short English sentence explaining the label.
- "literal_claim": for figurative and sarcasm, the plain checkable claim, or "" if there is \
none; for other types, "".
- Do not judge whether a claim is true. Only detect and label.

Return ONLY JSON of this shape:
{"claims": [{"segment": <number of the segment>, "text": "...", "type": "fact|legal|opinion|\
promise|sarcasm|figurative|vague", "checkworthiness": 0.0, "reason": "...", "literal_claim": ""}]}
If there are no claims, return {"claims": []}.
"""

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "segment": {"type": "integer"},
                    "text": {"type": "string"},
                    "type": {"type": "string", "enum": list(CLAIM_TYPES)},
                    "checkworthiness": {"type": "number"},
                    "reason": {"type": "string"},
                    "literal_claim": {"type": "string"},
                },
                "required": ["segment", "text", "type", "checkworthiness", "reason"],
            },
        }
    },
    "required": ["claims"],
}

_DEFAULT_REASONS = {
    "vague": "Lacks specific details (who, how much, when or which document) needed to check it.",
}


class _RawClaim(BaseModel):
    """Lenient shape of one LLM item. Anything that fails here is dropped."""

    segment: int
    text: str
    type: str = "vague"
    checkworthiness: float = 0.5
    reason: str = ""
    literal_claim: str | None = None

    @field_validator("segment", mode="before")
    @classmethod
    def _segment_number(cls, v: Any) -> Any:
        # Accept 2, "2", "[2]"; "[C1]" and friends fail and the item is dropped.
        if isinstance(v, str):
            m = re.fullmatch(r"\s*\[?\s*(\d+)\s*\]?\s*", v)
            if not m:
                raise ValueError(f"not a numbered segment: {v!r}")
            return int(m.group(1))
        return v

    @field_validator("text")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("empty text")
        return v

    @field_validator("type", mode="before")
    @classmethod
    def _known_type(cls, v: Any) -> str:
        v = str(v or "").strip().lower()
        return v if v in CLAIM_TYPES else "vague"

    @field_validator("checkworthiness", mode="before")
    @classmethod
    def _clamp(cls, v: Any) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.5
        if f != f:  # NaN
            return 0.5
        return min(1.0, max(0.0, f))

    @field_validator("reason", mode="before")
    @classmethod
    def _reason_str(cls, v: Any) -> str:
        return "" if v is None else str(v).strip()

    @field_validator("literal_claim", mode="before")
    @classmethod
    def _literal_str(cls, v: Any) -> str | None:
        if v is None:
            return None
        v = str(v).strip()
        return v or None


def build_user_prompt(batch: list[TranscriptSegment], context: list[TranscriptSegment]) -> str:
    lines: list[str] = []
    for i, seg in enumerate(context, start=1):
        lines.append(f"[C{i}] (CONTEXT only, do not extract) Speaker {seg.speaker}: {seg.text.strip()}")
    for i, seg in enumerate(batch, start=1):
        lines.append(f"[{i}] Speaker {seg.speaker}: {seg.text.strip()}")
    return "\n".join(lines)


def _extract_json(raw: str) -> Any:
    text = (raw or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


def parse_claims(raw: str, batch: list[TranscriptSegment]) -> list[Claim]:
    """Turn raw LLM output into validated claims mapped back to their segments.
    Never raises on bad output; invalid items are dropped and logged."""
    data = _extract_json(raw)
    if isinstance(data, dict):
        items = data.get("claims")
    elif isinstance(data, list):
        items = data
    else:
        logger.warning("Claim classifier returned unparseable output: %.200r", raw)
        return []
    if not isinstance(items, list):
        logger.warning("Claim classifier output has no 'claims' list: %.200r", raw)
        return []

    claims: list[Claim] = []
    per_segment: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            parsed = _RawClaim.model_validate(item)
        except ValidationError as exc:
            logger.info("Dropping invalid claim item %r: %s", item, exc.errors()[0]["msg"])
            continue
        if not 1 <= parsed.segment <= len(batch):
            logger.info("Dropping claim for out-of-range segment %s", parsed.segment)
            continue
        seg = batch[parsed.segment - 1]
        n = per_segment.get(seg.segment_id, 0)
        per_segment[seg.segment_id] = n + 1
        claims.append(
            Claim(
                id=f"{seg.segment_id}:{n}",
                segment_id=seg.segment_id,
                timestamp=seg.start_ms,
                speaker=seg.speaker,
                text=parsed.text,
                type=parsed.type,
                checkworthiness=parsed.checkworthiness,
                reason=parsed.reason or _DEFAULT_REASONS.get(parsed.type, f"Labelled as {parsed.type}."),
                literal_claim=parsed.literal_claim if parsed.type in ("figurative", "sarcasm") else None,
            )
        )
    return claims


class ClaimClassifier:
    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.calls = 0

    async def classify(
        self, batch: list[TranscriptSegment], context: list[TranscriptSegment] | None = None
    ) -> list[Claim]:
        """Exactly one LLM call per non-empty batch."""
        if not batch:
            return []
        self.calls += 1
        try:
            raw = await self.llm.generate(SYSTEM_PROMPT, build_user_prompt(batch, context or []), RESPONSE_SCHEMA)
        except Exception as exc:
            raise ClassifierError(f"LLM call failed: {exc}") from exc
        return parse_claims(raw, batch)
