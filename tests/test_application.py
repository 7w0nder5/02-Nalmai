from __future__ import annotations

import pytest

from nalmai.commands import HELP_TEXT, CommandParser
from nalmai.models import InboundMessage
from nalmai.services.application import NalmaiApplication
from nalmai.services.b50 import B50Service
from nalmai.services.binding import BindingService
from nalmai.services.sync import SyncService
from tests.fakes import FakeArcade, FakeCipher, FakeDivingFish, FakeRenderer, FakeRepository


def _application() -> NalmaiApplication:
    repository = FakeRepository()
    cipher = FakeCipher()
    client = FakeDivingFish()
    return NalmaiApplication(
        CommandParser(),
        BindingService(repository, cipher, client),
        SyncService(
            repository,
            repository,
            cipher,
            client,
            FakeArcade(),
            "hmac-key",
        ),
        B50Service(repository, client, FakeRenderer()),
    )


@pytest.mark.asyncio
async def test_help_lists_commands_without_calling_external_services() -> None:
    response = await _application().handle(
        InboundMessage("user", "group", "@Nalmai /help", is_private=False)
    )
    assert response.error_code is None
    assert response.text == HELP_TEXT
    for command in (
        "/help",
        "/status",
        "/pair",
        "/bind",
        "SGWCMAID",
        "/wechat",
        "/b50",
        "/unbind",
    ):
        assert command in response.text
    assert "请先私聊绑定" in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "@Nalmai /bind 123456 super-secret-token",
        "@Nalmai SGWCMAID-super-secret",
    ],
)
async def test_group_secrets_are_not_processed_or_echoed(text: str) -> None:
    response = await _application().handle(
        InboundMessage("user", "group", text, is_private=False)
    )
    assert response.error_code == "PRIVATE_CHANNEL_REQUIRED"
    assert "super-secret" not in response.text


@pytest.mark.asyncio
async def test_private_bind_sync_and_group_b50_flow() -> None:
    app = _application()
    bind = await app.handle(
        InboundMessage(
            "user", "private", "/bind 123456 super-secret-token", is_private=True
        )
    )
    assert bind.error_code is None
    assert "super-secret-token" not in bind.text

    sync = await app.handle(
        InboundMessage("user", "private", "SGWCMAIDabc", is_private=True)
    )
    assert sync.error_code is None
    assert "上传成功" in sync.text

    b50 = await app.handle(InboundMessage("user", "group", "/b50", is_private=False))
    assert b50.error_code is None
    assert b50.image is not None
