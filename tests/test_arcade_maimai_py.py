from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from nalmai.adapters.arcade_maimai_py import MaimaiPyArcadeScoreProvider
from nalmai.models import BindingStatus, UserBinding


def _binding() -> UserBinding:
    return UserBinding(
        platform_user_id="platform-1",
        claimed_qq="123456",
        divingfish_username="water_user",
        credential_ciphertext=b"ciphertext",
        credential_key_version="test-v1",
        credential_mask="toke...oken",
        status=BindingStatus.BOUND,
    )


@pytest.mark.asyncio
async def test_maimai_py_provider_maps_supported_fields(monkeypatch) -> None:
    module = ModuleType("maimai_py")
    observed: dict[str, object] = {}

    class ArcadeProvider:
        def __init__(self, http_proxy: str | None = None) -> None:
            observed["provider_proxy"] = http_proxy

    class MaimaiClient:
        async def qrcode(self, code: str, http_proxy: str | None = None):
            observed["code"] = code
            observed["qrcode_proxy"] = http_proxy
            return object()

        async def scores(self, identifier, provider):
            del identifier, provider
            score = SimpleNamespace(
                achievements=100.1234,
                dx_score=2876,
                title="Test Song",
                level_index=SimpleNamespace(value=3),
                type=SimpleNamespace(name="DX"),
                fc=None,
                fs=None,
                play_count=None,
            )
            return SimpleNamespace(scores=[score])

    module.ArcadeProvider = ArcadeProvider
    module.MaimaiClient = MaimaiClient
    monkeypatch.setitem(sys.modules, "maimai_py", module)

    batch = await MaimaiPyArcadeScoreProvider("http://127.0.0.1:7890").fetch_scores(
        "SGWCMAID-test", _binding()
    )

    assert observed == {
        "provider_proxy": "http://127.0.0.1:7890",
        "code": "SGWCMAID-test",
        "qrcode_proxy": "http://127.0.0.1:7890",
    }
    assert batch.upload_authorized is True
    assert batch.unavailable_fields == ("FC", "FS", "PC 次数")
    assert batch.scores[0].title == "Test Song"
    assert batch.scores[0].chart_type == "DX"
    assert batch.scores[0].fc is None
    assert batch.scores[0].fs is None
