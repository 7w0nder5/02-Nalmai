from __future__ import annotations

from base64 import b64encode
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from nalmai.config import Settings
from nalmai.services.binding import BindingService
from nalmai.services.sync import SyncService
from nalmai.services.wechat import WechatOAuthService
from nalmai.web import create_app
from tests.fakes import FakeArcade, FakeCipher, FakeDivingFish, FakeRepository


@pytest.mark.asyncio
async def test_local_wechat_api_claim_upload_and_detail_flow(tmp_path: Path) -> None:
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
    wechat = WechatOAuthService(
        repository,
        repository,
        sync,
        divingfish,
        "hmac-key",
    )
    await wechat.issue("platform-1")
    settings = Settings(
        database_path=tmp_path / "unused.sqlite3",
        fernet_key="unused",
        hmac_key="hmac-key",
        internal_api_token="internal-token",
        allow_group_secrets=False,
        http_timeout_seconds=1,
        b50_output_dir=tmp_path,
    )
    app = create_app(
        settings,
        SimpleNamespace(wechat=wechat),
        manage_resources=False,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1"
    ) as client:
        denied = await client.post("/internal/wechat/claim")
        assert denied.status_code == 401

        claimed = await client.post(
            "/internal/wechat/claim",
            headers={"X-Nalmai-Internal-Token": "internal-token"},
        )
        assert claimed.status_code == 200
        token = claimed.json()["upload_token"]

        scores = await client.post(
            "/v1/wechat/scores",
            headers={"X-Nalmai-WeChat-Token": token},
            json={
                "scores": [
                    {
                        "achievements": 100.5,
                        "dx_score": 1234,
                        "fc": "fc",
                        "fs": "",
                        "level_index": 3,
                        "title": "Test Song",
                        "chart_type": "SD",
                    }
                ]
            },
        )
        assert scores.status_code == 200
        assert scores.json()["charts"] == [
            {"title": "Test Song", "chart_type": "SD", "level_index": 3}
        ]

        encoded_asset = b64encode(b"image").decode("ascii")
        profile = await client.post(
            "/v1/wechat/profile",
            headers={"X-Nalmai-WeChat-Token": token},
            json={
                "player_name": "７ｗ０ｎｄｅｒｓ",
                "rating": 15896,
                "title_text": "あ",
                "title_rarity": "Gold",
                "star_count": 635,
                "avatar_name": "ソルト（ふぇすてぃばる）",
                "nameplate_name": "桃将",
                "nameplate_description": "maimai PiNK 全曲/BASIC～MASTER/RANK SSS",
                "frame_name": "樋口楓ちほー",
                "frame_description": "樋口楓ちほーで獲得",
                "version_logo_base64": encoded_asset,
                "avatar_base64": encoded_asset,
                "rating_base_base64": encoded_asset,
                "course_rank_base64": encoded_asset,
                "class_rank_base64": encoded_asset,
                "nameplate_base64": encoded_asset,
                "frame_base64": encoded_asset,
            },
        )
        assert profile.status_code == 200
        stored_profile = await repository.get_player_profile("platform-1")
        assert stored_profile is not None
        assert stored_profile.nameplate_name == "桃将"

        details = await client.post(
            "/v1/wechat/details",
            headers={"X-Nalmai-WeChat-Token": token},
            json={
                "details": [
                    {
                        "title": "Test Song",
                        "chart_type": "SD",
                        "level_index": 3,
                        "play_count": 8,
                        "dx_star": 2,
                    }
                ]
            },
        )
        assert details.status_code == 200
        assert details.json()["saved_details"] == 1
