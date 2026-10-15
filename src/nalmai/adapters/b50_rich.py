from __future__ import annotations

import asyncio
import hashlib
import io
import os
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from nalmai.errors import NalmaiError
from nalmai.models import B50Image, LocalPlayerProfile
from nalmai.ports import DivingFishClient


class RichB50Renderer:
    width = 1600
    columns = 5
    margin = 30
    gap = 12
    card_height = 220
    section_header_height = 58
    header_height = 300

    difficulty_colors = {
        0: "#42c96b",
        1: "#f3b82f",
        2: "#ef5d6f",
        3: "#9654d8",
        4: "#d9c8f7",
    }

    difficulty_names = {
        0: "BASIC",
        1: "ADVANCED",
        2: "EXPERT",
        3: "MASTER",
        4: "Re:MASTER",
    }

    difficulty_card_gradients = {
        0: ("#e8fff0", "#eefbff"),
        1: ("#fff7d9", "#fff0e8"),
        2: ("#ffe9ef", "#fff2f7"),
        3: ("#f1e8ff", "#e9f3ff"),
        4: ("#eee8ff", "#f7edff"),
    }

    rate_labels = {
        "d": "D",
        "c": "C",
        "b": "B",
        "bb": "BB",
        "bbb": "BBB",
        "a": "A",
        "aa": "AA",
        "aaa": "AAA",
        "s": "S",
        "sp": "S+",
        "ss": "SS",
        "ssp": "SS+",
        "sss": "SSS",
        "sssp": "SSS+",
    }

    rate_colors = {
        "d": "#77788f",
        "c": "#77788f",
        "b": "#77788f",
        "bb": "#77788f",
        "bbb": "#77788f",
        "a": "#3f9f75",
        "aa": "#3f9f75",
        "aaa": "#d28a2f",
        "s": "#2f9ac4",
        "sp": "#2386be",
        "ss": "#6e59c9",
        "ssp": "#8052d0",
        "sss": "#b550d3",
        "sssp": "#e68b2d",
    }

    fc_labels = {
        "fc": "FC",
        "fcp": "FC+",
        "ap": "AP",
        "app": "AP+",
    }

    fc_colors = {
        "fc": "#2bae66",
        "fcp": "#5fbd35",
        "ap": "#e6a52e",
        "app": "#ed7f35",
    }

    fs_labels = {
        "sync": "SYNC",
        "fs": "FS",
        "fsp": "FS+",
        "fsd": "FSD",
        "fdx": "FSD",
        "fsdp": "FSD+",
        "fdxp": "FSD+",
    }

    fs_colors = {
        "sync": "#2994cf",
        "fs": "#2994cf",
        "fsp": "#247fc1",
        "fsd": "#7654c8",
        "fdx": "#7654c8",
        "fsdp": "#c354b8",
        "fdxp": "#c354b8",
    }

    chart_icon_files = {
        "DX": "music_dx.png",
        "SD": "music_standard.png",
    }

    rate_icon_files = {
        "d": "music_icon_d.png",
        "c": "music_icon_c.png",
        "b": "music_icon_b.png",
        "bbb": "music_icon_bbb.png",
        "a": "music_icon_a.png",
        "aa": "music_icon_aa.png",
        "aaa": "music_icon_aaa.png",
        "s": "music_icon_s.png",
        "sp": "music_icon_sp.png",
        "ss": "music_icon_ss.png",
        "ssp": "music_icon_ssp.png",
        "sss": "music_icon_sss.png",
        "sssp": "music_icon_sssp.png",
    }

    fc_icon_files = {
        "fc": "music_icon_fc.png",
        "fcp": "music_icon_fcp.png",
        "ap": "music_icon_ap.png",
        "app": "music_icon_app.png",
    }

    fs_icon_files = {
        "sync": "music_icon_sync.png",
        "fs": "music_icon_fs.png",
        "fsp": "music_icon_fsp.png",
        "fsd": "music_icon_fdx.png",
        "fdx": "music_icon_fdx.png",
    }

    def __init__(self, assets: DivingFishClient) -> None:
        self._assets = assets
        self._ui_icon_cache: dict[str, Image.Image | None] = {}
        shared_root = os.getenv("NALMAI_SHARED_ASSET_DIR", "").strip()
        self._shared_asset_root = Path(shared_root) if shared_root else None
        self._shared_art_cache: dict[Path, Image.Image | None] = {}

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
        if not all(isinstance(item, dict) for item in sd + dx):
            raise NalmaiError("B50_SCHEMA_ERROR", "B50 谱面条目不是对象。")

        music_data = await self._assets.get_music_data()
        music_map = self._music_map(music_data)
        song_ids = sorted({
            song_id
            for item in sd + dx
            if isinstance((song_id := item.get("song_id")), int)
        })
        cover_contents = await asyncio.gather(
            *(self._assets.get_cover(song_id) for song_id in song_ids)
        )
        covers = dict(zip(song_ids, cover_contents, strict=True))

        sd_rows = max(1, (len(sd) + self.columns - 1) // self.columns)
        dx_rows = max(1, (len(dx) + self.columns - 1) // self.columns)
        header_height = (
            self.header_height
            if isinstance(payload.get("local_player_profile"), LocalPlayerProfile)
            else 205
        )
        height = (
            header_height
            + self.section_header_height * 2
            + (sd_rows + dx_rows) * self.card_height
            + self.gap * 2
            + 64
        )
        image = self._background(height)
        draw = ImageDraw.Draw(image)
        fonts = self._fonts()
        self._draw_header(image, draw, payload, music_map, fonts)

        y = header_height
        y = self._draw_section(
            image,
            draw,
            "B35  旧版本最佳成绩",
            sd,
            y,
            music_map,
            covers,
            fonts,
        )
        y += self.gap * 2
        y = self._draw_section(
            image,
            draw,
            "B15  当前版本最佳成绩",
            dx,
            y,
            music_map,
            covers,
            fonts,
        )
        draw.text(
            (self.width // 2, y + 18),
            "NALMAI AURORA  ·  成绩与 FC/FS：Diving-Fish  ·  PC 与 DX 星级：本机微信授权  ·  — 表示未取得",
            fill="#453f68",
            font=fonts["small"],
            anchor="ma",
        )

        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG", optimize=True)
        return B50Image(content=buffer.getvalue(), filename="nalmai-b50-rich.png")

    def _draw_header(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        payload: dict[str, Any],
        music_map: dict[tuple[int, str], dict[str, Any]],
        fonts: dict[str, ImageFont.FreeTypeFont | ImageFont.ImageFont],
    ) -> None:
        profile = payload.get("local_player_profile")
        if isinstance(profile, LocalPlayerProfile):
            self._draw_profile_header(
                image,
                draw,
                payload,
                profile,
                music_map,
                fonts,
            )
            return
        nickname = str(payload["nickname"])
        rating = int(payload["rating"])
        additional = payload.get("additional_rating")
        plate = payload.get("plate")
        charts = payload.get("charts")
        sd = charts.get("sd", []) if isinstance(charts, dict) else []
        dx = charts.get("dx", []) if isinstance(charts, dict) else []
        sd_rating = sum(
            int(item.get("ra", 0)) for item in sd if isinstance(item, dict)
        )
        dx_rating = sum(
            int(item.get("ra", 0)) for item in dx if isinstance(item, dict)
        )
        all_charts = [item for item in sd + dx if isinstance(item, dict)]
        play_count_synced = sum(
            isinstance(item.get("play_count"), int) for item in all_charts
        )
        dx_score_available = sum(
            isinstance(item.get("dxScore"), int) for item in all_charts
        )
        current_version = self._current_version(dx, music_map)
        display_avatar = payload.get("display_avatar")
        avatar = self._asset_image(
            display_avatar if isinstance(display_avatar, bytes) else b""
        )
        if avatar is None:
            avatar = self._shared_asset("icon", nickname)
        shared_nameplate = self._shared_asset("nameplate", nickname)
        shared_frame = self._shared_asset("frame", nickname)
        brand_right = 232 if avatar is not None else 300
        identity_x = 370 if avatar is not None else 336
        self._draw_shadow(
            image,
            (self.margin, 20, self.width - self.margin, 174),
            radius=30,
            blur=18,
            offset=(0, 10),
        )
        self._draw_gradient_box(
            image,
            (self.margin, 20, self.width - self.margin, 174),
            "#f4efff",
            "#e7f8ff",
            radius=30,
        )
        if shared_frame is not None:
            self._composite_art_in_box(
                image,
                shared_frame,
                (805, 25, 1215, 169),
                opacity=82,
                radius=26,
            )
        draw.rounded_rectangle(
            (self.margin, 20, self.width - self.margin, 174),
            radius=30,
            outline="#aa98e8",
            width=3,
        )
        draw.rounded_rectangle(
            (48, 37, brand_right, 156),
            radius=24,
            fill="#8c58d9",
            outline="#ffffff",
            width=4,
        )
        partner = self._shared_asset("partner", nickname)
        if partner is not None:
            self._composite_art_in_box(
                image,
                partner,
                (52, 41, brand_right - 4, 152),
                opacity=150,
                radius=20,
            )
        brand_center = (48 + brand_right) // 2
        draw.text(
            (brand_center, 52),
            "Nalmai",
            fill="white",
            font=fonts["brand"],
            anchor="ma",
            stroke_width=2,
            stroke_fill="#56329b",
        )
        draw.text(
            (brand_center, 123),
            "BEST 50",
            fill="#c9fbff",
            font=fonts["subtitle"],
            anchor="ma",
            stroke_width=1,
            stroke_fill="#56329b",
        )
        if avatar is not None:
            avatar = self._rounded_image(avatar, (100, 100), radius=20)
            image.alpha_composite(avatar, (244, 47))
            draw.rounded_rectangle(
                (243, 46, 345, 148),
                radius=21,
                outline="#ffffff",
                width=4,
            )
        if shared_nameplate is not None:
            nameplate_box = (identity_x - 10, 31, identity_x + 430, 99)
            self._composite_art_in_box(
                image,
                shared_nameplate,
                nameplate_box,
                opacity=235,
                radius=14,
            )
            draw.text(
                ((nameplate_box[0] + nameplate_box[2]) // 2, 65),
                nickname,
                fill="#ffffff",
                font=fonts["name"],
                anchor="mm",
                stroke_width=3,
                stroke_fill="#31284d",
            )
        else:
            draw.text(
                (identity_x, 43),
                nickname,
                fill="#27253d",
                font=fonts["name"],
            )
        draw.text(
            (identity_x, 105),
            f"でらっくす RATING  {rating:05d}",
            fill="#ee7a31",
            font=fonts["rating"],
        )
        draw.rounded_rectangle(
            (identity_x, 139, 790, 167),
            radius=12,
            fill="#fff2b7",
            outline="#f5b332",
            width=2,
        )
        draw.text(
            ((identity_x + 790) // 2, 153),
            f"B35: {sd_rating}  +  B15: {dx_rating}  =  {rating}",
            fill="#4d4020",
            font=fonts["small_bold"],
            anchor="mm",
        )
        meta: list[str] = []
        if isinstance(plate, str) and plate:
            meta.append(plate)
        if isinstance(additional, (int, float)):
            meta.append(f"段位 {int(additional)}")
        if meta:
            draw.text(
                (self.width - 62, 55),
                " · ".join(meta),
                fill="#4d4a6a",
                font=fonts["body"],
                anchor="ra",
            )
        draw.rounded_rectangle(
            (1010, 91, self.width - 54, 137),
            radius=16,
            fill="#f2ecff",
            outline="#c8b8ed",
            width=2,
        )
        draw.text(
            (1030, 114),
            f"B35 {len(sd):02d}  ·  B15 {len(dx):02d}",
            fill="#5a438d",
            font=fonts["small_bold"],
            anchor="lm",
        )
        draw.text(
            (self.width - 72, 114),
            f"PC {play_count_synced}/{len(all_charts)}  ·  DX SCORE {dx_score_available}/{len(all_charts)}",
            fill="#5a438d",
            font=fonts["small_bold"],
            anchor="rm",
        )
        draw.text(
            (self.width - 62, 147),
            f"CURRENT · {current_version}",
            fill="#7952c7",
            font=fonts["small_bold"],
            anchor="ra",
        )

    def _draw_profile_header(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        payload: dict[str, Any],
        profile: LocalPlayerProfile,
        music_map: dict[tuple[int, str], dict[str, Any]],
        fonts: dict[str, ImageFont.FreeTypeFont | ImageFont.ImageFont],
    ) -> None:
        charts = payload.get("charts")
        sd = charts.get("sd", []) if isinstance(charts, dict) else []
        dx = charts.get("dx", []) if isinstance(charts, dict) else []
        sd_rating = sum(
            int(item.get("ra", 0)) for item in sd if isinstance(item, dict)
        )
        dx_rating = sum(
            int(item.get("ra", 0)) for item in dx if isinstance(item, dict)
        )
        all_charts = [item for item in sd + dx if isinstance(item, dict)]
        play_count_synced = sum(
            isinstance(item.get("play_count"), int) for item in all_charts
        )
        current_version = self._current_version(dx, music_map)
        nickname = payload.get("nickname")

        self._draw_shadow(
            image,
            (self.margin, 20, self.width - self.margin, 278),
            radius=30,
            blur=20,
            offset=(0, 12),
        )
        self._draw_gradient_box(
            image,
            (self.margin, 20, self.width - self.margin, 278),
            "#f4efff",
            "#e7f8ff",
            radius=30,
        )
        draw.rounded_rectangle(
            (self.margin, 20, self.width - self.margin, 278),
            radius=30,
            outline="#aa98e8",
            width=3,
        )
        frame = self._asset_image(profile.frame)
        if frame is not None:
            frame = self._contain_image(frame, (735, 210))
            alpha = frame.getchannel("A").point(lambda value: value * 2 // 5)
            frame.putalpha(alpha)
            image.alpha_composite(frame, (815, 33))

        logo = self._asset_image(profile.version_logo)
        if logo is not None:
            image.alpha_composite(self._contain_image(logo, (150, 75)), (48, 35))
        draw.text(
            (123, 130),
            current_version,
            fill="#7952c7",
            font=fonts["micro_bold"],
            anchor="ma",
        )

        display_avatar = payload.get("display_avatar")
        avatar_content = (
            display_avatar if isinstance(display_avatar, bytes) else profile.avatar
        )
        avatar = self._asset_image(avatar_content)
        if avatar is None:
            avatar = self._shared_asset("icon", profile.player_name)
        if avatar is not None:
            avatar = self._rounded_image(avatar, (112, 112), radius=20)
            image.alpha_composite(avatar, (48, 153))
            draw.rounded_rectangle(
                (47, 152, 161, 266),
                radius=21,
                outline="#ffffff",
                width=4,
            )

        nameplate = self._asset_image(profile.nameplate)
        if nameplate is not None:
            image.alpha_composite(
                self._contain_image(nameplate, (580, 104)),
                (205, 42),
            )
        draw.text(
            (485, 91),
            profile.player_name,
            fill="#ffffff",
            font=fonts["name"],
            anchor="mm",
            stroke_width=3,
            stroke_fill="#32294f",
        )
        draw.rounded_rectangle(
            (185, 151, 790, 190),
            radius=14,
            fill=self._title_color(profile.title_rarity),
            outline="#ffffff",
            width=2,
        )
        draw.text(
            (203, 170),
            profile.title_text,
            fill="#ffffff",
            font=fonts["body"],
            anchor="lm",
        )
        draw.text(
            (774, 170),
            profile.nameplate_name,
            fill="#ffffff",
            font=fonts["small_bold"],
            anchor="rm",
        )

        course = self._asset_image(profile.course_rank)
        class_rank = self._asset_image(profile.class_rank)
        if course is not None:
            image.alpha_composite(self._contain_image(course, (128, 46)), (184, 202))
        if class_rank is not None:
            image.alpha_composite(
                self._contain_image(class_rank, (128, 46)), (322, 202)
            )
        draw.rounded_rectangle(
            (462, 206, 596, 246),
            radius=13,
            fill="#fff2b7",
            outline="#f5b332",
            width=2,
        )
        draw.text(
            (529, 226),
            f"★ × {profile.star_count}",
            fill="#8a5d00",
            font=fonts["small_bold"],
            anchor="mm",
        )
        draw.text(
            (610, 218),
            profile.avatar_name,
            fill="#55506b",
            font=fonts["micro"],
        )
        draw.text(
            (610, 239),
            profile.frame_name,
            fill="#7952c7",
            font=fonts["micro_bold"],
        )

        draw.rounded_rectangle(
            (820, 47, 1535, 112),
            radius=20,
            fill="#ffffffdf",
            outline="#f0a13c",
            width=3,
        )
        rating_base = self._asset_image(profile.rating_base)
        if rating_base is not None:
            image.alpha_composite(
                self._contain_image(rating_base, (278, 58)),
                (838, 50),
            )
        draw.text(
            (1135, 79),
            f"{profile.rating:05d}",
            fill="#ee7a31",
            font=fonts["rating"],
            anchor="lm",
            stroke_width=1,
            stroke_fill="#ffffff",
        )
        if isinstance(nickname, str) and nickname and nickname != profile.player_name:
            draw.text(
                (1515, 79),
                f"Diving-Fish: {nickname}",
                fill="#5a438d",
                font=fonts["small_bold"],
                anchor="rm",
            )

        draw.rounded_rectangle(
            (820, 126, 1535, 257),
            radius=20,
            fill="#ffffffdf",
            outline="#c8b8ed",
            width=2,
        )
        draw.text(
            (845, 151),
            f"B35 {len(sd):02d}  ·  B15 {len(dx):02d}",
            fill="#5a438d",
            font=fonts["small_bold"],
            anchor="lm",
        )
        draw.text(
            (1510, 151),
            f"PC {play_count_synced}/{len(all_charts)}",
            fill="#5a438d",
            font=fonts["small_bold"],
            anchor="rm",
        )
        draw.text(
            (845, 184),
            f"B35: {sd_rating}  +  B15: {dx_rating}",
            fill="#4d4020",
            font=fonts["small_bold"],
            anchor="lm",
        )
        draw.text(
            (1510, 184),
            f"TOTAL {sd_rating + dx_rating}",
            fill="#ee7a31",
            font=fonts["small_bold"],
            anchor="rm",
        )
        draw.text(
            (845, 219),
            profile.nameplate_description,
            fill="#514b68",
            font=fonts["micro"],
            anchor="lm",
        )
        draw.text(
            (1510, 239),
            f"资料更新 {profile.updated_at.astimezone().strftime('%Y-%m-%d %H:%M')}",
            fill="#777188",
            font=fonts["micro"],
            anchor="rm",
        )

    @staticmethod
    def _title_color(rarity: str) -> str:
        return {
            "Rainbow": "#d351c9",
            "Gold": "#c99928",
            "Silver": "#8c99aa",
            "Bronze": "#a96945",
            "Normal": "#586b87",
        }.get(rarity, "#586b87")

    @staticmethod
    def _asset_image(content: bytes) -> Image.Image | None:
        try:
            with Image.open(io.BytesIO(content)) as source:
                return source.convert("RGBA")
        except (OSError, ValueError):
            return None

    @staticmethod
    def _contain_image(source: Image.Image, size: tuple[int, int]) -> Image.Image:
        contained = ImageOps.contain(source, size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", size, (255, 255, 255, 0))
        canvas.alpha_composite(
            contained,
            ((size[0] - contained.width) // 2, (size[1] - contained.height) // 2),
        )
        return canvas

    @staticmethod
    def _rounded_image(
        source: Image.Image,
        size: tuple[int, int],
        *,
        radius: int,
    ) -> Image.Image:
        rounded = ImageOps.fit(source.convert("RGBA"), size, Image.Resampling.LANCZOS)
        mask = Image.new("L", size, 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, size[0] - 1, size[1] - 1),
            radius=radius,
            fill=255,
        )
        rounded.putalpha(mask)
        return rounded

    def _draw_section(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        title: str,
        entries: list[dict[str, Any]],
        y: int,
        music_map: dict[tuple[int, str], dict[str, Any]],
        covers: dict[int, bytes | None],
        fonts: dict[str, ImageFont.FreeTypeFont | ImageFont.ImageFont],
    ) -> int:
        rows = max(1, (len(entries) + self.columns - 1) // self.columns)
        panel_bottom = y + self.section_header_height + rows * self.card_height - 2
        self._draw_shadow(
            image,
            (self.margin - 8, y - 8, self.width - self.margin + 8, panel_bottom),
            radius=24,
            blur=18,
            offset=(0, 8),
            color=(28, 18, 72, 55),
        )
        panel_fill = "#e8f2ff" if title.startswith("B35") else "#fff0f5"
        draw.rounded_rectangle(
            (self.margin - 8, y - 8, self.width - self.margin + 8, panel_bottom),
            radius=24,
            fill=panel_fill,
            outline="#ffffff",
            width=2,
        )
        header_colors = (
            ("#6248c9", "#31aeca")
            if title.startswith("B35")
            else ("#d95e84", "#ee9b45")
        )
        self._draw_gradient_box(
            image,
            (self.margin, y, self.width - self.margin, y + 44),
            header_colors[0],
            header_colors[1],
            radius=18,
        )
        section_rating = sum(
            int(item.get("ra", 0)) for item in entries if isinstance(item, dict)
        )
        draw.text(
            (self.margin + 18, y + 22),
            title,
            fill="white",
            font=fonts["section"],
            anchor="lm",
        )
        draw.text(
            (self.width - self.margin - 18, y + 22),
            f"{len(entries)} CHARTS  ·  RA {section_rating}",
            fill="white",
            font=fonts["small_bold"],
            anchor="rm",
        )
        y += self.section_header_height
        card_width = (
            self.width - 2 * self.margin - (self.columns - 1) * self.gap
        ) // self.columns
        for index, item in enumerate(entries, start=1):
            row, column = divmod(index - 1, self.columns)
            x = self.margin + column * (card_width + self.gap)
            card_y = y + row * self.card_height
            self._draw_card(
                image,
                draw,
                item,
                index,
                x,
                card_y,
                card_width,
                music_map,
                covers,
                fonts,
            )
        return y + rows * self.card_height

    def _draw_card(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        item: dict[str, Any],
        index: int,
        x: int,
        y: int,
        width: int,
        music_map: dict[tuple[int, str], dict[str, Any]],
        covers: dict[int, bytes | None],
        fonts: dict[str, ImageFont.FreeTypeFont | ImageFont.ImageFont],
    ) -> None:
        required = {
            "title": str,
            "achievements": (int, float),
            "ra": (int, float),
            "type": str,
            "song_id": int,
            "level_index": int,
            "ds": (int, float),
            "dxScore": int,
            "rate": str,
        }
        for key, expected in required.items():
            if not isinstance(item.get(key), expected):
                raise NalmaiError(
                    "B50_SCHEMA_ERROR", f"B50 谱面条目缺少有效字段 {key}。"
                )

        level_index = item["level_index"]
        color = self.difficulty_colors.get(level_index, "#77788f")
        card_bottom = y + self.card_height - self.gap
        self._draw_shadow(
            image,
            (x, y, x + width, card_bottom),
            radius=16,
            blur=8,
            offset=(0, 5),
            color=(42, 32, 82, 45),
        )
        card_gradient = self.difficulty_card_gradients.get(
            level_index,
            ("#f0eef8", "#edf6ff"),
        )
        self._draw_gradient_box(
            image,
            (x, y, x + width, card_bottom),
            card_gradient[0],
            card_gradient[1],
            radius=16,
        )
        draw.rounded_rectangle(
            (x, y, x + width, card_bottom),
            radius=16,
            outline="#d2c8e8",
            width=2,
        )
        draw.rounded_rectangle(
            (x, y, x + 7, card_bottom),
            radius=4,
            fill=color,
        )
        draw.rounded_rectangle(
            (x + 7, y + 2, x + width - 2, y + 32),
            radius=11,
            fill=color,
        )
        level_label = item.get("level_label")
        level = item.get("level")
        difficulty = self.difficulty_names.get(level_index, "UNKNOWN")
        if isinstance(level_label, str) and level_label:
            difficulty = level_label.upper().replace("RE:MASTER", "Re:MASTER")
        draw.text(
            (x + 12, y + 18),
            f"No.{index:02d}",
            fill="white",
            font=fonts["tiny"],
            anchor="lm",
        )
        level_text = f"{difficulty}  {level}" if isinstance(level, str) else difficulty
        draw.text(
            (x + width - 12, y + 18),
            level_text,
            fill="#4b315d" if level_index == 4 else "white",
            font=fonts["tiny"],
            anchor="rm",
        )

        song_id = item["song_id"]
        chart_type = item["type"].upper()
        metadata = music_map.get((song_id, chart_type))
        cover = self._cover_image(covers.get(song_id), song_id)
        image.alpha_composite(cover, (x + 9, y + 42))
        draw.rounded_rectangle(
            (x + 8, y + 41, x + 90, y + 123),
            radius=8,
            outline="#ffffff",
            width=2,
        )

        text_x = x + 109
        title = self._fit_text(
            draw,
            item["title"],
            fonts["card_title"],
            width - 119,
        )
        draw.text(
            (text_x, y + 41),
            title,
            fill="#312d49",
            font=fonts["card_title"],
        )
        draw.text(
            (text_x, y + 68),
            f"{item['achievements']:.4f}%",
            fill="#7141bc",
            font=fonts["achievement"],
        )
        draw.text(
            (text_x, y + 106),
            f"{item['ds']:.1f}  →  {int(item['ra'])}",
            fill="#36324e",
            font=fonts["tiny"],
        )

        max_dx = self._max_dx_score(metadata, level_index)
        local_star = item.get("dx_star")
        star = (
            local_star
            if isinstance(local_star, int) and local_star >= 0
            else self._dx_star(item["dxScore"], max_dx)
        )
        max_dx_text = str(max_dx) if max_dx is not None else "—"
        play_count = item.get("play_count")
        pc_text = str(play_count) if isinstance(play_count, int) else "—"
        draw.text(
            (text_x, y + 130),
            f"DX {item['dxScore']}/{max_dx_text}   PC:{pc_text}",
            fill="#57516f",
            font=fonts["micro"],
        )
        self._draw_stars(
            draw,
            x + 10,
            y + 155,
            star,
            fonts["star"],
        )

        badge_x = x + 92
        badge_x = self._draw_status_badge(
            image,
            draw,
            badge_x,
            y + 158,
            self.chart_icon_files.get(chart_type),
            chart_type,
            "#2f9ac4" if chart_type == "DX" else "#e98b32",
            fonts["badge"],
        )
        rate_key = item["rate"].casefold()
        badge_x = self._draw_status_badge(
            image,
            draw,
            badge_x,
            y + 158,
            self.rate_icon_files.get(rate_key),
            self._rate_label(item["rate"]),
            self.rate_colors.get(rate_key, "#77788f"),
            fonts["badge"],
        )
        fc = item.get("fc")
        if isinstance(fc, str) and fc:
            fc_key = fc.casefold()
            badge_x = self._draw_status_badge(
                image,
                draw,
                badge_x,
                y + 158,
                self.fc_icon_files.get(fc_key),
                self.fc_labels.get(fc_key, fc.upper()),
                self.fc_colors.get(fc_key, "#77788f"),
                fonts["badge"],
            )
        fs = item.get("fs")
        if isinstance(fs, str) and fs:
            fs_key = fs.casefold()
            self._draw_status_badge(
                image,
                draw,
                badge_x,
                y + 158,
                self.fs_icon_files.get(fs_key),
                self.fs_labels.get(fs_key, fs.upper()),
                self.fs_colors.get(fs_key, "#77788f"),
                fonts["badge"],
            )

        version = self._fit_text(
            draw,
            self._version(metadata),
            fonts["micro"],
            width - 105,
        )
        draw.text(
            (x + 10, y + 201),
            version,
            fill="#716b86",
            font=fonts["micro"],
            anchor="lm",
        )
        draw.text(
            (x + width - 10, y + 201),
            f"ID {song_id}",
            fill=color,
            font=fonts["micro_bold"],
            anchor="rm",
        )

    @staticmethod
    def _music_map(
        music_data: list[dict[str, Any]],
    ) -> dict[tuple[int, str], dict[str, Any]]:
        result: dict[tuple[int, str], dict[str, Any]] = {}
        for item in music_data:
            song_id = item.get("id")
            chart_type = item.get("type")
            if isinstance(song_id, (int, str)) and str(song_id).isdigit() and isinstance(chart_type, str):
                result[(int(song_id), chart_type.upper())] = item
        return result

    @classmethod
    def _current_version(
        cls,
        entries: list[dict[str, Any]],
        music_map: dict[tuple[int, str], dict[str, Any]],
    ) -> str:
        versions: list[str] = []
        for item in entries:
            song_id = item.get("song_id")
            chart_type = item.get("type")
            if not isinstance(song_id, int) or not isinstance(chart_type, str):
                continue
            version = cls._version(music_map.get((song_id, chart_type.upper())))
            if version != "版本未知":
                versions.append(version)
        if not versions:
            return "当前版本"
        return Counter(versions).most_common(1)[0][0]

    @staticmethod
    def _max_dx_score(metadata: dict[str, Any] | None, level_index: int) -> int | None:
        if not metadata:
            return None
        charts = metadata.get("charts")
        if not isinstance(charts, list) or not 0 <= level_index < len(charts):
            return None
        chart = charts[level_index]
        notes = chart.get("notes") if isinstance(chart, dict) else None
        if not isinstance(notes, list) or not all(isinstance(note, int) for note in notes):
            return None
        return sum(notes) * 3

    @staticmethod
    def _version(metadata: dict[str, Any] | None) -> str:
        if not metadata:
            return "版本未知"
        basic = metadata.get("basic_info")
        version = basic.get("from") if isinstance(basic, dict) else None
        return version if isinstance(version, str) and version else "版本未知"

    @staticmethod
    def _dx_star(dx_score: int, max_dx_score: int | None) -> int | None:
        if not max_dx_score or max_dx_score <= 0:
            return None
        percentage = dx_score / max_dx_score * 100
        for index, threshold in enumerate((85, 90, 93, 95, 97)):
            if percentage <= threshold:
                return index
        return 5

    @classmethod
    def _rate_label(cls, rate: str) -> str:
        return cls.rate_labels.get(rate.casefold(), rate.upper())

    def _draw_status_badge(
        self,
        image: Image.Image,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        icon_filename: str | None,
        fallback_label: str,
        fallback_color: str,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    ) -> int:
        icon = self._official_ui_icon(icon_filename)
        if icon is None:
            return self._draw_badge(
                draw,
                x,
                y,
                fallback_label,
                fallback_color,
                font,
            )
        rendered = ImageOps.contain(icon, (82, 23), Image.Resampling.LANCZOS)
        image.alpha_composite(rendered, (x, y + (23 - rendered.height) // 2))
        return x + rendered.width + 4

    def _official_ui_icon(self, filename: str | None) -> Image.Image | None:
        if filename is None:
            return None
        if filename in self._ui_icon_cache:
            return self._ui_icon_cache[filename]
        path = (
            Path(__file__).resolve().parents[1]
            / "assets"
            / "wahlap_status"
            / filename
        )
        try:
            with Image.open(path) as source:
                result = source.convert("RGBA")
        except (OSError, ValueError):
            result = None
        self._ui_icon_cache[filename] = result
        return result

    def _shared_asset(self, category: str, seed: str) -> Image.Image | None:
        if self._shared_asset_root is None or category not in {
            "frame",
            "icon",
            "nameplate",
            "partner",
        }:
            return None
        directory = self._shared_asset_root / category
        if not directory.is_dir():
            return None
        paths = sorted(
            path
            for path in directory.iterdir()
            if path.is_file()
            and path.suffix.casefold() in {".gif", ".jpg", ".jpeg", ".png", ".webp"}
        )
        if not paths:
            return None
        digest = hashlib.sha256(seed.encode("utf-8")).digest()
        start = int.from_bytes(digest[:8], "big") % len(paths)
        for offset in range(len(paths)):
            path = paths[(start + offset) % len(paths)]
            if path in self._shared_art_cache:
                cached = self._shared_art_cache[path]
                if cached is not None:
                    return cached.copy()
                continue
            try:
                with Image.open(path) as source:
                    result = source.convert("RGBA")
                if result.getchannel("A").getbbox() is None:
                    result = None
            except (OSError, ValueError):
                result = None
            self._shared_art_cache[path] = result
            if result is not None:
                return result.copy()
        return None

    @staticmethod
    def _composite_art_in_box(
        image: Image.Image,
        source: Image.Image,
        box: tuple[int, int, int, int],
        *,
        opacity: int,
        radius: int,
    ) -> None:
        left, top, right, bottom = box
        size = (right - left, bottom - top)
        rendered = ImageOps.contain(source.convert("RGBA"), size, Image.Resampling.LANCZOS)
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        layer.alpha_composite(
            rendered,
            ((size[0] - rendered.width) // 2, size[1] - rendered.height),
        )
        scaled_alpha = layer.getchannel("A").point(
            lambda value: value * min(255, max(0, opacity)) // 255
        )
        rounded_mask = Image.new("L", size, 0)
        ImageDraw.Draw(rounded_mask).rounded_rectangle(
            (0, 0, size[0] - 1, size[1] - 1),
            radius=radius,
            fill=255,
        )
        layer.putalpha(ImageChops.multiply(scaled_alpha, rounded_mask))
        image.alpha_composite(layer, (left, top))

    @staticmethod
    def _draw_badge(
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        label: str,
        color: str,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    ) -> int:
        text_width = int(draw.textlength(label, font=font))
        width = max(30, text_width + 12)
        draw.rounded_rectangle(
            (x, y, x + width, y + 23),
            radius=9,
            fill=color,
            outline="#ffffff",
            width=2,
        )
        draw.text(
            (x + width // 2, y + 11),
            label,
            fill="white",
            font=font,
            anchor="mm",
        )
        return x + width + 4

    @staticmethod
    def _draw_stars(
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        star: int | None,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    ) -> None:
        if star is None:
            draw.text((x, y), "☆☆☆☆☆", fill="#b9b4c7", font=font)
            return
        value = min(5, max(0, star))
        draw.text(
            (x, y),
            "★" * value,
            fill="#73c84c",
            font=font,
            stroke_width=1,
            stroke_fill="#ffffff",
        )
        if value < 5:
            offset = draw.textlength("★" * value, font=font)
            draw.text(
                (x + offset, y),
                "☆" * (5 - value),
                fill="#b9b4c7",
                font=font,
            )

    @staticmethod
    def _cover_image(content: bytes | None, song_id: int) -> Image.Image:
        if content:
            try:
                with Image.open(io.BytesIO(content)) as source:
                    return ImageOps.fit(source.convert("RGBA"), (80, 80), Image.Resampling.LANCZOS)
            except (OSError, ValueError):
                pass
        fallback = Image.new("RGBA", (80, 80), "#d8d2ee")
        draw = ImageDraw.Draw(fallback)
        draw.text((40, 30), "NO", fill="#6c6388", anchor="mm")
        draw.text((40, 51), str(song_id), fill="#6c6388", anchor="mm")
        return fallback

    @staticmethod
    def _draw_shadow(
        image: Image.Image,
        box: tuple[int, int, int, int],
        *,
        radius: int,
        blur: int,
        offset: tuple[int, int],
        color: tuple[int, int, int, int] = (31, 20, 76, 70),
    ) -> None:
        left, top, right, bottom = box
        dx, dy = offset
        padding = blur * 3
        width = right - left
        height = bottom - top
        layer = Image.new(
            "RGBA",
            (width + padding * 2 + abs(dx), height + padding * 2 + abs(dy)),
            (0, 0, 0, 0),
        )
        layer_draw = ImageDraw.Draw(layer)
        layer_draw.rounded_rectangle(
            (
                padding + max(dx, 0),
                padding + max(dy, 0),
                padding + max(dx, 0) + width,
                padding + max(dy, 0) + height,
            ),
            radius=radius,
            fill=color,
        )
        layer = layer.filter(ImageFilter.GaussianBlur(blur))
        image.alpha_composite(layer, (left - padding, top - padding))

    @staticmethod
    def _draw_gradient_box(
        image: Image.Image,
        box: tuple[int, int, int, int],
        start: str,
        end: str,
        *,
        radius: int,
    ) -> None:
        left, top, right, bottom = box
        width = right - left
        height = bottom - top
        start_rgb = tuple(bytes.fromhex(start.removeprefix("#")))
        end_rgb = tuple(bytes.fromhex(end.removeprefix("#")))
        row = Image.new("RGBA", (width, 1))
        row.putdata(
            [
                tuple(
                    round(start_rgb[channel] + (end_rgb[channel] - start_rgb[channel]) * x / max(1, width - 1))
                    for channel in range(3)
                )
                + (255,)
                for x in range(width)
            ]
        )
        gradient = row.resize((width, height))
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, width - 1, height - 1), radius=radius, fill=255
        )
        gradient.putalpha(mask)
        image.alpha_composite(gradient, (left, top))

    @staticmethod
    def _background(height: int) -> Image.Image:
        stops = (
            (0.00, (37, 25, 83)),
            (0.10, (91, 74, 164)),
            (0.24, (192, 211, 246)),
            (0.54, (239, 233, 252)),
            (0.78, (219, 243, 250)),
            (1.00, (248, 229, 242)),
        )

        def color_at(position: float) -> tuple[int, int, int, int]:
            for index in range(len(stops) - 1):
                start_position, start_color = stops[index]
                end_position, end_color = stops[index + 1]
                if position <= end_position:
                    amount = (position - start_position) / max(
                        0.0001, end_position - start_position
                    )
                    return tuple(
                        round(
                            start_color[channel]
                            + (end_color[channel] - start_color[channel]) * amount
                        )
                        for channel in range(3)
                    ) + (255,)
            return stops[-1][1] + (255,)

        column = Image.new("RGBA", (1, height))
        column.putdata(
            [color_at(y / max(1, height - 1)) for y in range(height)]
        )
        image = column.resize((RichB50Renderer.width, height))

        glow = Image.new("RGBA", image.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow, "RGBA")
        glow_draw.ellipse((-260, 80, 720, 1040), fill=(74, 224, 242, 80))
        glow_draw.ellipse((990, -260, 1870, 620), fill=(233, 119, 239, 80))
        glow_draw.ellipse((950, height - 850, 1840, height + 80), fill=(255, 182, 116, 72))
        glow_draw.ellipse((-300, height - 980, 660, height - 20), fill=(105, 198, 247, 65))
        image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(120)))

        pattern = Image.new("RGBA", image.size, (0, 0, 0, 0))
        pattern_draw = ImageDraw.Draw(pattern, "RGBA")
        for x in range(-height, RichB50Renderer.width + height, 128):
            pattern_draw.line(
                (x, 0, x - height, height),
                fill=(255, 255, 255, 24),
                width=2,
            )
        for y in range(340, height, 96):
            pattern_draw.line(
                (0, y, RichB50Renderer.width, y),
                fill=(82, 70, 142, 16),
                width=1,
            )
        for y in range(370, height, 150):
            shift = 54 if (y // 150) % 2 else 0
            for x in range(48 + shift, RichB50Renderer.width, 150):
                size = 5 if (x + y) % 3 else 8
                pattern_draw.polygon(
                    (
                        (x, y - size),
                        (x + size // 3, y - size // 3),
                        (x + size, y),
                        (x + size // 3, y + size // 3),
                        (x, y + size),
                        (x - size // 3, y + size // 3),
                        (x - size, y),
                        (x - size // 3, y - size // 3),
                    ),
                    fill=(255, 255, 255, 108),
                )
        pattern_draw.arc(
            (-300, 80, 650, 1030),
            285,
            70,
            fill=(255, 255, 255, 82),
            width=8,
        )
        pattern_draw.arc(
            (1110, 30, 1780, 700),
            100,
            260,
            fill=(255, 255, 255, 68),
            width=7,
        )
        image.alpha_composite(pattern)
        return image

    @staticmethod
    def _fonts() -> dict[str, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
        bundled = (
            Path(__file__).resolve().parents[1]
            / "assets"
            / "fonts"
            / "ResourceHanRoundedCN-Bold.ttf"
        )
        regular_paths = (
            bundled,
            Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"),
            Path("C:/Windows/Fonts/msyh.ttc"),
            Path("C:/Windows/Fonts/simhei.ttf"),
        )
        bold_paths = (
            bundled,
            Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"),
            Path("C:/Windows/Fonts/msyhbd.ttc"),
            Path("C:/Windows/Fonts/msyh.ttc"),
        )
        regular = next((path for path in regular_paths if path.is_file()), None)
        bold = next((path for path in bold_paths if path.is_file()), regular)

        def load(path: Path | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
            return ImageFont.truetype(str(path), size) if path else ImageFont.load_default()

        return {
            "brand": load(bold, 48),
            "subtitle": load(bold, 25),
            "name": load(bold, 38),
            "rating": load(bold, 32),
            "body": load(regular, 23),
            "section": load(bold, 24),
            "card_title": load(bold, 18),
            "achievement": load(bold, 29),
            "small": load(regular, 18),
            "small_bold": load(bold, 18),
            "tiny": load(bold, 15),
            "micro": load(regular, 14),
            "micro_bold": load(bold, 14),
            "badge": load(bold, 12),
            "star": load(bold, 18),
        }

    @staticmethod
    def _fit_text(
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        max_width: int,
    ) -> str:
        if draw.textlength(text, font=font) <= max_width:
            return text
        suffix = "…"
        value = text
        while value and draw.textlength(value + suffix, font=font) > max_width:
            value = value[:-1]
        return value + suffix
