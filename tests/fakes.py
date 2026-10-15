from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from nalmai.errors import NalmaiError
from nalmai.models import (
    B50Image,
    LocalChartStat,
    LocalPlayerProfile,
    NormalizedScore,
    ScoreBatch,
    SyncJob,
    UploadReceipt,
    UserBinding,
    WechatOAuthSession,
    WechatSessionStatus,
)


class FakeCipher:
    key_version = "test-v1"

    def encrypt(self, plaintext: str) -> bytes:
        return b"encrypted:" + plaintext[::-1].encode("utf-8")

    def decrypt(self, ciphertext: bytes) -> str:
        prefix = b"encrypted:"
        assert ciphertext.startswith(prefix)
        return ciphertext[len(prefix) :].decode("utf-8")[::-1]


class FakeRepository:
    def __init__(self) -> None:
        self.bindings: dict[str, UserBinding] = {}
        self.jobs: dict[str, SyncJob] = {}
        self.pairing_codes: dict[str, tuple[str, datetime]] = {}
        self.identity_links: dict[str, str] = {}
        self.wechat_sessions: dict[str, WechatOAuthSession] = {}
        self.chart_stats: dict[tuple[str, str, str, int], LocalChartStat] = {}
        self.player_profiles: dict[str, LocalPlayerProfile] = {}

    async def get(self, platform_user_id: str) -> UserBinding | None:
        return self.bindings.get(platform_user_id)

    async def save(self, item: UserBinding | SyncJob) -> None:
        if isinstance(item, UserBinding):
            self.bindings[item.platform_user_id] = item
        else:
            self.jobs[item.id] = item

    async def delete(self, platform_user_id: str) -> bool:
        return self.bindings.pop(platform_user_id, None) is not None

    async def get_latest(self, platform_user_id: str) -> SyncJob | None:
        jobs = [job for job in self.jobs.values() if job.platform_user_id == platform_user_id]
        return max(jobs, key=lambda item: item.created_at) if jobs else None

    async def save_pairing_code(
        self, code_digest: str, private_identity: str, expires_at: datetime
    ) -> bool:
        if code_digest in self.pairing_codes:
            return False
        self.pairing_codes = {
            digest: value
            for digest, value in self.pairing_codes.items()
            if value[0] != private_identity
        }
        self.pairing_codes[code_digest] = (private_identity, expires_at)
        return True

    async def consume_pairing_code(
        self,
        code_digest: str,
        group_identity: str,
        consumed_at: datetime,
    ) -> str | None:
        value = self.pairing_codes.pop(code_digest, None)
        if value is None:
            return None
        private_identity, expires_at = value
        if expires_at <= consumed_at:
            return None
        self.identity_links[group_identity] = private_identity
        return private_identity

    async def resolve_group_identity(self, group_identity: str) -> str | None:
        return self.identity_links.get(group_identity)

    async def delete_identity_links(self, private_identity: str) -> int:
        groups = [
            group
            for group, private in self.identity_links.items()
            if private == private_identity
        ]
        for group in groups:
            del self.identity_links[group]
        self.pairing_codes = {
            digest: value
            for digest, value in self.pairing_codes.items()
            if value[0] != private_identity
        }
        return len(groups)

    async def create_wechat_session(self, session: WechatOAuthSession) -> None:
        self.wechat_sessions = {
            key: item
            for key, item in self.wechat_sessions.items()
            if not (
                item.platform_user_id == session.platform_user_id
                and item.status
                in {
                    WechatSessionStatus.PENDING,
                    WechatSessionStatus.CLAIMED,
                    WechatSessionStatus.SCORES_UPLOADED,
                }
            )
        }
        self.wechat_sessions[session.id] = session

    async def claim_pending_wechat_session(
        self, token_digest: str, claimed_at: datetime, expires_at: datetime
    ) -> WechatOAuthSession | None:
        matches = [
            item
            for item in self.wechat_sessions.values()
            if item.status is WechatSessionStatus.PENDING
            and item.expires_at > claimed_at
        ]
        if not matches:
            return None
        session = max(matches, key=lambda item: item.created_at)
        session.status = WechatSessionStatus.CLAIMED
        session.token_digest = token_digest
        session.claimed_at = claimed_at
        session.expires_at = expires_at
        return session

    async def get_wechat_session_by_token(
        self, token_digest: str, accessed_at: datetime
    ) -> WechatOAuthSession | None:
        return next(
            (
                item
                for item in self.wechat_sessions.values()
                if item.token_digest == token_digest and item.expires_at > accessed_at
            ),
            None,
        )

    async def save_wechat_session(self, session: WechatOAuthSession) -> None:
        self.wechat_sessions[session.id] = session

    async def save_chart_stats(self, stats: tuple[LocalChartStat, ...]) -> None:
        for item in stats:
            self.chart_stats[
                (
                    item.platform_user_id,
                    item.title,
                    item.chart_type,
                    item.level_index,
                )
            ] = item

    async def get_chart_stats(
        self, platform_user_id: str
    ) -> tuple[LocalChartStat, ...]:
        return tuple(
            item
            for item in self.chart_stats.values()
            if item.platform_user_id == platform_user_id
        )

    async def save_player_profile(self, profile: LocalPlayerProfile) -> None:
        self.player_profiles[profile.platform_user_id] = profile

    async def get_player_profile(
        self, platform_user_id: str
    ) -> LocalPlayerProfile | None:
        return self.player_profiles.get(platform_user_id)


class FakeDivingFish:
    def __init__(self) -> None:
        self.records_payload: dict[str, Any] = {
            "username": "water_user",
            "nickname": "Tester",
            "rating": 15000,
            "records": [],
        }
        self.b50_payload: dict[str, Any] = {
            "nickname": "Tester",
            "rating": 15000,
            "additional_rating": 0,
            "charts": {
                "sd": [
                    {
                        "title": "Test Song",
                        "achievements": 100.5,
                        "ds": 13.5,
                        "dxScore": 2900,
                        "fc": "fc",
                        "fs": "fs",
                        "level": "13+",
                        "level_index": 3,
                        "level_label": "Master",
                        "ra": 300,
                        "rate": "sssp",
                        "song_id": 1234,
                        "type": "SD",
                    }
                ],
                "dx": [],
            },
        }
        self.uploaded: list[dict[str, Any]] = []
        self.error: NalmaiError | None = None
        self.partial_upload = False
        self.keep_stale_records = False
        self.music_payload: list[dict[str, Any]] = [
            {
                "id": 1234,
                "title": "Test Song",
                "type": "SD",
                "ds": [4.0, 7.0, 10.0, 13.5],
                "level": ["4", "7", "10", "13+"],
                "cids": [1, 2, 3, 4],
                "charts": [
                    {"notes": [10, 10, 10, 10]},
                    {"notes": [20, 20, 20, 20]},
                    {"notes": [30, 30, 30, 30]},
                    {"notes": [250, 200, 200, 350]},
                ],
                "basic_info": {"from": "maimai でらっくす PRiSM"},
            }
        ]

    async def get_records(self, import_token: str) -> dict[str, Any]:
        if self.error:
            raise self.error
        assert import_token
        return self.records_payload

    async def upload_records(
        self, import_token: str, records: list[dict[str, Any]]
    ) -> UploadReceipt:
        if self.error:
            raise self.error
        assert import_token
        self.uploaded = records
        if not self.keep_stale_records:
            self.records_payload["records"] = [dict(record) for record in records]
        affected = max(0, len(records) - 1) if self.partial_upload else len(records)
        return UploadReceipt("更新成功", updates=affected, creates=0)

    async def query_b50(self, username: str) -> dict[str, Any]:
        if self.error:
            raise self.error
        assert username == "water_user"
        return self.b50_payload

    async def get_music_data(self) -> list[dict[str, Any]]:
        return self.music_payload

    async def get_cover(self, song_id: int) -> bytes | None:
        assert song_id == 1234
        return None


class FakeArcade:
    def __init__(self, *, verified: bool = True, delay: float = 0.0) -> None:
        self.verified = verified
        self.delay = delay
        self.active = 0
        self.max_active = 0

    async def fetch_scores(
        self, sgwc_credential: str, binding: UserBinding
    ) -> ScoreBatch:
        assert sgwc_credential.startswith("SGWCMAID")
        assert binding.divingfish_username == "water_user"
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if self.delay:
            await asyncio.sleep(self.delay)
        self.active -= 1
        return ScoreBatch(
            scores=(sample_score(),),
            player_display_name="Arcade Tester",
            upload_authorized=self.verified,
        )


class FakeRenderer:
    async def render(self, payload: dict[str, Any]) -> B50Image:
        assert payload["nickname"] == "Tester"
        return B50Image(content=b"fake-png")


def sample_score() -> NormalizedScore:
    return NormalizedScore(
        achievements=100.5,
        dx_score=1234,
        fc="fc",
        fs="",
        level_index=3,
        title="Test Song",
        chart_type="SD",
    )
