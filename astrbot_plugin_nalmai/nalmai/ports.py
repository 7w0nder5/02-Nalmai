from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from nalmai.models import (
    B50Image,
    LocalChartStat,
    LocalPlayerProfile,
    ScoreBatch,
    SyncJob,
    UploadReceipt,
    UserBinding,
    WechatOAuthSession,
)


class CredentialCipher(Protocol):
    key_version: str

    def encrypt(self, plaintext: str) -> bytes: ...

    def decrypt(self, ciphertext: bytes) -> str: ...


class BindingRepository(Protocol):
    async def get(self, platform_user_id: str) -> UserBinding | None: ...

    async def save(self, binding: UserBinding) -> None: ...

    async def delete(self, platform_user_id: str) -> bool: ...


class JobRepository(Protocol):
    async def save(self, job: SyncJob) -> None: ...

    async def get_latest(self, platform_user_id: str) -> SyncJob | None: ...


class QQIdentityRepository(Protocol):
    async def save_pairing_code(
        self, code_digest: str, private_identity: str, expires_at: datetime
    ) -> bool: ...

    async def consume_pairing_code(
        self,
        code_digest: str,
        group_identity: str,
        consumed_at: datetime,
    ) -> str | None: ...

    async def resolve_group_identity(self, group_identity: str) -> str | None: ...

    async def delete_identity_links(self, private_identity: str) -> int: ...


class WechatOAuthRepository(Protocol):
    async def create_wechat_session(self, session: WechatOAuthSession) -> None: ...

    async def claim_pending_wechat_session(
        self, token_digest: str, claimed_at: datetime, expires_at: datetime
    ) -> WechatOAuthSession | None: ...

    async def get_wechat_session_by_token(
        self, token_digest: str, accessed_at: datetime
    ) -> WechatOAuthSession | None: ...

    async def save_wechat_session(self, session: WechatOAuthSession) -> None: ...

    async def save_chart_stats(self, stats: tuple[LocalChartStat, ...]) -> None: ...

    async def get_chart_stats(
        self, platform_user_id: str
    ) -> tuple[LocalChartStat, ...]: ...

    async def save_player_profile(self, profile: LocalPlayerProfile) -> None: ...

    async def get_player_profile(
        self, platform_user_id: str
    ) -> LocalPlayerProfile | None: ...


class DivingFishClient(Protocol):
    async def get_records(self, import_token: str) -> dict[str, Any]: ...

    async def upload_records(
        self, import_token: str, records: list[dict[str, Any]]
    ) -> UploadReceipt: ...

    async def query_b50(self, username: str) -> dict[str, Any]: ...

    async def get_music_data(self) -> list[dict[str, Any]]: ...

    async def get_cover(self, song_id: int) -> bytes | None: ...


class ArcadeScoreProvider(Protocol):
    async def fetch_scores(self, sgwc_credential: str, binding: UserBinding) -> ScoreBatch: ...


class B50Renderer(Protocol):
    async def render(self, payload: dict[str, Any]) -> B50Image: ...
