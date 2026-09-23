import asyncio

import pytest

from src.services.claims.batcher import SegmentBatcher

from .conftest import seg


class Recorder:
    def __init__(self):
        self.batches: list[tuple[list[str], str]] = []

    async def __call__(self, batch, reason):
        self.batches.append(([s.segment_id for s in batch], reason))

    @property
    def ids(self) -> list[str]:
        return [i for batch, _ in self.batches for i in batch]


def make(max_segments=3, max_wait_s=60.0, **kw):
    rec = Recorder()
    return SegmentBatcher(rec, max_segments=max_segments, max_wait_s=max_wait_s, **kw), rec


async def test_flushes_at_max_segments():
    b, rec = make()
    for i in range(1, 4):
        await b.add(seg(i, "x"))
    assert rec.batches == [(["1", "2", "3"], "max_segments")]
    assert b.pending == 0


async def test_flushes_on_speaker_change_before_new_speaker():
    b, rec = make()
    await b.add(seg(1, "x", speaker="1"))
    await b.add(seg(2, "x", speaker="1"))
    await b.add(seg(3, "x", speaker="2"))
    assert rec.batches == [(["1", "2"], "speaker_change")]
    assert b.pending == 1
    await b.stop()
    assert rec.batches[-1] == (["3"], "stop")


async def test_flushes_after_timeout_without_new_message():
    b, rec = make(max_wait_s=0.05)
    await b.add(seg(1, "x"))
    await asyncio.sleep(0.15)
    assert rec.batches == [(["1"], "timeout")]
    assert b.pending == 0


async def test_timeout_counts_from_first_buffered_segment():
    b, rec = make(max_wait_s=0.1)
    await b.add(seg(1, "x"))
    await asyncio.sleep(0.06)
    await b.add(seg(2, "x"))  # must not restart the timer
    await asyncio.sleep(0.07)
    assert rec.batches == [(["1", "2"], "timeout")]


async def test_timeout_with_fake_clock():
    release = asyncio.Event()
    waits: list[float] = []

    async def fake_sleep(seconds):
        waits.append(seconds)
        await release.wait()

    b, rec = make(max_wait_s=15, sleep=fake_sleep)
    await b.add(seg(1, "x"))
    await asyncio.sleep(0)
    assert waits == [15] and rec.batches == []
    release.set()
    await asyncio.sleep(0.01)
    assert rec.batches == [(["1"], "timeout")]


async def test_stale_timer_does_not_flush_next_batch():
    b, rec = make(max_wait_s=0.05)
    await b.add(seg(1, "x"))
    await b.flush()
    await b.add(seg(2, "x"))  # new timer for this batch
    await asyncio.sleep(0.02)
    assert rec.batches == [(["1"], "flush")]
    await asyncio.sleep(0.08)
    assert rec.batches == [(["1"], "flush"), (["2"], "timeout")]


async def test_flushes_on_stop_and_explicit_flush():
    b, rec = make()
    await b.add(seg(1, "x"))
    await b.flush()
    await b.add(seg(2, "x"))
    await b.stop()
    assert rec.batches == [(["1"], "flush"), (["2"], "stop")]


async def test_empty_flush_is_a_noop():
    b, rec = make()
    await b.flush()
    await b.stop()
    assert rec.batches == []


async def test_cancel_discards_without_flushing():
    b, rec = make(max_wait_s=0.03)
    await b.add(seg(1, "x"))
    assert [s.segment_id for s in b.cancel()] == ["1"]
    await asyncio.sleep(0.06)
    assert rec.batches == []


@pytest.mark.parametrize("max_segments", [1, 2, 3, 5])
async def test_order_preserved_no_loss_no_duplicates(max_segments):
    b, rec = make(max_segments=max_segments, max_wait_s=0.02)
    speakers = "1112212333111"
    for i, spk in enumerate(speakers, start=1):
        await b.add(seg(i, "x", speaker=spk))
        if i % 4 == 0:
            await asyncio.sleep(0.04)  # let some timers fire mid-stream
    await b.stop()
    expected = [str(i) for i in range(1, len(speakers) + 1)]
    assert rec.ids == expected
    for batch, _ in rec.batches:
        assert 1 <= len(batch) <= max_segments
        assert len({speakers[int(i) - 1] for i in batch}) == 1  # one speaker per batch


def test_rejects_zero_max_segments():
    with pytest.raises(ValueError):
        SegmentBatcher(Recorder(), max_segments=0)
