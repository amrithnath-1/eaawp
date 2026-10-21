"""
Small in-process rate limiter for the public (unauthenticated) endpoints.

Why in-process: it needs no extra infrastructure and protects a single API
process out of the box.  LIMITATION (documented in docs/security_phase2.md): the
counters are per process, so with N workers/replicas the effective limit is N x
the configured value.  Put a shared limiter (reverse proxy / Redis) in front for
multi-instance deployments.

Client identity is the socket peer address.  ``X-Forwarded-For`` is honoured
ONLY when ``settings.trusted_proxy_count`` > 0 and then only the entry added by
the Nth trusted proxy from the right, so a client cannot spoof its own address.
"""
from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import HTTPException, Request, status

from app.config import settings

_MAX_KEYS = 50_000  # hard cap so a flood of distinct keys cannot exhaust memory


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._events.clear()

    def _prune(self, q: deque[float], now: float, window: float) -> None:
        while q and now - q[0] >= window:
            q.popleft()

    def check(self, key: str, limit: int, window: float) -> float:
        """Record one hit.  Returns 0 if allowed, else seconds until a slot frees."""
        now = time.monotonic()
        with self._lock:
            q = self._events.get(key)
            if q is None:
                if len(self._events) >= _MAX_KEYS:
                    self._evict(now, window)
                q = self._events.setdefault(key, deque())
            self._prune(q, now, window)
            if len(q) >= limit:
                return max(1.0, window - (now - q[0]))
            q.append(now)
            return 0.0

    def count(self, key: str, window: float) -> int:
        now = time.monotonic()
        with self._lock:
            q = self._events.get(key)
            if not q:
                return 0
            self._prune(q, now, window)
            return len(q)

    def clear_key(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    def record(self, key: str) -> None:
        with self._lock:
            self._events.setdefault(key, deque()).append(time.monotonic())

    def _evict(self, now: float, window: float) -> None:
        for k in list(self._events):
            q = self._events[k]
            self._prune(q, now, window)
            if not q:
                del self._events[k]
        while len(self._events) >= _MAX_KEYS:  # still full: drop the oldest key
            self._events.pop(next(iter(self._events)))


limiter = SlidingWindowLimiter()


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    hops = settings.trusted_proxy_count
    if hops > 0:
        xff = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if len(xff) >= hops:
            return xff[-hops]
    return peer


def too_many(retry_after: float, what: str = "requests") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Too many {what}. Try again later.",
        headers={"Retry-After": str(int(retry_after))},
    )


def rate_limit(name: str, limit_attr: str, window_attr: str):
    """FastAPI dependency factory: per-client-IP limit read from settings at call time."""

    async def _dep(request: Request) -> None:
        if not settings.rate_limit_enabled:
            return
        retry = limiter.check(
            f"{name}:{client_ip(request)}",
            int(getattr(settings, limit_attr)),
            float(getattr(settings, window_attr)),
        )
        if retry:
            raise too_many(retry)

    _dep.__name__ = f"rate_limit_{name}"
    return _dep
