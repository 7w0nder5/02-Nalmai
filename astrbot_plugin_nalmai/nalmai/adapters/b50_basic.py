from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from nalmai.errors import NalmaiError
from nalmai.models import B50Image


class BasicB50Renderer:
    width = 1600
    margin = 36
    card_height = 70

    async def render(self, payload: dict[str, Any]) -> B50Image:
        nickname = payload.get("nickname")
        rating = payload.get("rating")
        charts = payload.get("charts")
        if not isinstance(nickname, str) or not isinstance(rating, (int, float)):
            raise NalmaiError("B50_SCHEMA_ERROR", "B50 渲染数据缺少玩家信息。")
        if not isinstance(charts, dict):
            raise NalmaiError("B50_SCHEMA_ERROR", "B50 渲染数据缺少 charts。")
        sd = charts.get("sd")
        dx = charts.get("dx")
        if not isinstance(sd, list) or not isinstance(dx, list):
            raise NalmaiError("B50_SCHEMA_ERROR", "B50 渲染数据缺少 sd/dx 列表。")

        entries = [("SD", item) for item in sd] + [("DX", item) for item in dx]
        height = 140 + max(1, len(entries)) * self.card_height + self.margin
        image = Image.new("RGB", (self.width, height), "#101522")
        draw = ImageDraw.Draw(image)
        font = ImageFont.load_default()

        draw.text((self.margin, 28), "Nalmai B50", fill="#7ce8ff", font=font)
        draw.text(
            (self.margin, 62),
            f"Player: {self._ascii(nickname)}    Rating: {rating}",
            fill="white",
            font=font,
        )

        y = 110
        for index, (section, item) in enumerate(entries, start=1):
            if not isinstance(item, dict):
                raise NalmaiError("B50_SCHEMA_ERROR", "B50 谱面条目不是对象。")
            title = item.get("title")
            achievements = item.get("achievements")
            ra = item.get("ra")
            chart_type = item.get("type")
            if (
                not isinstance(title, str)
                or not isinstance(achievements, (int, float))
                or not isinstance(ra, (int, float))
                or not isinstance(chart_type, str)
            ):
                raise NalmaiError("B50_SCHEMA_ERROR", "B50 谱面条目字段不完整。")

            card_color = "#1b263b" if index % 2 else "#22324f"
            draw.rounded_rectangle(
                (self.margin, y, self.width - self.margin, y + 54),
                radius=8,
                fill=card_color,
            )
            line = (
                f"{index:02d} [{section}/{self._ascii(chart_type)}] "
                f"{self._ascii(title)} | {achievements:.4f}% | RA {ra}"
            )
            draw.text((self.margin + 18, y + 20), line, fill="#f5f7ff", font=font)
            y += self.card_height

        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return B50Image(content=buffer.getvalue())

    @staticmethod
    def _ascii(value: str) -> str:
        safe = value.encode("ascii", "replace").decode("ascii")
        return safe[:100]

