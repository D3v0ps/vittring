"""Lightweight token-bucket rate limiter.

In-process is sufficient for a single-instance deploy on the CX23. When/if
we scale to multiple replicas we swap the in-memory store for Redis.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass
from threading import Lock
from typing import Callable

from fastapi import HTTPException, Request, status

from vittring.utils.errors import RateLimitExceededError


@dataclass(slots=True)
class _Bucket:
    tokens: float
    last_refill: float


class RateLimiter:
    def __init__(self, *, capacity: int, window_seconds: int) -> None:
        self._capacity = capacity
        self._window = window_seconds
        self._buckets: dict[str, _Bucket] = defaultdict(
            lambda: _Bucket(tokens=float(capacity), last_refill=time.monotonic())
        )
        self._lock = Lock()

    def _refill(self, bucket: _Bucket, now: float) -> None:
        elapsed = now - bucket.last_refill
        rate = self._capacity / self._window
        bucket.tokens = min(self._capacity, bucket.tokens + elapsed * rate)
        bucket.last_refill = now

    def take(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            bucket = self._buckets[key]
            self._refill(bucket, now)
            if bucket.tokens < 1:
                deficit = 1 - bucket.tokens
                rate = self._capacity / self._window
                retry_after = int(deficit / rate) + 1
                raise RateLimitExceededError(retry_after_seconds=retry_after)
            bucket.tokens -= 1


# Pre-instantiated buckets per CLAUDE.md §13 ----------------------------
LOGIN_BY_IP = RateLimiter(capacity=10, window_seconds=60)
LOGIN_BY_EMAIL = RateLimiter(capacity=5, window_seconds=60)
SIGNUP_BY_IP = RateLimiter(capacity=5, window_seconds=3600)
PASSWORD_RESET_BY_EMAIL = RateLimiter(capacity=3, window_seconds=3600)
DEFAULT_BY_IP = RateLimiter(capacity=100, window_seconds=60)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(limiter: RateLimiter, key_fn: Callable[[Request], str]) -> Callable[[Request], None]:
    def dependency(request: Request) -> None:
        key = key_fn(request)
        try:
            limiter.take(key)
        except RateLimitExceededError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="rate_limit_exceeded",
                headers={"Retry-After": str(exc.retry_after_seconds)},
            ) from exc

    return dependency
