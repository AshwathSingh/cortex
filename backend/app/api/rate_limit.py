"""Per-client-IP rate limiting for unauthenticated endpoints.

Sliding window held in this process's memory. That is enough for one uvicorn
worker; with several workers or hosts each keeps its own count, so the effective
limit multiplies -- move the counters to a shared store (e.g. Redis) before
scaling out.

The client IP is ``request.client.host``. Behind a proxy (the Next.js /api
rewrite, a load balancer) that is the proxy's address unless uvicorn trusts its
X-Forwarded-For: run with ``--proxy-headers --forwarded-allow-ips=<proxy ip>``.
Uvicorn already trusts 127.0.0.1 by default, which covers local development.
"""

import math
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request, status

# Past this many tracked clients, idle ones are swept so memory stays bounded.
_SWEEP_THRESHOLD = 10_000


class RateLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float = 60,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def __call__(self, request: Request) -> None:
        """FastAPI dependency: raises 429 once the caller exceeds the limit."""
        key = request.client.host if request.client else "unknown"
        now = self._clock()
        cutoff = now - self.window

        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= self.limit:
                retry_after = max(1, math.ceil(hits[0] + self.window - now))
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many sign-in attempts. Please wait and try again.",
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)

            if len(self._hits) > _SWEEP_THRESHOLD:
                self._hits = {
                    k: v for k, v in self._hits.items() if v and v[-1] > cutoff
                }

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
