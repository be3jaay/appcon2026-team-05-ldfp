"""Process-wide pacing for LLM calls so live sessions stay under the provider's
requests-per-minute quota instead of bursting into 429s."""

import asyncio
import time


class RateLimiter:
    def __init__(self, rpm: float, clock=time.monotonic):
        self.interval = 60.0 / rpm if rpm and rpm > 0 else 0.0
        self._clock = clock
        self._next = 0.0

    async def acquire(self) -> float:
        """Wait for the next free slot. Returns the seconds waited.
        The slot is reserved before sleeping, so concurrent callers queue up in order."""
        now = self._clock()
        start = max(now, self._next)
        self._next = start + self.interval
        wait = start - now
        if wait > 0:
            await asyncio.sleep(wait)
        return wait

    def penalize(self, seconds: float) -> None:
        """The provider asked us to back off: nobody calls again for `seconds`."""
        self._next = max(self._next, self._clock() + seconds)
