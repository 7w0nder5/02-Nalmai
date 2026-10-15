from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
from PIL import Image

from nalmai.adapters.b50_basic import BasicB50Renderer
from nalmai.adapters.b50_rich import RichB50Renderer
from nalmai.errors import BindingRequired, NalmaiError
from nalmai.models import LocalPlayerProfile
from nalmai.services.b50 import B50Service
from nalmai.services.binding import BindingService
from tests.fakes import FakeCipher, FakeDivingFish, FakeRepository


@pytest.mark.asyncio
async def test_unbound_user_cannot_render_b50() -> None:
    repository = FakeRepository()
    service = B50Service(repository, FakeDivingFish(), BasicB50Renderer())
    with pytest.raises(BindingRequired):
        await service.create_image("missing")


@pytest.mark.asyncio
async def test_b50_renderer_outputs_valid_png() -> None:
    repository = FakeRepository()
    client = FakeDivingFish()
    await BindingService(repository, FakeCipher(), client).bind(
        "platform-1", "123456", "token"
    )
    image = await B50Service(repository, client, BasicB50Renderer()).create_image(
        "platform-1"
    )
    parsed = Image.open(io.BytesIO(image.content))
    assert parsed.format == "PNG"
    assert parsed.width == 1600


@pytest.mark.asyncio
async def test_rich_b50_renderer_outputs_complete_layout() -> None:
    repository = FakeRepository()
    client = FakeDivingFish()
    await BindingService(repository, FakeCipher(), client).bind(
        "platform-1", "123456", "token"
    )
    image = await B50Service(repository, client, RichB50Renderer(client)).create_image(
        "platform-1"
    )
    parsed = Image.open(io.BytesIO(image.content))
    assert parsed.format == "PNG"
    assert parsed.size[0] == 1600
    assert parsed.size[1] > 500
    assert image.filename == "nalmai-b50-rich.png"


@pytest.mark.asyncio
async def test_rich_b50_renderer_uses_supplied_display_avatar() -> None:
    repository = FakeRepository()
    client = FakeDivingFish()
    await BindingService(repository, FakeCipher(), client).bind(
        "platform-1", "123456", "token"
    )
    avatar = Image.new("RGB", (64, 64), "#ef3340")
    avatar_buffer = io.BytesIO()
    avatar.save(avatar_buffer, format="PNG")

    result = await B50Service(
        repository,
        client,
        RichB50Renderer(client),
    ).create_image(
        "platform-1",
        display_avatar=avatar_buffer.getvalue(),
    )

    parsed = Image.open(io.BytesIO(result.content)).convert("RGB")
    red, green, blue = parsed.getpixel((294, 97))
    assert red > 200
    assert green < 100
    assert blue < 100


def test_rich_b50_renderer_loads_confirmed_wahlap_status_icons() -> None:
    renderer = RichB50Renderer(FakeDivingFish())
    assert renderer._official_ui_icon("music_icon_sss.png").size == (68, 31)
    assert renderer._official_ui_icon("music_icon_fc.png").size == (42, 47)
    assert renderer._official_ui_icon("music_dx.png").size == (113, 32)


def test_rich_b50_renderer_loads_shared_artwork_deterministically(
    tmp_path,
    monkeypatch,
) -> None:
    icon_dir = tmp_path / "icon"
    partner_dir = tmp_path / "partner"
    nameplate_dir = tmp_path / "nameplate"
    frame_dir = tmp_path / "frame"
    icon_dir.mkdir()
    partner_dir.mkdir()
    nameplate_dir.mkdir()
    frame_dir.mkdir()
    Image.new("RGBA", (64, 64), "#33aa77").save(icon_dir / "icon.png")
    Image.new("RGBA", (80, 160), "#8844cc").save(partner_dir / "partner.png")
    Image.new("RGBA", (396, 63), "#225588").save(
        nameplate_dir / "nameplate.png"
    )
    Image.new("RGBA", (396, 165), (0, 0, 0, 0)).save(
        frame_dir / "0-empty.png"
    )
    Image.new("RGBA", (396, 165), "#55aaee").save(
        frame_dir / "1-frame.png"
    )
    monkeypatch.setenv("NALMAI_SHARED_ASSET_DIR", str(tmp_path))

    renderer = RichB50Renderer(FakeDivingFish())
    first = renderer._shared_asset("partner", "same-player")
    second = renderer._shared_asset("partner", "same-player")
    icon = renderer._shared_asset("icon", "same-player")
    nameplate = renderer._shared_asset("nameplate", "same-player")
    frame = renderer._shared_asset("frame", "same-player")

    assert first is not None
    assert second is not None
    assert icon is not None
    assert nameplate is not None
    assert frame is not None
    assert first.size == second.size == (80, 160)
    assert icon.size == (64, 64)
    assert nameplate.size == (396, 63)
    assert frame.size == (396, 165)
    assert frame.getchannel("A").getbbox() is not None


@pytest.mark.asyncio
async def test_rich_b50_renderer_uses_saved_wahlap_profile_header() -> None:
    repository = FakeRepository()
    client = FakeDivingFish()
    await BindingService(repository, FakeCipher(), client).bind(
        "platform-1", "123456", "token"
    )
    source = Image.new("RGBA", (64, 32), "#7f5ac7")
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")
    asset = buffer.getvalue()
    await repository.save_player_profile(
        LocalPlayerProfile(
            platform_user_id="platform-1",
            player_name="７ｗ０ｎｄｅｒｓ",
            rating=15896,
            title_text="あ",
            title_rarity="Gold",
            star_count=635,
            avatar_name="ソルト（ふぇすてぃばる）",
            nameplate_name="桃将",
            nameplate_description="maimai PiNK 全曲/BASIC～MASTER/RANK SSS",
            frame_name="樋口楓ちほー",
            frame_description="樋口楓ちほーで獲得",
            version_logo=asset,
            avatar=asset,
            rating_base=asset,
            course_rank=asset,
            class_rank=asset,
            nameplate=asset,
            frame=asset,
            updated_at=datetime.now(UTC),
        )
    )

    result = await B50Service(
        repository,
        client,
        RichB50Renderer(client),
        chart_stats=repository,
    ).create_image("platform-1")

    parsed = Image.open(io.BytesIO(result.content))
    assert parsed.format == "PNG"
    assert parsed.size[0] == 1600


def test_rich_b50_labels_match_arcade_notation() -> None:
    assert RichB50Renderer.rate_labels == {
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
    assert RichB50Renderer.fc_labels == {
        "fc": "FC",
        "fcp": "FC+",
        "ap": "AP",
        "app": "AP+",
    }
    assert RichB50Renderer.fs_labels == {
        "sync": "SYNC",
        "fs": "FS",
        "fsp": "FS+",
        "fsd": "FSD",
        "fdx": "FSD",
        "fsdp": "FSD+",
        "fdxp": "FSD+",
    }


@pytest.mark.parametrize(
    ("dx_score", "max_dx_score", "expected"),
    (
        (0, 1000, 0),
        (850, 1000, 0),
        (851, 1000, 1),
        (900, 1000, 1),
        (901, 1000, 2),
        (930, 1000, 2),
        (931, 1000, 3),
        (950, 1000, 3),
        (951, 1000, 4),
        (970, 1000, 4),
        (971, 1000, 5),
        (1000, 1000, 5),
        (1, None, None),
        (1, 0, None),
    ),
)
def test_dx_star_thresholds(
    dx_score: int, max_dx_score: int | None, expected: int | None
) -> None:
    assert RichB50Renderer._dx_star(dx_score, max_dx_score) == expected


def test_current_version_is_read_from_b15_music_metadata() -> None:
    entries = [
        {"song_id": 1001, "type": "DX"},
        {"song_id": 1002, "type": "DX"},
        {"song_id": 1003, "type": "SD"},
    ]
    music_map = {
        (1001, "DX"): {"basic_info": {"from": "PRiSM PLUS"}},
        (1002, "DX"): {"basic_info": {"from": "PRiSM PLUS"}},
        (1003, "SD"): {"basic_info": {"from": "PRiSM"}},
    }

    assert RichB50Renderer._current_version(entries, music_map) == "PRiSM PLUS"


@pytest.mark.asyncio
async def test_privacy_block_has_explicit_error() -> None:
    repository = FakeRepository()
    client = FakeDivingFish()
    await BindingService(repository, FakeCipher(), client).bind(
        "platform-1", "123456", "token"
    )
    client.error = NalmaiError("DIVINGFISH_FORBIDDEN", "forbidden")
    with pytest.raises(NalmaiError) as raised:
        await B50Service(repository, client, BasicB50Renderer()).create_image(
            "platform-1"
        )
    assert raised.value.code == "B50_PRIVACY_BLOCKED"
