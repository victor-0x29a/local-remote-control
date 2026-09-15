"""Exclusive browser-controller lease."""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LeaseHandle:
    id: str
    session_token: str

    def __repr__(self) -> str:
        return f"LeaseHandle(id={self.id!r}, session_token=<redacted>)"


class ControllerLease:
    def __init__(self, timeout: float = 15.0, clock: Callable[[], float] = time.monotonic) -> None:
        self._timeout = timeout
        self._clock = clock
        self._lock = asyncio.Lock()
        self._active: LeaseHandle | None = None
        self._last_seen = 0.0

    async def acquire(self, session_token: str) -> LeaseHandle | None:
        async with self._lock:
            if self._active is not None:
                return None
            self._active = LeaseHandle(secrets.token_urlsafe(24), session_token)
            self._last_seen = self._clock()
            return self._active

    async def heartbeat(self, handle_id: str) -> bool:
        async with self._lock:
            if self._active is None or self._active.id != handle_id:
                return False
            self._last_seen = self._clock()
            return True

    async def owns(self, handle_id: str, session_token: str) -> bool:
        async with self._lock:
            return bool(
                self._active is not None
                and self._active.id == handle_id
                and self._active.session_token == session_token
            )

    async def release(self, handle_id: str) -> None:
        async with self._lock:
            if self._active is not None and self._active.id == handle_id:
                self._active = None

    async def reap(self, now: float | None = None) -> bool:
        async with self._lock:
            moment = self._clock() if now is None else now
            if self._active is None or moment - self._last_seen <= self._timeout:
                return False
            self._active = None
            return True
