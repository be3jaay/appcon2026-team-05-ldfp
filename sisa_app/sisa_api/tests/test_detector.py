"""End to end: prefilter -> batcher -> classifier, with a keyword fake LLM (no network)."""

import asyncio

import pytest

from src.services.claims.classifier import ClaimClassifier
from src.services.claims.detector import ClaimDetector

from .conftest import FakeLLM, KeywordFakeLLM, seg

# A scripted Taglish hearing. (id, speaker, text, expected: None = skipped, else claim type)
SESSION = [
    (1, "1", "Magandang hapon po sa inyong lahat.", None),
    (2, "1", "Objection, Your Honor.", None),
    (3, "2", "Ang ₱125 milyon na confidential funds ay naubos sa loob ng 11 araw.", "fact"),
    (4, "2", "Ayon sa Article XI ng Konstitusyon, dapat agad simulan ang trial.", "legal"),
    (5, "2", "Sa totoo lang, nakakahiya at pangit ang ganitong pamamalakad.", "opinion"),
    (6, "3", "Noted. Proceed.", None),
    (7, "3", "Itatayo namin ang limampung bagong classroom bago matapos ang taon.", "promise"),
    (8, "3", "Wow, ang galing naman ng liquidation ninyo, very transparent talaga.", "sarcasm"),
    (9, "3", "Parang kinain ng buwaya ang pondo ng mga estudyante.", "figurative"),
    (10, "1", "Marami raw ang nawala sa pondo pero hindi natin alam kung magkano.", "vague"),
    (11, "1", "Salamat po.", None),
    (12, "1", "Ang DepEd ay gumastos ng ₱112 milyon noong 2023.", "fact"),
]


def session_segments():
    return [seg(i, text, speaker=spk) for i, spk, text, _ in SESSION]


async def run_session(llm=None, **kw):
    llm = llm or KeywordFakeLLM()
    emitted: list[dict] = []

    async def emit(message):
        emitted.append(message)

    detector = ClaimDetector(ClaimClassifier(llm), emit, max_segments=3, max_wait_s=60, context_size=2, **kw)
    result = await detector.process(session_segments())
    return result, emitted, llm


async def test_procedural_and_greeting_lines_are_skipped_with_reasons():
    result, emitted, _ = await run_session()
    expected_skips = {str(i) for i, _, _, exp in SESSION if exp is None}
    assert {s.segment_id for s in result.skipped} == expected_skips
    assert all(s.reason for s in result.skipped)
    skipped_msgs = [m for m in emitted if m["type"] == "skipped"]
    assert {m["segment_id"] for m in skipped_msgs} == expected_skips


async def test_claims_come_out_with_expected_types():
    result, _, _ = await run_session()
    got = {c.segment_id: c.type for c in result.claims}
    expected = {str(i): exp for i, _, _, exp in SESSION if exp is not None}
    assert got == expected
    for claim in result.claims:
        original = next(s for s in SESSION if str(s[0]) == claim.segment_id)
        assert claim.speaker == original[1]
        assert claim.timestamp == original[0] * 1000


async def test_llm_calls_far_below_segment_count():
    result, emitted, llm = await run_session()
    # 12 segments, 8 kept, grouped by speaker into [3,4,5] [7,8,9] [10,12].
    assert llm.call_count == 3
    assert result.llm_calls == 3
    assert llm.call_count * 3 <= len(SESSION)
    assert len([m for m in emitted if m["type"] == "claims"]) == 3


async def test_context_is_the_two_previous_final_lines_and_never_labelled():
    _, _, llm = await run_session()
    second = llm.calls[1]["user"].splitlines()
    assert second[0].startswith("[C1]") and "nakakahiya" in second[0]
    assert second[1].startswith("[C2]") and "Noted. Proceed." in second[1]
    assert second[2].startswith("[1] Speaker 3: Itatayo")


async def test_mic_and_video_use_the_same_path():
    # Sources are indistinguishable to the detector: same segments -> same claims.
    a, _, _ = await run_session()
    b, _, _ = await run_session()
    assert [c.model_dump() for c in a.claims] == [c.model_dump() for c in b.claims]


async def test_llm_failure_emits_error_and_session_continues():
    llm = FakeLLM(TimeoutError("gemini down"), '{"claims": [{"segment": 1, "text": "x", "type": "fact"}]}')
    result, emitted, _ = await run_session(llm=llm)
    errors = [m for m in emitted if m["type"] == "error"]
    assert len(errors) == 1 and errors[0]["segment_ids"] == ["3", "4", "5"]
    assert len(result.claims) == 2  # later batches still classified
    assert llm.call_count == 3


async def test_timeout_flush_emits_claims_mid_stream():
    llm = KeywordFakeLLM()
    emitted: list[dict] = []

    async def emit(m):
        emitted.append(m)

    detector = ClaimDetector(ClaimClassifier(llm), emit, max_segments=3, max_wait_s=0.05)
    await detector.add_segment(seg(1, "Ang COA ay nag-disallow ng ₱73 milyon noong 2022."))
    await asyncio.sleep(0.15)
    assert [m["type"] for m in emitted] == ["claims"]
    await detector.stop()
    assert llm.call_count == 1


async def test_abort_spends_no_llm_calls():
    llm = KeywordFakeLLM()
    detector = ClaimDetector(ClaimClassifier(llm), max_segments=3, max_wait_s=60)
    await detector.add_segment(seg(1, "Ang DepEd ay gumastos ng ₱112 milyon noong 2023."))
    detector.abort()
    assert llm.call_count == 0


@pytest.mark.parametrize("max_segments", [1, 3, 5])
async def test_every_kept_segment_is_classified_exactly_once(max_segments):
    llm = KeywordFakeLLM()
    detector = ClaimDetector(ClaimClassifier(llm), max_segments=max_segments, max_wait_s=60)
    await detector.process(session_segments())
    sent = [line for call in llm.calls for line in call["user"].splitlines() if not line.startswith("[C")]
    kept_texts = [text for _, _, text, exp in SESSION if exp is not None]
    assert [line.split(": ", 1)[1] for line in sent] == kept_texts
