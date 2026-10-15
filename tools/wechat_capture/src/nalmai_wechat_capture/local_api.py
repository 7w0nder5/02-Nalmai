from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass
from typing import Any

import httpx

from nalmai.models import (
    B50ChartKey,
    NormalizedScore,
    WechatChartDetail,
    WechatPlayerProfile,
)


class LocalApiError(RuntimeError):
    """Safe local integration error that never contains authorization tokens."""


@dataclass(frozen=True, slots=True)
class ClaimedSession:
    session_id: str
    upload_token: str


class NalmaiLocalApiClient:
    def __init__(self, base_url: str, internal_token: str) -> None:
        if not base_url.startswith("http://127.0.0.1:"):
            raise LocalApiError("本机 API 地址必须使用 127.0.0.1。")
        if not internal_token:
            raise LocalApiError("缺少 NALMAI_INTERNAL_API_TOKEN。")
        self._base_url = base_url.rstrip("/")
        self._internal_token = internal_token
        self._session: ClaimedSession | None = None
        self.last_job_id: str | None = None
        self.last_message: str | None = None

    async def claim(self) -> ClaimedSession:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self._base_url}/internal/wechat/claim",
                headers={"X-Nalmai-Internal-Token": self._internal_token},
            )
        payload = self._json(response)
        if response.status_code != 200:
            raise LocalApiError(self._safe_error(payload, "无法领取微信授权任务。"))
        session_id = payload.get("session_id")
        upload_token = payload.get("upload_token")
        if not isinstance(session_id, str) or not isinstance(upload_token, str):
            raise LocalApiError("本机 API 返回的授权任务结构无效。")
        self._session = ClaimedSession(session_id, upload_token)
        return self._session

    async def upload_scores(
        self, scores: tuple[NormalizedScore, ...]
    ) -> tuple[B50ChartKey, ...]:
        session = self._require_session()
        body = {
            "scores": [
                {
                    "achievements": item.achievements,
                    "dx_score": item.dx_score,
                    "fc": item.fc,
                    "fs": item.fs,
                    "level_index": item.level_index,
                    "title": item.title,
                    "chart_type": item.chart_type,
                }
                for item in scores
            ]
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self._base_url}/v1/wechat/scores",
                headers={"X-Nalmai-WeChat-Token": session.upload_token},
                json=body,
            )
        payload = self._json(response)
        if response.status_code != 200:
            raise LocalApiError(self._safe_error(payload, "微信成绩上传失败。"))
        raw_charts = payload.get("charts")
        if not isinstance(raw_charts, list):
            raise LocalApiError("本机 API 未返回 B50 谱面列表。")
        charts: list[B50ChartKey] = []
        for item in raw_charts:
            if not isinstance(item, dict):
                raise LocalApiError("本机 API 返回的 B50 谱面条目无效。")
            title = item.get("title")
            chart_type = item.get("chart_type")
            level_index = item.get("level_index")
            if (
                not isinstance(title, str)
                or chart_type not in {"SD", "DX"}
                or not isinstance(level_index, int)
            ):
                raise LocalApiError("本机 API 返回的 B50 定位字段无效。")
            charts.append(B50ChartKey(title, chart_type, level_index))
        job_id = payload.get("job_id")
        message = payload.get("text")
        self.last_job_id = job_id if isinstance(job_id, str) else None
        self.last_message = message if isinstance(message, str) else None
        return tuple(charts)

    async def upload_details(self, details: tuple[WechatChartDetail, ...]) -> int:
        session = self._require_session()
        body = {
            "details": [
                {
                    "title": item.title,
                    "chart_type": item.chart_type,
                    "level_index": item.level_index,
                    "play_count": item.play_count,
                    "dx_star": item.dx_star,
                }
                for item in details
            ]
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base_url}/v1/wechat/details",
                headers={"X-Nalmai-WeChat-Token": session.upload_token},
                json=body,
            )
        payload = self._json(response)
        if response.status_code != 200:
            raise LocalApiError(self._safe_error(payload, "微信谱面详情回传失败。"))
        saved = payload.get("saved_details")
        message = payload.get("text")
        if not isinstance(saved, int):
            raise LocalApiError("本机 API 未返回已保存详情数量。")
        self.last_message = message if isinstance(message, str) else self.last_message
        return saved

    async def upload_player_profile(self, profile: WechatPlayerProfile) -> None:
        session = self._require_session()
        body = {
            "player_name": profile.player_name,
            "rating": profile.rating,
            "title_text": profile.title_text,
            "title_rarity": profile.title_rarity,
            "star_count": profile.star_count,
            "avatar_name": profile.avatar_name,
            "nameplate_name": profile.nameplate_name,
            "nameplate_description": profile.nameplate_description,
            "frame_name": profile.frame_name,
            "frame_description": profile.frame_description,
            "version_logo_base64": b64encode(profile.version_logo).decode("ascii"),
            "avatar_base64": b64encode(profile.avatar).decode("ascii"),
            "rating_base_base64": b64encode(profile.rating_base).decode("ascii"),
            "course_rank_base64": b64encode(profile.course_rank).decode("ascii"),
            "class_rank_base64": b64encode(profile.class_rank).decode("ascii"),
            "nameplate_base64": b64encode(profile.nameplate).decode("ascii"),
            "frame_base64": b64encode(profile.frame).decode("ascii"),
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base_url}/v1/wechat/profile",
                headers={"X-Nalmai-WeChat-Token": session.upload_token},
                json=body,
            )
        payload = self._json(response)
        if response.status_code != 200:
            raise LocalApiError(
                self._safe_error(payload, "微信玩家资料回传失败。")
            )

    def _require_session(self) -> ClaimedSession:
        if self._session is None:
            raise LocalApiError("尚未领取微信授权任务。")
        return self._session

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise LocalApiError("本机 API 返回了无效 JSON。") from exc
        if not isinstance(payload, dict):
            raise LocalApiError("本机 API 响应不是 JSON 对象。")
        return payload

    @staticmethod
    def _safe_error(payload: dict[str, Any], fallback: str) -> str:
        text = payload.get("text")
        return text if isinstance(text, str) and text else fallback
