"""Token-bucket rate limiter for NCBI E-utilities (10 RPS with API key)."""
from __future__ import annotations

import asyncio
import time


class TokenBucket:
    """Simple token bucket. 1 acquire == 1 NCBI request slot.

    Usage:
        bucket = TokenBucket(rate=10.0, capacity=10)
        await bucket.acquire()  # blocks until a token is free
        # ... make NCBI call
    """

    def __init__(self, rate: float = 10.0, capacity: int = 10) -> None:
        self.rate = rate
        self.capacity = capacity
        self._tokens: float = capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, n: int = 1) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                self._last_refill = now
                if self._tokens >= n:
                    self._tokens -= n
                    return
                # Wait just long enough to refill the deficit
                deficit = n - self._tokens
                wait = deficit / self.rate
                await asyncio.sleep(wait)
