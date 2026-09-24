from src.services.claims.rate_limiter import RateLimiter


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


async def test_spaces_calls_by_interval(monkeypatch):
    slept: list[float] = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr("src.services.claims.rate_limiter.asyncio.sleep", fake_sleep)
    clock = Clock()
    limiter = RateLimiter(rpm=6, clock=clock)  # one call per 10 s
    assert await limiter.acquire() == 0
    assert await limiter.acquire() == 10
    assert await limiter.acquire() == 20  # reserved in order, even before the first sleep ends
    assert slept == [10, 20]


async def test_penalize_pushes_next_slot():
    clock = Clock()
    limiter = RateLimiter(rpm=0, clock=clock)  # unlimited
    assert await limiter.acquire() == 0
    limiter.penalize(0.02)
    waited = await limiter.acquire()
    assert 0.019 <= waited <= 0.021


async def test_unlimited_never_waits():
    limiter = RateLimiter(rpm=0)
    for _ in range(5):
        assert await limiter.acquire() == 0
