from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from nalmai.errors import BindingRequired, NalmaiError
from nalmai.models import (
    B50ChartKey,
    LocalChartStat,
    LocalPlayerProfile,
    NormalizedScore,
    SyncResult,
    WechatChartDetail,
    WechatOAuthSession,
    WechatPlayerProfile,
    WechatSessionStatus,
)
from nalmai.ports import BindingRepository, DivingFishClient, WechatOAuthRepository
from nalmai.services.sync import SyncService


class WechatOAuthService:
    pending_ttl = timedelta(minutes=5)
    claimed_ttl = timedelta(minutes=15)

    def __init__(
        self,
        bindings: BindingRepository,
        repository: WechatOAuthRepository,
        sync: SyncService,
        divingfish: DivingFishClient,
        hmac_key: str,
    ) -> None:
        if not hmac_key:
            raise ValueError("WeChat OAuth requires a non-empty HMAC key")
        self._bindings = bindings
        self._repository = repository
        self._sync = sync
        self._divingfish = divingfish
        self._hmac_key = hmac_key.encode("utf-8")

    async def issue(self, platform_user_id: str) -> WechatOAuthSession:
        if await self._bindings.get(platform_user_id) is None:
            raise BindingRequired()
        now = datetime.now(UTC)
        session = WechatOAuthSession(
            id=str(uuid.uuid4()),
            platform_user_id=platform_user_id,
            status=WechatSessionStatus.PENDING,
            token_digest=None,
            created_at=now,
            expires_at=now + self.pending_ttl,
        )
        await self._repository.create_wechat_session(session)
        return session

    async def claim(self) -> tuple[WechatOAuthSession, str]:
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        session = await self._repository.claim_pending_wechat_session(
            self._digest(token),
            now,
            now + self.claimed_ttl,
        )
        if session is None:
            raise NalmaiError(
                "WECHAT_SESSION_NOT_FOUND",
                "没有等待中的微信授权任务；请先在 QQ 私聊发送 /wechat。",
            )
        return session, token

    async def upload_scores(
        self,
        token: str,
        scores: tuple[NormalizedScore, ...],
    ) -> tuple[SyncResult, tuple[B50ChartKey, ...]]:
        session = await self._require_session(
            token, {WechatSessionStatus.CLAIMED}
        )
        if not scores:
            raise NalmaiError("WECHAT_SCORES_EMPTY", "微信成绩列表中没有可上传成绩。")
        try:
            result = await self._sync.synchronize_authorized_scores(
                session.platform_user_id,
                scores,
                session.id,
            )
            binding = await self._bindings.get(session.platform_user_id)
            if binding is None:
                raise BindingRequired()
            payload = await self._divingfish.query_b50(binding.divingfish_username)
            chart_keys = self._b50_chart_keys(payload)
            session.status = WechatSessionStatus.SCORES_UPLOADED
            session.expires_at = datetime.now(UTC) + self.claimed_ttl
            await self._repository.save_wechat_session(session)
            return result, chart_keys
        except NalmaiError as exc:
            session.status = WechatSessionStatus.FAILED
            session.error_code = exc.code
            session.finished_at = datetime.now(UTC)
            session.token_digest = None
            await self._repository.save_wechat_session(session)
            raise

    async def upload_details(
        self,
        token: str,
        details: tuple[WechatChartDetail, ...],
    ) -> int:
        session = await self._require_session(
            token, {WechatSessionStatus.SCORES_UPLOADED}
        )
        if not details:
            raise NalmaiError(
                "WECHAT_DETAILS_EMPTY",
                "成绩已上传，但没有取得当前 B50 的谱面详情。",
            )
        now = datetime.now(UTC)
        stats: list[LocalChartStat] = []
        for item in details:
            if (
                not item.title
                or item.chart_type not in {"SD", "DX"}
                or not 0 <= item.level_index <= 4
                or item.play_count < 0
                or (item.dx_star is not None and item.dx_star < 0)
            ):
                raise NalmaiError(
                    "WECHAT_DETAIL_INVALID",
                    "微信谱面详情包含无效字段，未写入本地统计。",
                )
            stats.append(
                LocalChartStat(
                    platform_user_id=session.platform_user_id,
                    title=item.title,
                    chart_type=item.chart_type,
                    level_index=item.level_index,
                    play_count=item.play_count,
                    dx_star=item.dx_star,
                    updated_at=now,
                )
            )
        await self._repository.save_chart_stats(tuple(stats))
        session.status = WechatSessionStatus.SUCCEEDED
        session.finished_at = now
        session.token_digest = None
        await self._repository.save_wechat_session(session)
        return len(stats)

    async def upload_player_profile(
        self,
        token: str,
        profile: WechatPlayerProfile,
    ) -> None:
        session = await self._require_session(
            token, {WechatSessionStatus.SCORES_UPLOADED}
        )
        text_fields = (
            profile.player_name,
            profile.title_text,
            profile.title_rarity,
            profile.avatar_name,
            profile.nameplate_name,
            profile.nameplate_description,
            profile.frame_name,
            profile.frame_description,
        )
        asset_fields = (
            profile.version_logo,
            profile.avatar,
            profile.rating_base,
            profile.course_rank,
            profile.class_rank,
            profile.nameplate,
            profile.frame,
        )
        if (
            any(not value or len(value) > 512 for value in text_fields)
            or profile.rating < 0
            or profile.star_count < 0
            or any(not value or len(value) > 5 * 1024 * 1024 for value in asset_fields)
        ):
            raise NalmaiError(
                "WECHAT_PROFILE_INVALID",
                "微信玩家资料包含无效字段，未写入本地资料。",
            )
        await self._repository.save_player_profile(
            LocalPlayerProfile(
                platform_user_id=session.platform_user_id,
                player_name=profile.player_name,
                rating=profile.rating,
                title_text=profile.title_text,
                title_rarity=profile.title_rarity,
                star_count=profile.star_count,
                avatar_name=profile.avatar_name,
                nameplate_name=profile.nameplate_name,
                nameplate_description=profile.nameplate_description,
                frame_name=profile.frame_name,
                frame_description=profile.frame_description,
                version_logo=profile.version_logo,
                avatar=profile.avatar,
                rating_base=profile.rating_base,
                course_rank=profile.course_rank,
                class_rank=profile.class_rank,
                nameplate=profile.nameplate,
                frame=profile.frame,
                updated_at=datetime.now(UTC),
            )
        )

    async def _require_session(
        self,
        token: str,
        allowed: set[WechatSessionStatus],
    ) -> WechatOAuthSession:
        if not token:
            raise NalmaiError(
                "WECHAT_TOKEN_INVALID",
                "微信授权回传令牌无效或已经过期。",
            )
        session = await self._repository.get_wechat_session_by_token(
            self._digest(token), datetime.now(UTC)
        )
        if session is None or session.status not in allowed:
            raise NalmaiError(
                "WECHAT_TOKEN_INVALID",
                "微信授权回传令牌无效、已过期或已经使用。",
            )
        return session

    def _digest(self, token: str) -> str:
        return hmac.new(
            self._hmac_key,
            f"wechat-oauth\0{token}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _b50_chart_keys(payload: dict[str, object]) -> tuple[B50ChartKey, ...]:
        charts = payload.get("charts")
        if not isinstance(charts, dict):
            raise NalmaiError("B50_SCHEMA_ERROR", "B50 响应缺少 charts 对象。")
        result: list[B50ChartKey] = []
        for section in ("sd", "dx"):
            items = charts.get(section)
            if not isinstance(items, list):
                raise NalmaiError(
                    "B50_SCHEMA_ERROR", f"B50 响应缺少 {section} 列表。"
                )
            for item in items:
                if not isinstance(item, dict):
                    raise NalmaiError("B50_SCHEMA_ERROR", "B50 谱面条目不是对象。")
                title = item.get("title")
                chart_type = item.get("type")
                level_index = item.get("level_index")
                if (
                    not isinstance(title, str)
                    or chart_type not in {"SD", "DX"}
                    or not isinstance(level_index, int)
                ):
                    raise NalmaiError(
                        "B50_SCHEMA_ERROR", "B50 谱面条目缺少精确定位字段。"
                    )
                result.append(B50ChartKey(title, chart_type, level_index))
        return tuple(result)
