"""Single entry point for claim detection: prefilter -> batcher -> classifier.

Mic and video both reach this through the claims websocket; offline callers
(eval script, tests) use `process()`. One detector per transcript stream.
"""

import asyncio
import logging
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from ...models.claims import DetectionResult, SkippedSegment, TranscriptSegment
from .batcher import FlushReason, SegmentBatcher
from .classifier import ClaimClassifier, ClassifierError
from .prefilter import prefilter

logger = logging.getLogger(__name__)

Emit = Callable[[dict[str, Any]], Awaitable[None]]

_HISTORY_SIZE = 64


async def _no_emit(_: dict[str, Any]) -> None:
    return None


class ClaimDetector:
    def __init__(
        self,
        classifier: ClaimClassifier,
        emit: Emit | None = None,
        *,
        max_segments: int = 3,
        max_wait_s: float = 15.0,
        context_size: int = 2,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.classifier = classifier
        self._emit = emit or _no_emit
        self.context_size = context_size
        self.batcher = SegmentBatcher(self._enqueue, max_segments=max_segments, max_wait_s=max_wait_s, sleep=sleep)
        self.result = DetectionResult()
        # Every final segment (kept or dropped), so context lines are the real previous lines.
        self._history: deque[TranscriptSegment] = deque(maxlen=_HISTORY_SIZE)
        self._queue: asyncio.Queue[tuple[list[TranscriptSegment], list[TranscriptSegment]]] = asyncio.Queue()
        self._worker: asyncio.Task | None = None

    async def add_segment(self, segment: TranscriptSegment) -> None:
        self._history.append(segment)
        keep, reason = prefilter(segment.text)
        if not keep:
            skipped = SkippedSegment(segment_id=segment.segment_id, reason=reason)
            self.result.skipped.append(skipped)
            await self._safe_emit({"type": "skipped", **skipped.model_dump()})
            return
        await self.batcher.add(segment)

    async def flush(self) -> None:
        await self.batcher.flush()
        await self._queue.join()

    async def stop(self) -> DetectionResult:
        await self.batcher.stop()
        await self._queue.join()
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None
        self.result.llm_calls = self.classifier.calls
        return self.result

    def abort(self) -> None:
        """Drop pending work without spending LLM calls (e.g. the websocket closed)."""
        self.batcher.cancel()
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None

    async def process(self, segments: Iterable[TranscriptSegment]) -> DetectionResult:
        for segment in segments:
            await self.add_segment(segment)
        return await self.stop()

    def _context_for(self, batch: list[TranscriptSegment]) -> list[TranscriptSegment]:
        if self.context_size <= 0:
            return []
        history = list(self._history)
        first_id = batch[0].segment_id
        for i, seg in enumerate(history):
            if seg.segment_id == first_id:
                return history[max(0, i - self.context_size) : i]
        return []

    async def _enqueue(self, batch: list[TranscriptSegment], reason: FlushReason) -> None:
        logger.debug("flushing %d segment(s): %s", len(batch), reason)
        if self._worker is None:
            self._worker = asyncio.create_task(self._run_worker())
        # Snapshot context now; history keeps moving while the LLM call is pending.
        self._queue.put_nowait((batch, self._context_for(batch)))

    async def _run_worker(self) -> None:
        while True:
            batch, context = await self._queue.get()
            try:
                claims = await self.classifier.classify(batch, context)
                self.result.claims.extend(claims)
                await self._safe_emit(
                    {
                        "type": "claims",
                        "segment_ids": [s.segment_id for s in batch],
                        "claims": [c.model_dump() for c in claims],
                    }
                )
            except ClassifierError as exc:
                logger.warning("claim classification failed: %s", exc)
                await self._safe_emit(
                    {
                        "type": "error",
                        "message": "Claim classification failed for this batch.",
                        "segment_ids": [s.segment_id for s in batch],
                    }
                )
            except Exception:
                logger.exception("unexpected error in claim worker")
            finally:
                self._queue.task_done()

    async def _safe_emit(self, message: dict[str, Any]) -> None:
        try:
            await self._emit(message)
        except Exception as exc:  # client went away; keep detecting for the result
            logger.info("could not emit %s message: %s", message.get("type"), exc)

