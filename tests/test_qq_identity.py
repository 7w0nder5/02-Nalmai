from __future__ import annotations

import sqlite3

import pytest

from nalmai.adapters.sqlite_repository import SqliteRepository
from nalmai.commands import CommandParser
from nalmai.errors import NalmaiError
from nalmai.services.application import NalmaiApplication
from nalmai.services.b50 import B50Service
from nalmai.services.binding import BindingService
from nalmai.services.qq_identity import QQIdentityService
from nalmai.services.qq_router import QQCommandRouter
from nalmai.services.sync import SyncService
from tests.fakes import (
    FakeArcade,
    FakeCipher,
    FakeDivingFish,
    FakeRenderer,
    FakeRepository,
)


def _router() -> tuple[QQCommandRouter, FakeRepository, QQIdentityService]:
    repository = FakeRepository()
    client = FakeDivingFish()
    cipher = FakeCipher()
    application = NalmaiApplication(
        CommandParser(),
        BindingService(repository, cipher, client),
        SyncService(
            repository,
            repository,
            cipher,
            client,
            FakeArcade(),
            "sync-hmac-key",
        ),
        B50Service(repository, client, FakeRenderer()),
    )
    identities = QQIdentityService(repository, "identity-hmac-key")
    return (
        QQCommandRouter(application, CommandParser(), identities),
        repository,
        identities,
    )


@pytest.mark.asyncio
async def test_pairing_is_one_time_and_resolves_group_to_private() -> None:
    repository = FakeRepository()
    service = QQIdentityService(repository, "identity-hmac-key")
    private_identity = service.private_identity("private-openid")
    group_identity = service.group_identity("group-openid", "member-openid")

    assert "private-openid" not in private_identity
    assert "group-openid" not in group_identity
    assert "member-openid" not in group_identity

    issued = await service.issue(private_identity)
    assert len(issued.value) == 8
    assert issued.value.isascii() and issued.value.isdigit()
    assert issued.value not in repository.pairing_codes

    assert await service.consume(issued.value, group_identity) == private_identity
    assert await service.resolve_group(group_identity) == private_identity
    with pytest.raises(NalmaiError, match="无效、已使用或已过期"):
        await service.consume(issued.value, group_identity)


@pytest.mark.asyncio
async def test_router_bind_pair_status_b50_and_unbind_flow() -> None:
    router, _, _ = _router()

    group_help = await router.handle_group(
        "group-openid", "member-openid", "/help"
    )
    assert group_help.error_code is None
    assert "/pair" in group_help.text

    bind = await router.handle_private(
        "private-openid", "/bind 123456 import-token"
    )
    assert bind.error_code is None
    assert "绑定成功" in bind.text
    assert "import-token" not in bind.text

    issued = await router.handle_private("private-openid", "/pair")
    code = issued.text.splitlines()[0].partition("：")[2]
    assert len(code) == 8

    paired = await router.handle_group(
        "group-openid", "member-openid", f"/pair {code}"
    )
    assert paired.error_code is None
    assert "配对成功" in paired.text
    assert "water_user" in paired.text

    status = await router.handle_group(
        "group-openid", "member-openid", "/status"
    )
    assert "WebSocket 已连接" in status.text
    assert "water_user" in status.text

    b50 = await router.handle_group("group-openid", "member-openid", "/b50")
    assert b50.error_code is None
    assert b50.image is not None
    assert b50.image.content == b"fake-png"

    unbind = await router.handle_private("private-openid", "/unbind")
    assert unbind.text == "解绑成功。"
    after = await router.handle_group(
        "group-openid", "member-openid", "/status"
    )
    assert "尚未配对" in after.text


@pytest.mark.asyncio
async def test_public_mode_rate_limits_expensive_commands_per_user() -> None:
    router, _, _ = _router()

    first_bind = await router.handle_private(
        "first-private-openid", "/bind 123456 import-token"
    )
    assert first_bind.error_code is None
    first_b50 = await router.handle_private("first-private-openid", "/b50")
    assert first_b50.error_code is None

    repeated_b50 = await router.handle_private("first-private-openid", "/b50")
    assert repeated_b50.error_code == "RATE_LIMITED"
    assert "秒后重试" in repeated_b50.text

    status = await router.handle_private("first-private-openid", "/status")
    assert status.error_code is None

    second_bind = await router.handle_private(
        "second-private-openid", "/bind 654321 another-import-token"
    )
    assert second_bind.error_code is None
    second_b50 = await router.handle_private("second-private-openid", "/b50")
    assert second_b50.error_code is None


def test_public_mode_rejects_invalid_resource_limits() -> None:
    application_router, _, identities = _router()
    with pytest.raises(ValueError, match="must not be negative"):
        QQCommandRouter(
            application_router._application,
            CommandParser(),
            identities,
            expensive_cooldown_seconds=-1,
        )
    with pytest.raises(ValueError, match="at least 1"):
        QQCommandRouter(
            application_router._application,
            CommandParser(),
            identities,
            max_concurrent_expensive=0,
        )


@pytest.mark.asyncio
async def test_sqlite_never_stores_pairing_code_or_openids_in_plaintext(
    tmp_path,
) -> None:
    database = tmp_path / "nalmai.sqlite3"
    repository = SqliteRepository(database)
    service = QQIdentityService(repository, "identity-hmac-key")
    private_openid = "private-openid-sensitive"
    group_openid = "group-openid-sensitive"
    member_openid = "member-openid-sensitive"
    private_identity = service.private_identity(private_openid)
    group_identity = service.group_identity(group_openid, member_openid)

    issued = await service.issue(private_identity)
    await service.consume(issued.value, group_identity)
    repository.close()

    database_bytes = database.read_bytes()
    assert issued.value.encode("ascii") not in database_bytes
    assert private_openid.encode("utf-8") not in database_bytes
    assert group_openid.encode("utf-8") not in database_bytes
    assert member_openid.encode("utf-8") not in database_bytes

    connection = sqlite3.connect(database)
    assert connection.execute("SELECT COUNT(*) FROM qq_identity_links").fetchone()[0] == 1
    assert connection.execute("SELECT COUNT(*) FROM qq_pairing_codes").fetchone()[0] == 0
    connection.close()
