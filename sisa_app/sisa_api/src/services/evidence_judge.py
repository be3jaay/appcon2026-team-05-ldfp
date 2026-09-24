"""Compare what a claim says a document does with the document's official text.

Used only after a rule-based search found the exact document (e.g. Executive
Order No. 124, s. 2026) and the claim is about its content ("... to reorganize
DPWH"). One LLM call; it never searches, never summarizes, and only sees the
official excerpt it is given.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

from .claims.classifier import LLMClient, LLMConfigError, RetryableLLMError
from .claims.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

JudgeVerdict = Literal["SUPPORTED", "CONTRADICTED", "NEEDS_CONTEXT"]

JUDGE_PROMPT = """\
You check a claim against the official text of a Philippine government document.

You receive the CLAIM and one or more DOCUMENTS (title + the opening text published by the \
Official Gazette). The opening text usually states the document's title and purpose, but it \
is NOT the full document.

Decide:
- "SUPPORTED": the documents clearly say what the claim says the document does.
- "CONTRADICTED": the documents clearly show the claimed document is about something \
different (e.g. its stated purpose or subject is another matter), or state the opposite.
- "NEEDS_CONTEXT": the opening text does not settle it either way.

Rules:
- Judge only from the given text. Do not use outside knowledge.
- A detail that is simply not mentioned in the opening text is NOT a contradiction.
- If several documents share the number, the claim is CONTRADICTED only if none of them fits.
- The explanation is one short English sentence that quotes or names the relevant words.

Return ONLY JSON: {"verdict": "SUPPORTED|CONTRADICTED|NEEDS_CONTEXT", "explanation": "..."}
"""

_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["SUPPORTED", "CONTRADICTED", "NEEDS_CONTEXT"]},
        "explanation": {"type": "string"},
    },
    "required": ["verdict", "explanation"],
}


@dataclass(frozen=True)
class DocumentText:
    title: str
    text: str | None


@dataclass(frozen=True)
class Judgement:
    verdict: JudgeVerdict
    explanation: str


def build_prompt(claim: str, documents: list[DocumentText]) -> str:
    lines = [f"CLAIM: {claim.strip()}", ""]
    for i, doc in enumerate(documents, start=1):
        lines.append(f"DOCUMENT {i}: {doc.title}")
        lines.append(f"OPENING TEXT: {doc.text or '(no text available)'}")
        lines.append("")
    return "\n".join(lines).strip()


def parse(raw: str) -> Judgement | None:
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
    verdict = str(data.get("verdict", "")).strip().upper()
    explanation = str(data.get("explanation") or "").strip()
    if verdict not in ("SUPPORTED", "CONTRADICTED", "NEEDS_CONTEXT") or not explanation:
        return None
    return Judgement(verdict, explanation)  # type: ignore[arg-type]


async def judge(
    claim: str,
    documents: list[DocumentText],
    llm: LLMClient,
    rate_limiter: RateLimiter | None = None,
) -> Judgement | None:
    """None when the comparison could not be made (no text, LLM down, bad output)."""
    if not any(d.text for d in documents):
        return None
    if rate_limiter is not None:
        await rate_limiter.acquire()
    try:
        raw = await llm.generate(JUDGE_PROMPT, build_prompt(claim, documents), _SCHEMA)
    except (RetryableLLMError, LLMConfigError) as exc:
        logger.warning("evidence comparison unavailable: %s", exc)
        return None
    except Exception:
        logger.exception("evidence comparison failed")
        return None
    result = parse(raw)
    if result is None:
        logger.warning("evidence comparison returned unusable output: %.200r", raw)
    return result
