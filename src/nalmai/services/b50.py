from __future__ import annotations

import copy

from nalmai.errors import BindingRequired, NalmaiError
from nalmai.models import B50Image
from nalmai.ports import (
    B50Renderer,
    BindingRepository,
    DivingFishClient,
    WechatOAuthRepository,
)


class B50Service:
    def __init__(
        self,
        bindings: BindingRepository,
        divingfish: DivingFishClient,
        renderer: B50Renderer,
        chart_stats: WechatOAuthRepository | None = None,
    ) -> None:
        self._bindings = bindings
        self._divingfish = divingfish
        self._renderer = renderer
        self._chart_stats = chart_stats

    async def create_image(
        self,
        platform_user_id: str,
        *,
        display_avatar: bytes | None = None,
    ) -> B50Image:
        binding = await self._bindings.get(platform_user_id)
        if binding is None:
            raise BindingRequired()
        try:
            payload = await self._divingfish.query_b50(binding.divingfish_username)
        except NalmaiError as exc:
            if exc.code == "DIVINGFISH_FORBIDDEN":
                raise NalmaiError(
                    "B50_PRIVACY_BLOCKED",
                    "水鱼隐私设置阻止公开 B50；本地 B50 算法尚未验收。",
                ) from exc
            raise
        if self._chart_stats is not None:
            payload = await self._merge_chart_stats(platform_user_id, payload)
            profile = await self._chart_stats.get_player_profile(platform_user_id)
            if profile is not None:
                payload = copy.deepcopy(payload)
                payload["local_player_profile"] = profile
        if display_avatar is not None:
            payload = copy.deepcopy(payload)
            payload["display_avatar"] = display_avatar
        return await self._renderer.render(payload)

    async def _merge_chart_stats(
        self, platform_user_id: str, payload: dict[str, object]
    ) -> dict[str, object]:
        stats = await self._chart_stats.get_chart_stats(platform_user_id)
        if not stats:
            return payload
        lookup = {
            (item.title, item.chart_type, item.level_index): item for item in stats
        }
        enriched = copy.deepcopy(payload)
        charts = enriched.get("charts")
        if not isinstance(charts, dict):
            return enriched
        for section in ("sd", "dx"):
            entries = charts.get(section)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                title = entry.get("title")
                chart_type = entry.get("type")
                level_index = entry.get("level_index")
                if (
                    not isinstance(title, str)
                    or not isinstance(chart_type, str)
                    or not isinstance(level_index, int)
                ):
                    continue
                stat = lookup.get((title, chart_type, level_index))
                if stat is not None:
                    entry["play_count"] = stat.play_count
                    entry["dx_star"] = stat.dx_star
        return enriched
