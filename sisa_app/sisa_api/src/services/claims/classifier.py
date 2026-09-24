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

from ...models.claims import CHECK_TYPES, CLAIM_TYPES, Claim, ClaimEntities, TranscriptSegment

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    async def generate(self, system: str, user: str, response_schema: dict | None = None) -> str: ...


class RetryableLLMError(RuntimeError):
    """Raised by an LLMClient for transient failures (rate limit, overload)."""

    def __init__(self, message: str, retry_after: float, exponential: bool = False):
        super().__init__(message)
        self.retry_after = retry_after
        # True when the provider gave no delay: back off 1x, 2x, 4x... per attempt.
        self.exponential = exponential


class LLMConfigError(RuntimeError):
    """A provider is missing a key or is misconfigured (bad key, unknown model). Not retried."""


class ClassifierError(RuntimeError):
    def __init__(self, message: str, retry_after: float | None = None, exponential: bool = False):
        super().__init__(message)
        self.retry_after = retry_after  # None = not worth retrying
        self.exponential = exponential


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
- "quote": the exact words from the segment that carry this claim, copied verbatim (same \
spelling, no paraphrase), as short as possible while still containing the claim.
- "text": the claim restated as one short, self-contained sentence in the speaker's language, \
resolving pronouns from context where obvious. Do not add facts that were not said.
- "text_en": the same claim in English (identical to "text" if already English), used to \
search English-language sources.
- "checkworthiness": 0 to 1, how worth fact-checking it is: high (0.7–1) for specific, \
consequential fact/legal claims; medium for hedged or partly specific ones; low (0–0.3) for \
opinion, promise and vague.
- "reason": one short English sentence explaining the label.
- "literal_claim": for figurative and sarcasm, the plain checkable claim, or "" if there is \
none; for other types, "".
- "check_type": which official source could check it. "STATISTICAL" for official \
statistics and government spending records (rates, counts, prices, population, GDP, poverty, \
budgets, amounts spent on or number of government projects and contracts). "LEGAL" for claims \
about a law, the Constitution or an issuance (Republic Act, Executive Order, Proclamation, \
Administrative Order, Memorandum Circular…): that it exists, was signed/issued, or what it says. \
Otherwise "OTHER". Opinion, promise and vague claims are "OTHER".
- "entities": the claim's parts as fields; omit or leave empty what the speaker did not say, \
never guess. STATISTICAL: metric (e.g. "unemployment rate", "flood control project cost", \
"number of flood control projects"), value (number only, in full units: "₱125 milyon" -> \
125000000, "3.9%" -> 3.9), unit ("percent", "pesos", "projects", "persons"…), date (period, \
e.g. "July 2026" or "2023"), geography (the region, province or city named; "Philippines" only \
if clearly national), contractor (the company named, if any). LEGAL: document_type (e.g. "Executive Order"), document_number (e.g. "124"), date, subject (what the document is claimed to do or contain, or empty if the claim is only that it exists or was issued).
- Do not judge whether a claim is true. Only detect and label.

Return ONLY JSON of this shape:
{"claims": [{"segment": <number of the segment>, "quote": "...", "text": "...", "text_en": "...", "type": "fact|legal|opinion|\
promise|sarcasm|figurative|vague", "checkworthiness": 0.0, "reason": "...", "literal_claim": "", "check_type": "STATISTICAL|LEGAL|OTHER", "entities": {...only the fields that apply...}}]}
Example entities: STATISTICAL {"metric": "unemployment rate", "value": 5, "unit": "percent", "date": "July 2026", "geography": "Philippines"}; LEGAL {"document_type": "Executive Order", "document_number": "124"}; OTHER {}.
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
                    "quote": {"type": "string"},
                    "text": {"type": "string"},
                    "text_en": {"type": "string"},
                    "type": {"type": "string", "enum": list(CLAIM_TYPES)},
                    "checkworthiness": {"type": "number"},
                    "reason": {"type": "string"},
                    "literal_claim": {"type": "string"},
                    "check_type": {"type": "string", "enum": list(CHECK_TYPES)},
                    "entities": {
                        "type": "object",
                        "properties": {
                            "metric": {"type": "string"},
                            "value": {"type": "number"},
                            "unit": {"type": "string"},
                            "date": {"type": "string"},
                            "geography": {"type": "string"},
                            "contractor": {"type": "string"},
                            "document_type": {"type": "string"},
                            "document_number": {"type": "string"},
                            "subject": {"type": "string"},
                        },
                    },
                },
                "required": ["segment", "quote", "text", "type", "checkworthiness", "reason"],
            },
        }
    },
    "required": ["claims"],
}

_ROUTABLE = frozenset({"fact", "legal", "figurative", "sarcasm"})
_ENTITY_FIELDS = {
    "STATISTICAL": {"metric", "value", "unit", "date", "geography", "contractor"},
    "LEGAL": {"document_type", "document_number", "subject", "date"},
    "OTHER": set(),
}


def _entities_for(check_type: str, entities: ClaimEntities | None) -> ClaimEntities | None:
    """Keep only the fields that belong to the claim's check_type (models sometimes fill
    every field, e.g. value=0 on a legal claim)."""
    if entities is None:
        return None
    kept = entities.model_dump(include=_ENTITY_FIELDS[check_type], exclude_none=True)
    return ClaimEntities(**kept) if kept else None

_DEFAULT_REASONS = {
    "vague": "Lacks specific details (who, how much, when or which document) needed to check it.",
}


class _RawClaim(BaseModel):
    """Lenient shape of one LLM item. Anything that fails here is dropped."""

    segment: int
    text: str
    quote: str | None = None
    text_en: str | None = None
    type: str = "vague"
    checkworthiness: float = 0.5
    reason: str = ""
    literal_claim: str | None = None
    check_type: str = "OTHER"
    entities: ClaimEntities | None = None

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

    @field_validator("check_type", mode="before")
    @classmethod
    def _known_check_type(cls, v: Any) -> str:
        v = str(v or "").strip().upper()
        return v if v in CHECK_TYPES else "OTHER"

    @field_validator("entities", mode="before")
    @classmethod
    def _lenient_entities(cls, v: Any) -> Any:
        # Bad entities must not drop the claim itself.
        if not isinstance(v, dict):
            return None
        try:
            entities = ClaimEntities.model_validate(v)
        except ValidationError:
            return None
        return entities if entities.model_dump(exclude_none=True) else None

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

    @field_validator("quote", "literal_claim", "text_en", mode="before")
    @classmethod
    def _literal_str(cls, v: Any) -> str | None:
        if v is None:
            return None
        v = str(v).strip()
        return v or None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def verbatim_quote(quote: str | None, segment_text: str) -> str | None:
    """Keep the quote only if it really occurs in the segment (so the UI can highlight it)."""
    if not quote:
        return None
    q = quote.strip(" \"'“”‘’.,")
    return q if q and _norm(q) in _norm(segment_text) else None


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
                quote=verbatim_quote(parsed.quote, seg.text),
                text_en=parsed.text_en,
                type=parsed.type,
                checkworthiness=parsed.checkworthiness,
                reason=parsed.reason or _DEFAULT_REASONS.get(parsed.type, f"Labelled as {parsed.type}."),
                literal_claim=parsed.literal_claim if parsed.type in ("figurative", "sarcasm") else None,
                # Only statements that assert something checkable get routed to a source.
                check_type=parsed.check_type if parsed.type in _ROUTABLE else "OTHER",
                entities=_entities_for(parsed.check_type, parsed.entities) if parsed.type in _ROUTABLE else None,
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
        except RetryableLLMError as exc:
            raise ClassifierError(
                f"LLM call failed: {exc}", retry_after=exc.retry_after, exponential=exc.exponential
            ) from exc
        except Exception as exc:
            raise ClassifierError(f"LLM call failed: {exc}") from exc
        return parse_claims(raw, batch)
