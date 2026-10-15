from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from nalmai.errors import NalmaiError
from nalmai.ports import QQIdentityRepository


@dataclass(frozen=True, slots=True)
class PairingCode:
    value: str
    expires_at: datetime


class QQIdentityService:
    code_length = 8

    def __init__(
        self,
        repository: QQIdentityRepository,
        hmac_key: str,
        *,
        ttl_seconds: int = 300,
    ) -> None:
        if not hmac_key:
            raise ValueError("QQ identity pairing requires a non-empty HMAC key")
        if ttl_seconds <= 0:
            raise ValueError("QQ identity pairing TTL must be positive")
        self._repository = repository
        self._key = hmac_key.encode("utf-8")
        self._ttl = timedelta(seconds=ttl_seconds)

    def private_identity(self, user_openid: str) -> str:
        if not user_openid:
            raise ValueError("QQ C2C user_openid must not be empty")
        return f"qq:c2c:{self._identity_digest('c2c', user_openid)}"

    def group_identity(self, group_openid: str, member_openid: str) -> str:
        if not group_openid or not member_openid:
            raise ValueError("QQ group and member openids must not be empty")
        return "qq:group:" + self._identity_digest(
            "group", f"{group_openid}\0{member_openid}"
        )

    async def issue(self, private_identity: str) -> PairingCode:
        if not private_identity.startswith("qq:c2c:"):
            raise ValueError("pairing codes can only be issued to QQ C2C identities")
        for _ in range(10):
            code = f"{secrets.randbelow(10**self.code_length):0{self.code_length}d}"
            expires_at = datetime.now(UTC) + self._ttl
            reserved = await self._repository.save_pairing_code(
                self._digest(code), private_identity, expires_at
            )
            if reserved:
                return PairingCode(code, expires_at)
        raise NalmaiError(
            "PAIR_CODE_ALLOCATION_FAILED",
            "暂时无法生成配对码，请稍后重试。",
        )

    async def consume(self, code: str, group_identity: str) -> str:
        if (
            len(code) != self.code_length
            or not code.isascii()
            or not code.isdigit()
        ):
            raise NalmaiError("INVALID_PAIR_CODE", "配对码必须是 8 位数字。")
        if not group_identity.startswith("qq:group:"):
            raise ValueError("pairing codes can only be consumed by QQ group identities")
        private_identity = await self._repository.consume_pairing_code(
            self._digest(code), group_identity, datetime.now(UTC)
        )
        if private_identity is None:
            raise NalmaiError(
                "PAIR_CODE_INVALID_OR_EXPIRED",
                "配对码无效、已使用或已过期，请在私聊重新发送 /pair。",
            )
        return private_identity

    async def resolve_group(self, group_identity: str) -> str | None:
        return await self._repository.resolve_group_identity(group_identity)

    async def unlink_private(self, private_identity: str) -> int:
        return await self._repository.delete_identity_links(private_identity)

    def _digest(self, code: str) -> str:
        return hmac.new(
            self._key,
            f"qq-pair\0{code}".encode("ascii"),
            hashlib.sha256,
        ).hexdigest()

    def _identity_digest(self, scope: str, value: str) -> str:
        return hmac.new(
            self._key,
            f"qq-identity\0{scope}\0{value}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
