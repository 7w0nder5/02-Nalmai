from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nalmai.errors import NalmaiError
from nalmai.models import (
    B50Image,
    LocalChartStat,
    WechatChartDetail,
    WechatPlayerProfile,
    WechatSessionStatus,
)
from nalmai.services.b50 import B50Service
from nalmai.services.binding import BindingService
from nalmai.services.sync import SyncService
from nalmai.services.wechat import WechatOAuthService
from tests.fakes import (
    FakeArcade,
    FakeCipher,
    FakeDivingFish,
    FakeRepository,
    sample_score,
)


async def _service() -> tuple[
    WechatOAuthService, FakeRepository, FakeDivingFish
]:
    repository = FakeRepository()
    divingfish = FakeDivingFish()
    cipher = FakeCipher()
    await BindingService(repository, cipher, divingfish).bind(
        "platform-1", "123456", "import-token"
    )
    sync = SyncService(
        repository,
        repository,
        cipher,
        divingfish,
        FakeArcade(),
        "hmac-key",
    )
    return (
        WechatOAuthService(
            repository,
            repository,
            sync,
            divingfish,
            "hmac-key",
        ),
        repository,
        divingfish,
    )


@pytest.mark.asyncio
async def test_wechat_session_uploads_scores_and_saves_b50_details() -> None:
    service, repository, divingfish = await _service()
    issued = await service.issue("platform-1")
    assert issued.status is WechatSessionStatus.PENDING

    claimed, token = await service.claim()
    assert claimed.id == issued.id
    assert token.encode("utf-8") not in claimed.token_digest.encode("utf-8")

    result, charts = await service.upload_scores(token, (sample_score(),))
    assert result.uploaded_count == 1
    assert divingfish.uploaded[0]["title"] == "Test Song"
    assert [(item.title, item.chart_type, item.level_index) for item in charts] == [
        ("Test Song", "SD", 3)
    ]

    await service.upload_player_profile(
        token,
        WechatPlayerProfile(
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
            version_logo=b"logo",
            avatar=b"avatar",
            rating_base=b"rating",
            course_rank=b"course",
            class_rank=b"class",
            nameplate=b"nameplate",
            frame=b"frame",
        ),
    )
    profile = await repository.get_player_profile("platform-1")
    assert profile is not None
    assert profile.player_name == "７ｗ０ｎｄｅｒｓ"
    assert profile.nameplate_name == "桃将"

    saved = await service.upload_details(
        token,
        (
            WechatChartDetail(
                title="Test Song",
                chart_type="SD",
                level_index=3,
                play_count=9,
                dx_star=2,
            ),
        ),
    )
    assert saved == 1
    stats = await repository.get_chart_stats("platform-1")
    assert stats[0].play_count == 9
    assert stats[0].dx_star == 2
    assert repository.wechat_sessions[issued.id].status is WechatSessionStatus.SUCCEEDED

    with pytest.raises(NalmaiError) as raised:
        await service.upload_details(token, ())
    assert raised.value.code == "WECHAT_TOKEN_INVALID"


@pytest.mark.asyncio
async def test_wechat_claim_requires_private_pending_task() -> None:
    service, _, _ = await _service()
    with pytest.raises(NalmaiError) as raised:
        await service.claim()
    assert raised.value.code == "WECHAT_SESSION_NOT_FOUND"


@pytest.mark.asyncio
async def test_b50_merges_exact_local_chart_stats() -> None:
    class CapturingRenderer:
        payload = None

        async def render(self, payload):
            self.payload = payload
            return B50Image(content=b"png")

    _, repository, divingfish = await _service()
    await repository.save_chart_stats(
        (
            LocalChartStat(
                platform_user_id="platform-1",
                title="Test Song",
                chart_type="SD",
                level_index=3,
                play_count=12,
                dx_star=3,
                updated_at=datetime.now(UTC),
            ),
        )
    )
    renderer = CapturingRenderer()
    await B50Service(
        repository,
        divingfish,
        renderer,
        chart_stats=repository,
    ).create_image("platform-1")
    item = renderer.payload["charts"]["sd"][0]
    assert item["play_count"] == 12
    assert item["dx_star"] == 3
