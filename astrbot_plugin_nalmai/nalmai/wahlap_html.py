from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from lxml import html

from nalmai.models import NormalizedScore


SCORE_CARD_XPATH = (
    "//div[contains(concat(' ', normalize-space(@class), ' '), ' w_450 ') "
    "and contains(concat(' ', normalize-space(@class), ' '), ' m_15 ') "
    "and contains(concat(' ', normalize-space(@class), ' '), ' p_r ') "
    "and contains(concat(' ', normalize-space(@class), ' '), ' f_0 ')]"
)
DIFFICULTY_INDEX = {
    "diff_basic.png": 0,
    "diff_advanced.png": 1,
    "diff_expert.png": 2,
    "diff_master.png": 3,
    "diff_remaster.png": 4,
}
DETAIL_SECTION_IDS = {
    "basic": 0,
    "advanced": 1,
    "expert": 2,
    "master": 3,
    "remaster": 4,
}
CHART_TYPES = {
    "music_standard.png": "SD",
    "music_dx.png": "DX",
}
FC_ICONS = {
    "music_icon_fc.png": "fc",
    "music_icon_fcp.png": "fcp",
    "music_icon_ap.png": "ap",
    "music_icon_app.png": "app",
    "music_icon_back.png": None,
    "music_icon_blank.png": None,
}
FS_ICONS = {
    "music_icon_sync.png": "sync",
    "music_icon_fs.png": "fs",
    "music_icon_fsp.png": "fsp",
    "music_icon_fdx.png": "fsd",
    "music_icon_back.png": None,
    "music_icon_blank.png": None,
}
RATE_ICONS = frozenset(
    {
        "music_icon_d.png",
        "music_icon_c.png",
        "music_icon_b.png",
        "music_icon_bbb.png",
        "music_icon_a.png",
        "music_icon_aa.png",
        "music_icon_aaa.png",
        "music_icon_s.png",
        "music_icon_sp.png",
        "music_icon_ss.png",
        "music_icon_ssp.png",
        "music_icon_sss.png",
        "music_icon_sssp.png",
        "music_icon_back.png",
        "music_icon_blank.png",
    }
)
_ACHIEVEMENT = re.compile(r"^(\d{1,3}(?:\.\d{1,4})?)%$")
_DX_SCORE = re.compile(r"([\d,]+)\s*/\s*([\d,]+)")
_DX_STAR = re.compile(r"^music_icon_dxstar(?:_detail)?_(\d+)\.png$")
_STAR_COUNT = re.compile(r"(?:×|x)\s*(\d+)")


@dataclass(frozen=True, slots=True)
class WahlapDetailScore:
    title: str
    chart_type: str
    level_index: int
    level: str
    achievements: float
    dx_score: int
    max_dx_score: int
    fc: str | None
    fs: str | None
    rate: str | None
    play_count: int
    dx_star: int | None


@dataclass(frozen=True, slots=True)
class WahlapPlayerProfile:
    player_name: str
    rating: int
    title_text: str
    title_rarity: str
    star_count: int
    version_logo_path: str
    avatar_path: str
    rating_base_path: str
    course_rank_path: str
    class_rank_path: str


@dataclass(frozen=True, slots=True)
class WahlapCollectionItem:
    name: str
    description: str
    image_path: str


def _filename(url: str) -> str:
    return PurePosixPath(url.split("?", 1)[0]).name


def _text(element: object) -> str:
    if not hasattr(element, "xpath"):
        return ""
    return str(element.xpath("string(.)")).strip()


def _first_filename(node: object, expression: str) -> str | None:
    values = node.xpath(expression)
    if not values or not isinstance(values[0], str):
        return None
    return _filename(values[0])


def _first_source_path(node: object, expression: str) -> str | None:
    values = node.xpath(expression)
    if not values or not isinstance(values[0], str):
        return None
    return values[0].split("?", 1)[0]


def parse_player_profile(page: str) -> WahlapPlayerProfile | None:
    root = html.fromstring(page)
    name_nodes = root.xpath(
        "//div[contains(concat(' ', normalize-space(@class), ' '), ' name_block ')][1]"
    )
    rating_nodes = root.xpath(
        "//div[contains(concat(' ', normalize-space(@class), ' '), ' rating_block ')][1]"
    )
    trophy_nodes = root.xpath(
        "//div[contains(concat(' ', normalize-space(@class), ' '), ' trophy_block ')][1]"
    )
    star_nodes = root.xpath(
        "//div[img[@src='/maimai-mobile/img/icon_star.png']][1]"
    )
    if not name_nodes or not rating_nodes or not trophy_nodes or not star_nodes:
        return None

    rating_text = _text(rating_nodes[0])
    star_match = _STAR_COUNT.search(_text(star_nodes[0]))
    title_nodes = trophy_nodes[0].xpath(
        ".//div[contains(concat(' ', normalize-space(@class), ' '), "
        "' trophy_inner_block ')][1]"
    )
    trophy_classes = trophy_nodes[0].get("class", "").split()
    rarity_tokens = [
        token.removeprefix("trophy_")
        for token in trophy_classes
        if token.startswith("trophy_") and token != "trophy_block"
    ]
    version_logo_path = _first_source_path(
        root, "//img[@src='/maimai-mobile/img/logo.png'][1]/@src"
    )
    avatar_path = _first_source_path(
        root, "//img[starts-with(@src, '/maimai-mobile/img/Icon/')][1]/@src"
    )
    rating_base_path = _first_source_path(
        root, "//img[starts-with(@src, '/maimai-mobile/img/rating_base_')][1]/@src"
    )
    course_rank_path = _first_source_path(
        root, "//img[starts-with(@src, '/maimai-mobile/img/course/')][1]/@src"
    )
    class_rank_path = _first_source_path(
        root, "//img[starts-with(@src, '/maimai-mobile/img/class/')][1]/@src"
    )
    required_paths = (
        version_logo_path,
        avatar_path,
        rating_base_path,
        course_rank_path,
        class_rank_path,
    )
    if (
        not rating_text.isascii()
        or not rating_text.isdigit()
        or star_match is None
        or not title_nodes
        or not rarity_tokens
        or any(path is None for path in required_paths)
    ):
        return None
    return WahlapPlayerProfile(
        player_name=_text(name_nodes[0]),
        rating=int(rating_text),
        title_text=_text(title_nodes[0]),
        title_rarity=rarity_tokens[0],
        star_count=int(star_match.group(1)),
        version_logo_path=version_logo_path,
        avatar_path=avatar_path,
        rating_base_path=rating_base_path,
        course_rank_path=course_rank_path,
        class_rank_path=class_rank_path,
    )


def parse_current_collection_item(
    page: str,
    asset_directory: str,
) -> WahlapCollectionItem | None:
    if asset_directory not in {"Icon", "NamePlate", "Frame"}:
        raise ValueError("unsupported Wahlap collection asset directory")
    root = html.fromstring(page)
    blocks = root.xpath(
        "//div[contains(concat(' ', normalize-space(@class), ' '), "
        "' collection_setting_block ')][1]"
    )
    if not blocks:
        return None
    block = blocks[0]
    image_path = _first_source_path(
        block,
        f".//img[starts-with(@src, '/maimai-mobile/img/{asset_directory}/')][1]/@src",
    )
    if asset_directory == "Icon":
        name_nodes = block.xpath(
            ".//div[contains(concat(' ', normalize-space(@class), ' '), ' p_t_10 ') "
            "and contains(concat(' ', normalize-space(@class), ' '), ' p_b_5 ') "
            "and contains(concat(' ', normalize-space(@class), ' '), ' f_14 ') "
            "and contains(concat(' ', normalize-space(@class), ' '), ' break ')][1]"
        )
    else:
        name_nodes = block.xpath(
            ".//div[contains(concat(' ', normalize-space(@class), ' '), ' p_5 ') "
            "and contains(concat(' ', normalize-space(@class), ' '), ' f_14 ') "
            "and contains(concat(' ', normalize-space(@class), ' '), ' break ')][1]"
        )
    description_nodes = block.xpath(
        ".//div[contains(concat(' ', normalize-space(@class), ' '), ' f_12 ') "
        "and contains(concat(' ', normalize-space(@class), ' '), ' gray ') "
        "and contains(concat(' ', normalize-space(@class), ' '), ' break ')][1]"
    )
    if image_path is None or not name_nodes or not description_nodes:
        return None
    return WahlapCollectionItem(
        name=_text(name_nodes[0]),
        description=_text(description_nodes[0]),
        image_path=image_path,
    )


def _achievement(node: object) -> float | None:
    elements = node.xpath(
        ".//div[contains(concat(' ', normalize-space(@class), ' '), "
        "' music_score_block ')]"
    )
    if not elements:
        return None
    match = _ACHIEVEMENT.fullmatch(_text(elements[0]))
    return float(match.group(1)) if match else None


def _dx_scores(node: object) -> tuple[int, int] | None:
    elements = node.xpath(
        ".//div[contains(concat(' ', normalize-space(@class), ' '), "
        "' music_score_block ')]"
    )
    if len(elements) < 2:
        return None
    match = _DX_SCORE.search(_text(elements[1]))
    if not match:
        return None
    current, maximum = match.groups()
    return int(current.replace(",", "")), int(maximum.replace(",", ""))


def _status_icons(
    node: object,
    expression: str,
    *,
    detail_order: bool = False,
) -> tuple[str | None, str | None, str | None]:
    filenames = [
        _filename(value)
        for value in node.xpath(expression)
        if isinstance(value, str) and "music_icon_" in value
    ]
    filenames = [name for name in filenames if _DX_STAR.fullmatch(name) is None]
    if len(filenames) < 3:
        return None, None, None
    if detail_order:
        rate_name, fc_name, fs_name = filenames[:3]
    else:
        fs_name, fc_name, rate_name = filenames[:3]
    fs = FS_ICONS.get(fs_name)
    fc = FC_ICONS.get(fc_name)
    rate = (
        rate_name.removeprefix("music_icon_").removesuffix(".png")
        if rate_name in RATE_ICONS and rate_name not in {"music_icon_back.png", "music_icon_blank.png"}
        else None
    )
    return fc, fs, rate


def parse_score_list(page: str) -> tuple[NormalizedScore, ...]:
    root = html.fromstring(page)
    result: list[NormalizedScore] = []
    for card in root.xpath(SCORE_CARD_XPATH):
        form = card.xpath(".//form[1]")
        if not form:
            continue
        form = form[0]
        difficulty_name = _first_filename(
            form,
            ".//img[contains(@src, '/maimai-mobile/img/diff_')][1]/@src",
        )
        level_index = DIFFICULTY_INDEX.get(difficulty_name or "")
        title_elements = form.xpath(
            ".//div[contains(concat(' ', normalize-space(@class), ' '), "
            "' music_name_block ')][1]"
        )
        achievements = _achievement(form)
        dx_scores = _dx_scores(form)
        kind_name = _first_filename(
            card,
            "./img[contains(concat(' ', normalize-space(@class), ' '), "
            "' music_kind_icon ')][1]/@src",
        )
        chart_type = CHART_TYPES.get(kind_name or "")
        if (
            level_index is None
            or not title_elements
            or achievements is None
            or dx_scores is None
            or chart_type is None
        ):
            continue
        title = _text(title_elements[0])
        if not title:
            continue
        fc, fs, _rate = _status_icons(
            form, ".//img[contains(@src, '/maimai-mobile/img/music_icon_')]/@src"
        )
        result.append(
            NormalizedScore(
                achievements=achievements,
                dx_score=dx_scores[0],
                fc=fc,
                fs=fs,
                level_index=level_index,
                title=title,
                chart_type=chart_type,
            )
        )
    return tuple(result)


def parse_music_detail(page: str) -> tuple[WahlapDetailScore, ...]:
    root = html.fromstring(page)
    title_elements = root.xpath(
        "//div[contains(concat(' ', normalize-space(@class), ' '), ' basic_block ')]"
        "//div[contains(concat(' ', normalize-space(@class), ' '), ' f_15 ') "
        "and contains(concat(' ', normalize-space(@class), ' '), ' break ')][1]"
    )
    if not title_elements:
        return ()
    title = _text(title_elements[0])
    result: list[WahlapDetailScore] = []
    for section_id, level_index in DETAIL_SECTION_IDS.items():
        sections = root.xpath(f"//div[@id='{section_id}']")
        if not sections:
            continue
        section = sections[0]
        kind_name = _first_filename(
            section,
            ".//img[contains(concat(' ', normalize-space(@class), ' '), "
            "' music_kind_icon ')][1]/@src",
        )
        chart_type = CHART_TYPES.get(kind_name or "")
        level_elements = section.xpath(
            ".//div[contains(concat(' ', normalize-space(@class), ' '), "
            "' music_lv_back ')][1]"
        )
        achievements = _achievement(section)
        dx_scores = _dx_scores(section)
        count_cells = section.xpath(
            ".//tr[td[1][normalize-space()='游戏次数：']]/td[2]"
        )
        if (
            chart_type is None
            or not level_elements
            or achievements is None
            or dx_scores is None
            or not count_cells
        ):
            continue
        count_text = _text(count_cells[0]).replace(",", "")
        if not count_text.isascii() or not count_text.isdigit():
            continue
        fc, fs, rate = _status_icons(
            section,
            ".//div[contains(concat(' ', normalize-space(@class), ' '), ' t_r ') "
            "and contains(concat(' ', normalize-space(@class), ' '), ' f_r ')]"
            "//img[contains(@src, '/maimai-mobile/img/music_icon_')]/@src",
            detail_order=True,
        )
        star_names = [
            _filename(value)
            for value in section.xpath(
                ".//img[contains(@src, '/maimai-mobile/img/music_icon_dxstar_detail_')]/@src"
            )
            if isinstance(value, str)
        ]
        star_match = _DX_STAR.fullmatch(star_names[0]) if star_names else None
        result.append(
            WahlapDetailScore(
                title=title,
                chart_type=chart_type,
                level_index=level_index,
                level=_text(level_elements[0]),
                achievements=achievements,
                dx_score=dx_scores[0],
                max_dx_score=dx_scores[1],
                fc=fc,
                fs=fs,
                rate=rate,
                play_count=int(count_text),
                dx_star=int(star_match.group(1)) if star_match else None,
            )
        )
    return tuple(result)
