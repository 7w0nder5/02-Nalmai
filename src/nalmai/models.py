from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class CommandKind(StrEnum):
    HELP = "HELP"
    PAIR_ISSUE = "PAIR_ISSUE"
    PAIR_CONSUME = "PAIR_CONSUME"
    BIND_GUIDE = "BIND_GUIDE"
    BIND = "BIND"
    SYNC = "SYNC"
    WECHAT = "WECHAT"
    B50 = "B50"
    STATUS = "STATUS"
    UNBIND = "UNBIND"


class BindingStatus(StrEnum):
    BOUND = "BOUND"
    ROTATION_REQUIRED = "ROTATION_REQUIRED"
    REVOKED = "REVOKED"


class JobStatus(StrEnum):
    CREATED = "CREATED"
    CREDENTIAL_ACCEPTED = "CREDENTIAL_ACCEPTED"
    FETCHING_SCORES = "FETCHING_SCORES"
    NORMALIZING = "NORMALIZING"
    UPLOADING = "UPLOADING"
    VERIFYING_B50 = "VERIFYING_B50"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UPLOADED_UNVERIFIED = "UPLOADED_UNVERIFIED"


class WechatSessionStatus(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    SCORES_UPLOADED = "SCORES_UPLOADED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class InboundMessage:
    platform_user_id: str
    session_id: str
    text: str
    is_private: bool
    message_reference: str | None = None
    display_avatar: bytes | None = None


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    kind: CommandKind
    pairing_code: str | None = None
    claimed_qq: str | None = None
    import_token: str | None = None
    sgwc_credential: str | None = None


@dataclass(slots=True)
class UserBinding:
    platform_user_id: str
    claimed_qq: str
    divingfish_username: str
    credential_ciphertext: bytes
    credential_key_version: str
    credential_mask: str
    status: BindingStatus = BindingStatus.BOUND
    bound_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    credential_rotated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class NormalizedScore:
    achievements: float
    dx_score: int
    fc: str | None
    fs: str | None
    level_index: int
    title: str
    chart_type: str
    play_count: int | None = None

    def to_divingfish_record(self) -> dict[str, Any]:
        return {
            "achievements": self.achievements,
            "dxScore": self.dx_score,
            "fc": self.fc,
            "fs": self.fs,
            "level_index": self.level_index,
            "title": self.title,
            "type": self.chart_type,
        }


@dataclass(slots=True)
class WechatOAuthSession:
    id: str
    platform_user_id: str
    status: WechatSessionStatus
    token_digest: str | None
    created_at: datetime
    expires_at: datetime
    claimed_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class LocalChartStat:
    platform_user_id: str
    title: str
    chart_type: str
    level_index: int
    play_count: int
    dx_star: int | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class B50ChartKey:
    title: str
    chart_type: str
    level_index: int


@dataclass(frozen=True, slots=True)
class WechatChartDetail:
    title: str
    chart_type: str
    level_index: int
    play_count: int
    dx_star: int | None


@dataclass(frozen=True, slots=True)
class WechatPlayerProfile:
    player_name: str
    rating: int
    title_text: str
    title_rarity: str
    star_count: int
    avatar_name: str
    nameplate_name: str
    nameplate_description: str
    frame_name: str
    frame_description: str
    version_logo: bytes
    avatar: bytes
    rating_base: bytes
    course_rank: bytes
    class_rank: bytes
    nameplate: bytes
    frame: bytes


@dataclass(frozen=True, slots=True)
class LocalPlayerProfile:
    platform_user_id: str
    player_name: str
    rating: int
    title_text: str
    title_rarity: str
    star_count: int
    avatar_name: str
    nameplate_name: str
    nameplate_description: str
    frame_name: str
    frame_description: str
    version_logo: bytes
    avatar: bytes
    rating_base: bytes
    course_rank: bytes
    class_rank: bytes
    nameplate: bytes
    frame: bytes
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ScoreBatch:
    scores: tuple[NormalizedScore, ...]
    player_display_name: str
    upload_authorized: bool
    unavailable_fields: tuple[str, ...] = ()


@dataclass(slots=True)
class SyncJob:
    id: str
    platform_user_id: str
    status: JobStatus
    credential_digest: str
    score_count: int = 0
    uploaded_count: int = 0
    skipped_count: int = 0
    error_code: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class UploadReceipt:
    message: str
    updates: int
    creates: int

    @property
    def affected(self) -> int:
        return self.updates + self.creates


@dataclass(frozen=True, slots=True)
class BindResult:
    username: str
    nickname: str
    masked_qq: str
    masked_token: str


@dataclass(frozen=True, slots=True)
class SyncResult:
    job_id: str
    uploaded_count: int
    skipped_count: int
    player_display_name: str
    unavailable_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class B50Image:
    content: bytes
    media_type: str = "image/png"
    filename: str = "nalmai-b50.png"


@dataclass(frozen=True, slots=True)
class ApplicationResponse:
    text: str
    image: B50Image | None = None
    error_code: str | None = None
