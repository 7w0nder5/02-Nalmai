from __future__ import annotations

from typing import Any

from nalmai.errors import NalmaiError
from nalmai.models import NormalizedScore, ScoreBatch, UserBinding


class MaimaiPyArcadeScoreProvider:
    """Read the supported basic score fields through maimai.py ArcadeProvider.

    The current upstream provider deliberately returns FC, FS and play_count as
    unavailable after the Wahlap 1.53 login change.  Nalmai therefore keeps
    those fields unknown instead of fabricating values.
    """

    def __init__(self, http_proxy: str | None = None) -> None:
        self._http_proxy = http_proxy

    async def fetch_scores(
        self, sgwc_credential: str, binding: UserBinding
    ) -> ScoreBatch:
        del binding
        try:
            from maimai_py import ArcadeProvider, MaimaiClient
        except ImportError as exc:
            raise NalmaiError(
                "ARCADE_DEPENDENCY_MISSING",
                "缺少机台成绩依赖；请安装项目的 arcade 可选依赖。",
            ) from exc

        try:
            client = MaimaiClient()
            provider = ArcadeProvider(http_proxy=self._http_proxy)
            identifier = await client.qrcode(
                sgwc_credential, http_proxy=self._http_proxy
            )
            result = await client.scores(identifier, provider=provider)
        except Exception as exc:
            raise NalmaiError(
                "ARCADE_FETCH_FAILED",
                "二维码身份码无效、已过期，或华立成绩服务当前不可用。",
            ) from exc

        scores: list[NormalizedScore] = []
        for score in result.scores:
            normalized = self._normalize_score(score)
            if normalized is not None:
                scores.append(normalized)
        if not scores:
            raise NalmaiError(
                "ARCADE_NO_SCORES",
                "没有从该二维码身份码读取到可上传的标准或 DX 谱面成绩。",
            )
        return ScoreBatch(
            scores=tuple(scores),
            player_display_name="二维码玩家",
            upload_authorized=True,
            unavailable_fields=("FC", "FS", "PC 次数"),
        )

    @staticmethod
    def _normalize_score(score: Any) -> NormalizedScore | None:
        achievements = getattr(score, "achievements", None)
        dx_score = getattr(score, "dx_score", None)
        title = getattr(score, "title", None)
        level_index = getattr(getattr(score, "level_index", None), "value", None)
        score_type = getattr(getattr(score, "type", None), "name", None)
        chart_type = {"STANDARD": "SD", "DX": "DX"}.get(score_type)
        if (
            not isinstance(achievements, (int, float))
            or not isinstance(dx_score, int)
            or not isinstance(title, str)
            or not isinstance(level_index, int)
            or chart_type is None
        ):
            return None

        fc_value = getattr(score, "fc", None)
        fs_value = getattr(score, "fs", None)
        play_count = getattr(score, "play_count", None)
        fc = getattr(fc_value, "name", "").lower() if fc_value is not None else None
        fs = getattr(fs_value, "name", "").lower() if fs_value is not None else None
        return NormalizedScore(
            achievements=float(achievements),
            dx_score=dx_score,
            fc=fc,
            fs=fs,
            level_index=level_index,
            title=title,
            chart_type=chart_type,
            play_count=play_count if isinstance(play_count, int) else None,
        )
