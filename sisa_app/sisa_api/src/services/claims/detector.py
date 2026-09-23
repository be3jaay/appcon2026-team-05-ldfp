"""Single entry point for claim detection: prefilter -> batcher -> classifier.

Mic and video both reach this through the claims websocket; offline callers
(eval script, tests) use `process()`. One detector per transcript stream.

LLM calls are made by one worker per detector:
- batches that queue up while a call is pending or rate-limited are MERGED
  into the next call (up to `max_call_segments`), so a fast back-and-forth
  between speakers does not turn into one call per turn;
- an optional shared `RateLimiter` paces calls across all sessions;
- transient failures (429/503) are retried after the provider's retry delay.
"""

import asyncio
import logging
import time
import uuid
from collections import Counter, deque
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from ...models.claims import DetectionResult, SkippedSegment, TranscriptSegment
from .batcher import FlushReason, SegmentBatcher
from .classifier import ClaimClassifier, ClassifierError
from .prefilter import prefilter
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

Emit = Callable[[dict[str, Any]], Awaitable[None]]
Batch = tuple[list[TranscriptSegment], list[TranscriptSegment]]  # (segments, context)

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
        max_call_segments: int = 8,
        max_attempts: int = 3,
        rate_limiter: RateLimiter | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        session: str | None = None,
    ):
        self.classifier = classifier
        self._emit = emit or _no_emit
        self.context_size = context_size
        self.max_call_segments = max(max_call_segments, max_segments)
        self.max_attempts = max(1, max_attempts)
        self.rate_limiter = rate_limiter
        self._sleep = sleep
        self.session = session or uuid.uuid4().hex[:6]
        self.batcher = SegmentBatcher(self._enqueue, max_segments=max_segments, max_wait_s=max_wait_s, sleep=sleep)
        self.result = DetectionResult()
        # Every final segment (kept or dropped), so context lines are the real previous lines.
        self._history: deque[TranscriptSegment] = deque(maxlen=_HISTORY_SIZE)
        self._queue: asyncio.Queue[Batch] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._segments_seen = 0

    def _log(self, level: int, msg: str, *args: Any) -> None:
        logger.log(level, "[claims %s] " + msg, self.session, *args)

    async def add_segment(self, segment: TranscriptSegment) -> None:
        self._segments_seen += 1
        self._history.append(segment)
        keep, reason = prefilter(segment.text)
        self._log(
            logging.INFO,
            "segment %s spk=%s words=%d %s (%s): %.80s",
            segment.segment_id,
            segment.speaker,
            len(segment.text.split()),
            "KEEP" if keep else "DROP",
            reason,
            segment.text.strip(),
        )
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
        self._log(
            logging.INFO,
            "stop: %d segments, %d skipped, %d LLM calls (%d batches failed), %d claims %s",
            self._segments_seen,
            len(self.result.skipped),
            self.result.llm_calls,
            self.result.llm_errors,
            len(self.result.claims),
            dict(Counter(c.type for c in self.result.claims)),
        )
        return self.result

    def abort(self) -> None:
        """Drop pending work without spending LLM calls (e.g. the websocket closed)."""
        dropped = self.batcher.cancel()
        if self._worker is not None:
            self._worker.cancel()
            self._worker = None
        self._log(logging.INFO, "aborted: %d buffered segments, %d queued batches discarded", len(dropped), self._queue.qsize())

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
        self._log(logging.INFO, "batch ready (%s): segments %s", reason, [s.segment_id for s in batch])
        if self._worker is None:
            self._worker = asyncio.create_task(self._run_worker())
        # Snapshot context now; history keeps moving while the LLM call is pending.
        self._queue.put_nowait((batch, self._context_for(batch)))

    def _take_merged(self, first: Batch) -> tuple[list[TranscriptSegment], list[TranscriptSegment], int]:
        """Merge queued batches into `first` while they fit in one call."""
        segments, context = list(first[0]), first[1]
        taken = 1
        while not self._queue.empty():
            peek = self._queue._queue[0]  # asyncio.Queue has no public peek
            if len(segments) + len(peek[0]) > self.max_call_segments:
                break
            segments += self._queue.get_nowait()[0]
            taken += 1
        return segments, context, taken

    async def _run_worker(self) -> None:
        while True:
            first = await self._queue.get()
            if self.rate_limiter is not None:
                # Wait for our slot *before* merging, so batches that arrive meanwhile ride along.
                waited = await self.rate_limiter.acquire()
                if waited > 0.05:
                    self._log(logging.INFO, "rate limit: waited %.1fs for a call slot", waited)
            segments, context, taken = self._take_merged(first)
            try:
                await self._classify_with_retry(segments, context, merged=taken)
            except Exception:
                logger.exception("[claims %s] unexpected error in claim worker", self.session)
            finally:
                for _ in range(taken):
                    self._queue.task_done()

    async def _classify_with_retry(
        self, segments: list[TranscriptSegment], context: list[TranscriptSegment], merged: int
    ) -> None:
        ids = [s.segment_id for s in segments]
        await self._safe_emit({"type": "checking", "segment_ids": ids})
        for attempt in range(1, self.max_attempts + 1):
            if attempt > 1 and self.rate_limiter is not None:
                await self.rate_limiter.acquire()
            self._log(
                logging.INFO,
                "LLM call %d (attempt %d/%d): %d segments from %d batch(es) %s + %d context lines",
                self.classifier.calls + 1,
                attempt,
                self.max_attempts,
                len(segments),
                merged,
                ids,
                len(context),
            )
            started = time.perf_counter()
            try:
                claims = await self.classifier.classify(segments, context)
            except ClassifierError as exc:
                if exc.retry_after is not None and attempt < self.max_attempts:
                    delay = exc.retry_after * (2 ** (attempt - 1) if exc.exponential else 1)
                    self._log(logging.WARNING, "%s; retrying in %.1fs", exc, delay)
                    if self.rate_limiter is not None:
                        self.rate_limiter.penalize(delay)
                    else:
                        await self._sleep(delay)
                    continue
                self.result.llm_errors += 1
                self._log(logging.WARNING, "giving up on segments %s: %s", ids, exc)
                await self._safe_emit(
                    {"type": "error", "message": "Claim classification failed for this batch.", "segment_ids": ids}
                )
                return
            self.result.claims.extend(claims)
            self._log(
                logging.INFO,
                "LLM ok in %.1fs: %d claims %s",
                time.perf_counter() - started,
                len(claims),
                dict(Counter(c.type for c in claims)),
            )
            await self._safe_emit({"type": "claims", "segment_ids": ids, "claims": [c.model_dump() for c in claims]})
            return

    async def _safe_emit(self, message: dict[str, Any]) -> None:
        try:
            await self._emit(message)
        except Exception as exc:  # client went away; keep detecting for the result
            self._log(logging.INFO, "could not emit %s message: %s", message.get("type"), exc)
