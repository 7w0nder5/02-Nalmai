from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from nalmai.errors import NalmaiError


@dataclass(slots=True)
class SubmissionSession:
    platform_user_id: str
    expires_at: float


class SubmissionSessionStore:
    def __init__(self, ttl_seconds: int = 300) -> None:
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, SubmissionSession] = {}

    def create(self, platform_user_id: str) -> str:
        nonce = secrets.token_urlsafe(32)
        self._sessions[nonce] = SubmissionSession(
            platform_user_id=platform_user_id,
            expires_at=time.monotonic() + self._ttl_seconds,
        )
        return nonce

    def consume(self, nonce: str) -> str:
        session = self._sessions.pop(nonce, None)
        if session is None or session.expires_at < time.monotonic():
            raise NalmaiError(
                "SUBMISSION_SESSION_INVALID",
                "提交链接不存在、已过期或已经使用。",
            )
        return session.platform_user_id

