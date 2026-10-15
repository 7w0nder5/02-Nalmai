from __future__ import annotations

import asyncio

import pytest

from nalmai.adapters.arcade_unavailable import UnavailableArcadeScoreProvider
from nalmai.errors import BindingRequired, NalmaiError
from nalmai.models import JobStatus, NormalizedScore, ScoreBatch
from nalmai.services.binding import BindingService
from nalmai.services.sync import SyncService
from tests.fakes import FakeArcade, FakeCipher, FakeDivingFish, FakeRepository


async def _bound_service(
    arcade: FakeArcade | None = None,
) -> tuple[SyncService, FakeRepository, FakeDivingFish, FakeArcade]:
    repository = FakeRepository()
    client = FakeDivingFish()
    cipher = FakeCipher()
    await BindingService(repository, cipher, client).bind(
        "platform-1", "123456", "import-token"
    )
    active_arcade = arcade or FakeArcade()
    return (
        SyncService(
            repository,
            repository,
            cipher,
            client,
            active_arcade,
            "hmac-key",
        ),
        repository,
        client,
        active_arcade,
    )


@pytest.mark.asyncio
async def test_unbound_user_cannot_sync() -> None:
    repository = FakeRepository()
    service = SyncService(
        repository,
        repository,
        FakeCipher(),
        FakeDivingFish(),
        FakeArcade(),
        "hmac-key",
    )
    with pytest.raises(BindingRequired):
        await service.synchronize("missing", "SGWCMAIDabc")


@pytest.mark.asyncio
async def test_unavailable_arcade_provider_fails_before_upload() -> None:
    repository = FakeRepository()
    client = FakeDivingFish()
    cipher = FakeCipher()
    await BindingService(repository, cipher, client).bind(
        "platform-1", "123456", "import-token"
    )
    service = SyncService(
        repository,
        repository,
        cipher,
        client,
        UnavailableArcadeScoreProvider(),
        "hmac-key",
    )

    with pytest.raises(NalmaiError) as raised:
        await service.synchronize("platform-1", "SGWCMAIDabc")

    assert raised.value.code == "ARCADE_PROVIDER_NOT_CONFIGURED"
    assert client.uploaded == []
    latest = await repository.get_latest("platform-1")
    assert latest is not None and latest.status is JobStatus.FAILED


@pytest.mark.asyncio
async def test_sync_reaches_succeeded_and_uploads_exact_fields() -> None:
    service, repository, client, _ = await _bound_service()
    result = await service.synchronize("platform-1", "SGWCMAIDabc")

    assert result.uploaded_count == 1
    assert client.uploaded == [
        {
            "achievements": 100.5,
            "dxScore": 1234,
            "fc": "fc",
            "fs": "",
            "level_index": 3,
            "title": "Test Song",
            "type": "SD",
        }
    ]
    latest = await repository.get_latest("platform-1")
    assert latest is not None and latest.status is JobStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_account_match_must_be_verified() -> None:
    service, repository, client, _ = await _bound_service(FakeArcade(verified=False))
    with pytest.raises(NalmaiError) as raised:
        await service.synchronize("platform-1", "SGWCMAIDabc")
    assert raised.value.code == "UPLOAD_NOT_AUTHORIZED"
    assert client.uploaded == []
    latest = await repository.get_latest("platform-1")
    assert latest is not None and latest.status is JobStatus.FAILED


@pytest.mark.asyncio
async def test_partial_upload_is_uploaded_unverified() -> None:
    service, repository, client, _ = await _bound_service()
    client.partial_upload = True
    with pytest.raises(NalmaiError) as raised:
        await service.synchronize("platform-1", "SGWCMAIDabc")
    assert raised.value.code == "UPLOAD_COUNT_MISMATCH"
    latest = await repository.get_latest("platform-1")
    assert latest is not None and latest.status is JobStatus.UPLOADED_UNVERIFIED


@pytest.mark.asyncio
async def test_upload_is_not_success_until_new_scores_are_visible() -> None:
    service, repository, client, _ = await _bound_service()
    client.keep_stale_records = True
    with pytest.raises(NalmaiError) as raised:
        await service.synchronize("platform-1", "SGWCMAIDabc")
    assert raised.value.code == "SCORE_VERIFY_FAILED"
    latest = await repository.get_latest("platform-1")
    assert latest is not None and latest.status is JobStatus.UPLOADED_UNVERIFIED


@pytest.mark.asyncio
async def test_unknown_arcade_fc_fs_preserve_existing_water_values() -> None:
    class BasicArcade:
        async def fetch_scores(self, sgwc_credential, binding):
            del sgwc_credential, binding
            return ScoreBatch(
                scores=(
                    NormalizedScore(
                        achievements=100.6,
                        dx_score=2000,
                        fc=None,
                        fs=None,
                        level_index=3,
                        title="Test Song",
                        chart_type="SD",
                    ),
                ),
                player_display_name="二维码玩家",
                upload_authorized=True,
                unavailable_fields=("FC", "FS", "PC 次数"),
            )

    service, _, client, _ = await _bound_service(BasicArcade())
    client.records_payload["records"] = [
        {
            "title": "Test Song",
            "type": "SD",
            "level_index": 3,
            "fc": "ap",
            "fs": "fsd",
        }
    ]

    result = await service.synchronize("platform-1", "SGWCMAIDabc")

    assert client.uploaded[0]["fc"] == "ap"
    assert client.uploaded[0]["fs"] == "fsd"
    assert result.unavailable_fields == ("FC", "FS", "PC 次数")


@pytest.mark.asyncio
async def test_same_user_jobs_are_serialized_and_replay_is_rejected() -> None:
    arcade = FakeArcade(delay=0.02)
    service, _, _, _ = await _bound_service(arcade)

    first, second = await asyncio.gather(
        service.synchronize("platform-1", "SGWCMAID-one"),
        service.synchronize("platform-1", "SGWCMAID-two"),
    )
    assert first.uploaded_count == second.uploaded_count == 1
    assert arcade.max_active == 1

    with pytest.raises(NalmaiError) as raised:
        await service.synchronize("platform-1", "SGWCMAID-one")
    assert raised.value.code == "DUPLICATE_CREDENTIAL"
