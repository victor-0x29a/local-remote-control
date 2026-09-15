"""Password throttling and opaque in-memory browser sessions."""

from __future__ import annotations

import secrets
from collections import OrderedDict
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError


@dataclass(slots=True)
class Session:
    token: str
    csrf: str
    created_at: float
    last_seen: float


@dataclass(slots=True)
class _Failures:
    count: int = 0
    blocked_until: float = 0.0


class AuthManager:
    def __init__(
        self,
        password_hash: str,
        idle_seconds: int,
        *,
        hasher: PasswordHasher | None = None,
    ) -> None:
        self._password_hash = password_hash
        self._idle_seconds = idle_seconds
        self._hasher = hasher or PasswordHasher()
        self._failures: OrderedDict[str, _Failures] = OrderedDict()
        self._sessions: dict[str, Session] = {}

    def verify_password(self, ip: str, password: str, now: float) -> bool:
        failures = self._failures.setdefault(ip, _Failures())
        self._failures.move_to_end(ip)
        if failures.count >= 5 and now < failures.blocked_until:
            return False
        try:
            valid = self._hasher.verify(self._password_hash, password)
        except VerificationError:
            valid = False
        if valid:
            self._failures.pop(ip, None)
            return True
        failures.count += 1
        if failures.count >= 5:
            failures.blocked_until = now + min(60.0, 2.0 ** (failures.count - 5))
        while len(self._failures) > 128:
            self._failures.popitem(last=False)
        return False

    def create_session(self, now: float) -> Session:
        session = Session(
            token=secrets.token_urlsafe(32),
            csrf=secrets.token_urlsafe(32),
            created_at=now,
            last_seen=now,
        )
        self._sessions[session.token] = session
        return session

    def authenticate(self, token: str, now: float) -> Session | None:
        session = self._sessions.get(token)
        if session is None:
            return None
        if now - session.last_seen > self._idle_seconds:
            self.revoke(token)
            return None
        session.last_seen = now
        return session

    def revoke(self, token: str) -> None:
        self._sessions.pop(token, None)
