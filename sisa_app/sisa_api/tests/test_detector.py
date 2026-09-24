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

    kw.setdefault("max_call_segments", 3)  # one call per batch unless a test opts into merging
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
    second = [line for line in llm.calls[1]["user"].splitlines() if not line.startswith("[E")]
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
    assert result.llm_errors == 1
    assert llm.call_count == 3


async def test_timeout_flush_emits_claims_mid_stream():
    llm = KeywordFakeLLM()
    emitted: list[dict] = []

    async def emit(m):
        emitted.append(m)

    detector = ClaimDetector(ClaimClassifier(llm), emit, max_segments=3, max_wait_s=0.05)
    await detector.add_segment(seg(1, "Ang COA ay nag-disallow ng ₱73 milyon noong 2022."))
    await asyncio.sleep(0.15)
    assert [m["type"] for m in emitted] == ["checking", "claims"]
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


# --- merging, pacing and retries (the fix for "one call per speaker turn") ---

HEARING = [
    ("1", "Paragraph 4, Your Honor, please. Uh, witness."),
    ("2", "Intelligence and confidential activities by their very nature are highly sensitive operations."),
    ("1", "Uh, can you continue with paragraph 5, Celine? Silene?"),
    ("2", "Requiring receipts for safe house rentals may create a leak that endangers the agents."),
    ("1", "So, uh, paragraph 6. Sorry. Medyo magbabasa ka, no? Paragraph 6."),
    ("2", "In many instances it is impractical and sometimes impossible to obtain such receipts."),
]


async def test_alternating_speakers_are_merged_into_few_calls():
    # Every line is a speaker change, so every batch has 1 segment. While the
    # worker waits for its rate-limit slot, queued batches ride along in one call.
    from src.services.claims.rate_limiter import RateLimiter

    llm = KeywordFakeLLM()
    detector = ClaimDetector(
        ClaimClassifier(llm), max_segments=3, max_wait_s=60, max_call_segments=8, rate_limiter=RateLimiter(rpm=600)
    )
    result = await detector.process([seg(i, t, speaker=s) for i, (s, t) in enumerate(HEARING, start=1)])
    assert llm.call_count == 1
    assert result.llm_calls == 1
    sent = [line for line in llm.calls[0]["user"].splitlines() if not line.startswith("[C")]
    assert len(sent) >= 3  # the testimony lines, from different batches, in one call


async def test_merge_respects_max_call_segments():
    llm = KeywordFakeLLM()
    detector = ClaimDetector(ClaimClassifier(llm), max_segments=1, max_wait_s=60, max_call_segments=2)
    segs = [seg(i, f"Ang DepEd ay gumastos ng ₱{i}00 milyon noong 2023.", speaker=str(i % 2)) for i in range(1, 8)]
    await detector.process(segs)
    for call in llm.calls:
        numbered = [line for line in call["user"].splitlines() if not line.startswith(("[C", "[E"))]
        assert len(numbered) <= 2
    assert llm.call_count == 4  # 7 segments / 2 per call


async def test_retryable_error_is_retried_then_succeeds():
    from src.services.claims.classifier import RetryableLLMError

    ok = '{"claims": [{"segment": 1, "text": "x", "type": "fact"}]}'
    llm = FakeLLM(RetryableLLMError("429 RESOURCE_EXHAUSTED", retry_after=0.01), ok)
    emitted: list[dict] = []

    async def emit(m):
        emitted.append(m)

    detector = ClaimDetector(ClaimClassifier(llm), emit, max_attempts=3)
    result = await detector.process([seg(1, "Ang DepEd ay gumastos ng ₱112 milyon noong 2023.")])
    assert llm.call_count == 2
    assert result.llm_errors == 0 and len(result.claims) == 1
    assert [m["type"] for m in emitted] == ["checking", "claims"]


async def test_retries_give_up_after_max_attempts():
    from src.services.claims.classifier import RetryableLLMError

    llm = FakeLLM(RetryableLLMError("503 UNAVAILABLE", retry_after=0.01))
    detector = ClaimDetector(ClaimClassifier(llm), max_attempts=2)
    result = await detector.process([seg(1, "Ang DepEd ay gumastos ng ₱112 milyon noong 2023.")])
    assert llm.call_count == 2
    assert result.llm_errors == 1


async def test_non_retryable_error_is_not_retried():
    llm = FakeLLM(ValueError("bad request"))
    detector = ClaimDetector(ClaimClassifier(llm), max_attempts=3)
    result = await detector.process([seg(1, "Ang DepEd ay gumastos ng ₱112 milyon noong 2023.")])
    assert llm.call_count == 1 and result.llm_errors == 1


async def test_checking_message_lists_segments_before_claims():
    emitted: list[dict] = []

    async def emit(m):
        emitted.append(m)

    detector = ClaimDetector(ClaimClassifier(KeywordFakeLLM()), emit, max_segments=3)
    await detector.process([seg(1, "Ang COA ay nag-disallow ng ₱73 milyon noong 2022.")])
    assert emitted[0] == {"type": "checking", "segment_ids": ["1"]}
    assert emitted[1]["type"] == "claims"


def test_detector_logs_each_step(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="src.services.claims.detector")
    asyncio.run(
        ClaimDetector(ClaimClassifier(KeywordFakeLLM()), session="t1").process(
            [seg(1, "Objection, Your Honor."), seg(2, "Ang COA ay nag-disallow ng ₱73 milyon noong 2022.")]
        )
    )
    text = caplog.text
    for expected in ("[claims t1] segment 1", "DROP", "KEEP", "batch ready", "LLM call 1", "LLM ok", "stop:"):
        assert expected in text, expected


async def test_overload_backs_off_exponentially_but_explicit_delay_does_not():
    from src.services.claims.classifier import RetryableLLMError

    ok = '{"claims": []}'
    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)

    overload = RetryableLLMError("503", retry_after=5, exponential=True)
    llm = FakeLLM(overload, overload, overload, ok)
    detector = ClaimDetector(ClaimClassifier(llm), max_attempts=4, sleep=fake_sleep)
    await detector.process([seg(1, "Ang DepEd ay gumastos ng ₱112 milyon noong 2023.")])
    assert slept == [5, 10, 20]

    slept.clear()
    quota = RetryableLLMError("429", retry_after=38)
    detector = ClaimDetector(ClaimClassifier(FakeLLM(quota, quota, ok)), max_attempts=4, sleep=fake_sleep)
    await detector.process([seg(1, "Ang DepEd ay gumastos ng ₱112 milyon noong 2023.")])
    assert slept == [38, 38]


async def test_earlier_assertions_are_sent_but_never_extracted():
    llm = KeywordFakeLLM()
    detector = ClaimDetector(ClaimClassifier(llm), max_segments=1, max_wait_s=60, max_call_segments=1)
    await detector.process([
        seg(1, "Ang DepEd ay gumastos ng ₱100 milyon noong 2023.", speaker="1"),
        seg(2, "Ang DepEd ay gumastos ng ₱300 milyon noong 2023.", speaker="2"),
    ])
    first, second = (call["user"].splitlines() for call in llm.calls)
    assert not any(line.startswith("[E") for line in first)
    earlier = [line for line in second if line.startswith("[E")]
    assert len(earlier) == 1 and "₱100 milyon" in earlier[0] and "Speaker 1" in earlier[0]
