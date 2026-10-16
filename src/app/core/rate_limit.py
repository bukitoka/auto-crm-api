"""In-memory sliding-window limiter for the unauthenticated auth endpoints.

State lives in the process, which is correct while the API runs as one container.
Put the limit in a shared store (Redis) before scaling to several replicas.
"""

import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Request, status

from app.core.config import settings
from app.core.exceptions import AppError


class TooManyRequestsError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_message = "Too many attempts. Try again later"


class RateLimiter:
    def __init__(self, name: str, limit: Callable[[], int], window_seconds: int) -> None:
        self.name = name
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def reset(self) -> None:
        self._hits.clear()

    async def __call__(self, request: Request) -> None:
        limit = self.limit()
        if limit <= 0:
            return
        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        hits = self._hits[client]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= limit:
            raise TooManyRequestsError()
        hits.append(now)
        if len(self._hits) > 10_000:  # drop idle clients so the table cannot grow forever
            for key in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
                del self._hits[key]


login_limiter = RateLimiter("login", lambda: settings.login_attempts_per_minute, 60)
password_reset_limiter = RateLimiter(
    "password-reset", lambda: settings.password_reset_requests_per_hour, 3600
)
setup_limiter = RateLimiter("setup", lambda: settings.login_attempts_per_minute, 60)
LIMITERS = (login_limiter, password_reset_limiter, setup_limiter)
