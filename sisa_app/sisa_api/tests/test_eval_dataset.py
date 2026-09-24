"""The eval dataset is edited by hand; keep it well-formed. No LLM involved."""

import json
from collections import Counter
from pathlib import Path

from src.models.claims import CLAIM_TYPES
from src.services.claims.prefilter import prefilter

DATA = Path(__file__).resolve().parents[1] / "data" / "eval" / "claim_detection.json"
CASES = json.loads(DATA.read_text(encoding="utf-8"))["cases"]


def test_dataset_size_and_type_coverage():
    assert len(CASES) >= 30
    counts = Counter(e["type"] for c in CASES for e in c["expected"])
    for t in CLAIM_TYPES:
        assert counts[t] >= 3, f"need at least 3 '{t}' cases, have {counts[t]}"


def test_cases_are_well_formed():
    ids = [c["id"] for c in CASES]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    for c in CASES:
        assert c["text"].strip()
        assert isinstance(c["needs_context"], bool)
        if c["needs_context"]:
            assert c["context"], f"{c['id']} needs context but has none"
        for e in c["expected"]:
            assert e["type"] in CLAIM_TYPES, c["id"]
            assert set(e.get("also_ok", [])) <= set(CLAIM_TYPES), c["id"]


def test_prefilter_never_drops_a_labelled_claim():
    dropped = [c["id"] for c in CASES if c["expected"] and not prefilter(c["text"])[0]]
    assert dropped == []


def test_prefilter_drops_the_no_claim_cases():
    kept = [c["id"] for c in CASES if not c["expected"] and prefilter(c["text"])[0]]
    assert kept == []
