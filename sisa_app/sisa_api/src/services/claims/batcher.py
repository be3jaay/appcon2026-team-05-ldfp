"""Groups kept segments so the classifier makes one LLM call per batch.

A batch is flushed on the FIRST of:
  - speaker change (the buffered batch is flushed before the new speaker's segment),
  - `max_segments` buffered,
  - `max_wait_s` since the first buffered segment (a timer, not the next message),
  - an explicit `flush()` / `stop()`.

`on_flush` runs under the batcher lock, so batches are delivered strictly in
order and a segment is never delivered twice or dropped. Keep `on_flush` fast
(the detector just enqueues the batch).
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal

from ...models.claims import TranscriptSegment

FlushReason = Literal["speaker_change", "max_segments", "timeout", "flush", "stop"]
OnFlush = Callable[[list[TranscriptSegment], FlushReason], Awaitable[None]]


class SegmentBatcher:
    def __init__(
        self,
        on_flush: OnFlush,
        max_segments: int = 3,
        max_wait_s: float = 15.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        if max_segments < 1:
            raise ValueError("max_segments must be >= 1")
        self._on_flush = on_flush
        self.max_segments = max_segments
        self.max_wait_s = max_wait_s
        self._sleep = sleep
        self._buffer: list[TranscriptSegment] = []
        self._lock = asyncio.Lock()
        self._timer: asyncio.Task | None = None
        self._generation = 0  # bumps on every flush so a stale timer never flushes a newer batch

    @property
    def pending(self) -> int:
        return len(self._buffer)

    async def add(self, segment: TranscriptSegment) -> None:
        async with self._lock:
            if self._buffer and self._buffer[-1].speaker != segment.speaker:
                await self._flush_locked("speaker_change")
            self._buffer.append(segment)
            if len(self._buffer) == 1:
                self._start_timer()
            if len(self._buffer) >= self.max_segments:
                await self._flush_locked("max_segments")

    async def flush(self) -> None:
        async with self._lock:
            await self._flush_locked("flush")

    async def stop(self) -> None:
        async with self._lock:
            await self._flush_locked("stop")

    def cancel(self) -> list[TranscriptSegment]:
        """Stop the timer and discard the buffer without flushing (client went away)."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._generation += 1
        dropped, self._buffer = self._buffer, []
        return dropped

    def _start_timer(self) -> None:
        generation = self._generation
        self._timer = asyncio.create_task(self._timeout(generation))

    async def _timeout(self, generation: int) -> None:
        await self._sleep(self.max_wait_s)
        async with self._lock:
            if generation != self._generation:
                return
            self._timer = None  # we are the timer; don't cancel ourselves
            await self._flush_locked("timeout")

    async def _flush_locked(self, reason: FlushReason) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._generation += 1
        if not self._buffer:
            return
        batch, self._buffer = self._buffer, []
        await self._on_flush(batch, reason)
