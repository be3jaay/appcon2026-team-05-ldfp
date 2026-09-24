"""Evaluate claim detection against the REAL LLM provider chain (not part of CI).

    cd sisa_api
    uv run python scripts/eval_claim_detection.py                 # stream mode (realistic batching)
    uv run python scripts/eval_claim_detection.py --mode isolated # one detector per case
    uv run python scripts/eval_claim_detection.py --file other.json

Stream mode feeds every case (context lines first) through one detector, so
batches mix neighbouring cases like a live session does. Only claims on a
case's own line are scored; claims on its context lines are ignored.
"""

import argparse
import logging
import asyncio
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import settings  # noqa: E402
from src.models.claims import CLAIM_TYPES, Claim, TranscriptSegment  # noqa: E402
from src.services.claims.classifier import ClaimClassifier, LLMClient  # noqa: E402
from src.services.claims.detector import ClaimDetector  # noqa: E402
from src.services.claims.rate_limiter import RateLimiter  # noqa: E402

LLM_NAME = "?"
DEFAULT_FILE = ROOT / "data" / "eval" / "claim_detection.json"
NONE = "none"


def load_cases(path: Path) -> list[dict]:
    cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
    for case in cases:
        case.setdefault("speaker", "1")
        case["context"] = [
            c if isinstance(c, dict) else {"speaker": case["speaker"], "text": c} for c in case.get("context", [])
        ]
    return cases


def case_segments(case: dict, clock: list[int]) -> list[TranscriptSegment]:
    segments = []
    for i, ctx in enumerate(case["context"]):
        segments.append(_segment(f"{case['id']}#ctx{i}", ctx["text"], ctx.get("speaker", "1"), clock))
    segments.append(_segment(case["id"], case["text"], case["speaker"], clock))
    return segments


def _segment(segment_id: str, text: str, speaker: str, clock: list[int]) -> TranscriptSegment:
    clock[0] += 4000
    return TranscriptSegment(segment_id=segment_id, text=text, speaker=speaker, start_ms=clock[0], end_ms=clock[0] + 3500)


def make_llm() -> LLMClient:
    from src.clients.llm_chain import build_llm_client

    return build_llm_client()


def make_detector(llm: LLMClient, limiter: RateLimiter) -> ClaimDetector:
    return ClaimDetector(
        ClaimClassifier(llm),
        max_segments=settings.claims_batch_max_segments,
        max_wait_s=3600,  # offline: batches close on size/speaker/stop, not wall time
        context_size=settings.claims_context_segments,
        max_call_segments=settings.claims_batch_max_segments,  # score batches as configured
        max_attempts=settings.claims_llm_max_attempts,
        rate_limiter=limiter,
    )


async def run(cases: list[dict], mode: str, rpm: float) -> tuple[list[Claim], set[str], int, int, int]:
    clock = [0]
    claims: list[Claim] = []
    skipped: set[str] = set()
    calls = segments = errors = 0
    groups = [cases] if mode == "stream" else [[c] for c in cases]
    llm, limiter = make_llm(), RateLimiter(rpm)
    for group in groups:
        detector = make_detector(llm, limiter)
        segs = [s for case in group for s in case_segments(case, clock)]
        result = await detector.process(segs)
        claims += result.claims
        skipped |= {s.segment_id for s in result.skipped}
        calls += result.llm_calls
        errors += result.llm_errors
        segments += len(segs)
    return claims, skipped, calls, segments, errors


def score(cases: list[dict], claims: list[Claim]):
    by_segment: dict[str, list[Claim]] = defaultdict(list)
    for c in claims:
        by_segment[c.segment_id].append(c)

    confusion: Counter[tuple[str, str]] = Counter()
    hits: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    misses: list[dict] = []
    literal = {"expected": 0, "filled": 0}

    for case in cases:
        predicted = list(by_segment.get(case["id"], []))
        expected = case["expected"]
        unmatched_expected = []
        for exp in expected:
            ok_types = {exp["type"], *exp.get("also_ok", [])}
            totals[exp["type"]] += 1
            match = next((p for p in predicted if p.type in ok_types), None)
            if match:
                predicted.remove(match)
                hits[exp["type"]] += 1
                confusion[(exp["type"], exp["type"])] += 1
                if exp.get("literal_claim"):
                    literal["expected"] += 1
                    literal["filled"] += bool(match.literal_claim)
            else:
                unmatched_expected.append(exp)
        # pair what's left in order: those are confusions; leftovers are misses/extras
        for exp in unmatched_expected:
            got = predicted.pop(0).type if predicted else NONE
            confusion[(exp["type"], got)] += 1
            misses.append({"case": case, "expected": exp["type"], "got": got})
        if not expected:
            totals[NONE] += 1
            if predicted:
                for p in predicted:
                    confusion[(NONE, p.type)] += 1
                misses.append({"case": case, "expected": NONE, "got": ", ".join(p.type for p in predicted)})
            else:
                hits[NONE] += 1
                confusion[(NONE, NONE)] += 1
        else:
            for p in predicted:  # extra claims on a case that had expectations
                confusion[(NONE, p.type)] += 1
                misses.append({"case": case, "expected": "(no more claims)", "got": p.type})
    return hits, totals, confusion, misses, literal


def print_report(cases, claims, skipped, calls, segments, errors, mode):
    hits, totals, confusion, misses, literal = score(cases, claims)
    labels = [*CLAIM_TYPES, NONE]

    print(f"\n=== Claim detection eval  llm={LLM_NAME}  mode={mode}  cases={len(cases)} ===\n")
    print("Accuracy per expected type")
    for t in labels:
        if totals[t]:
            print(f"  {t:<11} {hits[t]:>3}/{totals[t]:<3} {hits[t] / totals[t]:6.1%}")
    all_hits, all_total = sum(hits.values()), sum(totals.values())
    print(f"  {'overall':<11} {all_hits:>3}/{all_total:<3} {all_hits / all_total:6.1%}")

    print("\nConfusion matrix (rows = expected, cols = got)")
    width = 7
    print(" " * 12 + "".join(f"{t[:width]:>{width + 1}}" for t in labels))
    for row in labels:
        if not any(confusion[(row, col)] for col in labels):
            continue
        print(f"  {row:<10}" + "".join(f"{confusion[(row, col)] or '.':>{width + 1}}" for col in labels))

    print(f"\nMisses ({len(misses)})")
    for m in misses:
        case = m["case"]
        flag = " [needs context]" if case.get("needs_context") else ""
        dropped = " [dropped by prefilter]" if case["id"] in skipped else ""
        print(f"  - {case['id']}: expected {m['expected']}, got {m['got']}{flag}{dropped}")
        print(f"      {case['text']}")

    case_ids = {c["id"] for c in cases}
    claim_cases = {c["id"] for c in cases if c["expected"]}
    print("\nPrefilter")
    print(f"  drop rate (all segments incl. context): {len(skipped)}/{segments} = {len(skipped) / segments:.1%}")
    print(f"  dropped no-claim cases:  {len((case_ids - claim_cases) & skipped)}/{len(case_ids - claim_cases)}")
    print(f"  dropped CLAIM cases (bad): {len(claim_cases & skipped)}/{len(claim_cases)}")

    if literal["expected"]:
        print(f"\nliteral_claim filled on matched figurative/sarcasm: {literal['filled']}/{literal['expected']}")
    print(f"\nLLM calls: {calls} for {segments} segments = {100 * calls / segments:.1f} per 100 segments")
    if errors:
        print(f"WARNING: {errors} LLM call(s) FAILED (see log above); their segments are scored as missed.")
    print()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # ₱ and Tagalog text on Windows consoles
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--mode", choices=["stream", "isolated"], default="stream")
    parser.add_argument("--rpm", type=float, default=settings.llm_rpm, help="max LLM requests per minute")
    parser.add_argument(
        "--providers", help="provider chain to evaluate, e.g. 'groq' or 'gemini' (default: LLM_PROVIDERS)"
    )
    args = parser.parse_args()

    if args.providers:
        settings.llm_providers = [p.strip().lower() for p in args.providers.split(",") if p.strip()]
    if not settings.llm_providers:
        print("No LLM API key is set: skipping the claim detection eval (it calls a real LLM).")
        print("Add GROQ_API_KEY (or GEMINI_API_KEY, ...) to sisa_api/.env and run again.")
        return 0
    global LLM_NAME
    LLM_NAME = " > ".join(settings.llm_providers)

    cases = load_cases(args.file)
    print(f"Running {len(cases)} cases against {LLM_NAME} at <= {args.rpm:g} requests/min...")
    print_report(cases, *asyncio.run(run(cases, args.mode, args.rpm)), args.mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
