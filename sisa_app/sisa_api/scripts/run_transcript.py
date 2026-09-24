"""Run a plain-text transcript through the whole SISA pipeline and report every verdict.

    cd sisa_api
    uv run python scripts/run_transcript.py ../transcribe.md
    uv run python scripts/run_transcript.py ../transcribe.md --limit 10 --json out.json

It splits the text into segments the way live transcription does (a couple of
sentences each), runs the prefilter + batched LLM detection, then verifies every
claim the frontend would send to /claims/verify. Uses the real providers and
sources configured in .env (Groq/Gemini, Official Gazette, DPWH data, PSA,
Google Fact Check, OpenAI web search), so it makes real API calls.
"""

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.clients.llm_chain import build_llm_client  # noqa: E402
from src.config import settings  # noqa: E402
from src.models.claims import Claim, TranscriptSegment  # noqa: E402
from src.models.verification import VerifyClaimRequest  # noqa: E402
from src.services import claim_verification_service  # noqa: E402
from src.services.claims.classifier import ClaimClassifier  # noqa: E402
from src.services.claims.detector import ClaimDetector  # noqa: E402
from src.services.claims.rate_limiter import RateLimiter  # noqa: E402

MAX_WORDS = 45


def segments_from_text(text: str) -> list[TranscriptSegment]:
    """Sentence-split, then pack up to ~45 words per segment (like Soniox utterances)."""
    sentences = [s.strip() for s in re.split(r"(?:(?<=[.!?])|(?<=[.!?][\"”]))\s+", text.strip()) if s.strip()]
    segments, current = [], []
    for sentence in sentences:
        if current and len(" ".join(current + [sentence]).split()) > MAX_WORDS:
            segments.append(" ".join(current))
            current = []
        current.append(sentence)
    if current:
        segments.append(" ".join(current))
    return [
        TranscriptSegment(segment_id=str(i), text=t, speaker="1", start_ms=i * 15000, end_ms=i * 15000 + 14000)
        for i, t in enumerate(segments)
    ]


def is_verifiable(c: Claim) -> bool:  # same rule as the frontend (lib/verification.ts)
    return c.check_type in ("STATISTICAL", "LEGAL") or c.type in ("fact", "legal")


async def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=Path)
    parser.add_argument("--limit", type=int, help="only the first N segments")
    parser.add_argument("--no-web", action="store_true", help="skip the paid AI web search step")
    parser.add_argument("--json", type=Path, help="write the full report here")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if args.no_web:
        settings.openai_api_key = None

    segments = segments_from_text(args.file.read_text(encoding="utf-8"))[: args.limit]
    # Same context the frontend sends: the line before, the claim's line, and the next one.
    context_by_id = {
        s.segment_id: " ".join(x.text for x in segments[max(0, i - 1) : i + 2]) for i, s in enumerate(segments)
    }
    llm = build_llm_client()
    limiter = RateLimiter(settings.llm_rpm)
    detector = ClaimDetector(
        ClaimClassifier(llm),
        max_segments=settings.claims_batch_max_segments,
        max_wait_s=3600,
        context_size=settings.claims_context_segments,
        max_call_segments=settings.claims_max_segments_per_call,
        max_attempts=settings.claims_llm_max_attempts,
        rate_limiter=limiter,
    )
    started = time.perf_counter()
    print(f"{len(segments)} segments → detecting with {getattr(llm, 'name', llm)} …", flush=True)
    detected = await detector.process(segments)
    print(f"detected {len(detected.claims)} claims in {detected.llm_calls} LLM calls "
          f"({detected.llm_errors} failed), {len(detected.skipped)} segments skipped "
          f"[{time.perf_counter() - started:.0f}s]\n", flush=True)

    rows = []
    for c in detected.claims:
        row = {"segment": c.segment_id, "type": c.type, "check_type": c.check_type, "text": c.text,
               "fallacy": getattr(c, "fallacy", None), "evasion": getattr(c, "evasion", None), "contradicts": c.contradicts,
               "entities": c.entities.model_dump(exclude_none=True) if c.entities else None}
        if is_verifiable(c):
            req = VerifyClaimRequest(
                claim=c.text[:500], search_text=(c.text_en or None) and c.text_en[:500], claim_type=c.check_type,
                entities=c.entities or {}, checkworthiness=c.checkworthiness, context=context_by_id[c.segment_id],
            )
            res = await claim_verification_service.verify(req, llm, limiter)
            row.update(status=res.assessment.status, method=res.assessment.method,
                       explanation=res.assessment.explanation, evidence=len(res.evidence))
        else:
            row.update(status="(not checked: " + c.type + ")", method="-", explanation="", evidence=0)
        rows.append(row)
        flags = " ".join(x for x in (f"fallacy={row['fallacy']}" if row["fallacy"] else "",
                                     "EVASION" if row["evasion"] else "",
                                     f"CONFLICTS-WITH={row['contradicts']}" if row["contradicts"] else "") if x)
        print(f"[{c.segment_id:>2}] {c.type:10} {c.check_type:11} {row['status']:22} {row['method']:20} "
              f"{c.text[:80]} {flags}", flush=True)
        if row["explanation"]:
            print(f"        {row['explanation'][:230]}", flush=True)

    print("\n=== Verdicts ===")
    for status, n in Counter(r["status"] for r in rows).most_common():
        print(f"  {n:>3}  {status}")
    print("=== How they were reached ===")
    for method, n in Counter(r["method"] for r in rows if r["method"] != "-").most_common():
        print(f"  {n:>3}  {method}")
    print(f"\nTotal time {time.perf_counter() - started:.0f}s")
    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
