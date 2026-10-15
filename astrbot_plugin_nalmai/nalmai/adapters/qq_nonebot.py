from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import uvicorn
from nonebot import get_driver, get_plugin_config, on_message
from nonebot.adapters.qq import Bot, Event, MessageSegment
from nonebot.adapters.qq.event import (
    C2CMessageCreateEvent,
    GroupAtMessageCreateEvent,
)
from nonebot.log import logger
from pydantic import BaseModel, SecretStr

from nalmai.adapters.qq_capture import SecureQQEventCapture
from nalmai.bootstrap import build_container
from nalmai.commands import CommandParser
from nalmai.config import Settings
from nalmai.models import ApplicationResponse
from nalmai.services.qq_identity import QQIdentityService
from nalmai.services.qq_router import QQCommandRouter
from nalmai.web import create_app


class QQRuntimeConfig(BaseModel):
    nalmai_database_path: Path = Path("./data/nalmai.sqlite3")
    nalmai_fernet_key: SecretStr
    nalmai_hmac_key: SecretStr
    nalmai_internal_api_token: SecretStr
    nalmai_allow_group_secrets: bool = False
    nalmai_http_timeout_seconds: float = 15.0
    nalmai_b50_output_dir: Path = Path("./data")
    nalmai_arcade_provider: str = "unavailable"
    nalmai_arcade_http_proxy: str | None = None
    nalmai_local_api_port: int = 8000
    nalmai_qq_capture_enabled: bool = True
    nalmai_qq_capture_raw: bool = False
    nalmai_qq_capture_dir: Path = Path("./data/qq-events")
    nalmai_qq_expensive_cooldown_seconds: float = 30.0
    nalmai_qq_max_concurrent_expensive: int = 2


_config = get_plugin_config(QQRuntimeConfig)
_settings = Settings(
    database_path=_config.nalmai_database_path,
    fernet_key=_config.nalmai_fernet_key.get_secret_value(),
    hmac_key=_config.nalmai_hmac_key.get_secret_value(),
    internal_api_token=_config.nalmai_internal_api_token.get_secret_value(),
    allow_group_secrets=_config.nalmai_allow_group_secrets,
    http_timeout_seconds=_config.nalmai_http_timeout_seconds,
    b50_output_dir=_config.nalmai_b50_output_dir,
    arcade_provider=_config.nalmai_arcade_provider,
    arcade_http_proxy=_config.nalmai_arcade_http_proxy or None,
    local_api_port=_config.nalmai_local_api_port,
    qq_expensive_cooldown_seconds=(
        _config.nalmai_qq_expensive_cooldown_seconds
    ),
    qq_max_concurrent_expensive=_config.nalmai_qq_max_concurrent_expensive,
)
_container = build_container(_settings)
_identities = QQIdentityService(_container.repository, _settings.hmac_key)
_router = QQCommandRouter(
    _container.application,
    CommandParser(),
    _identities,
    expensive_cooldown_seconds=_settings.qq_expensive_cooldown_seconds,
    max_concurrent_expensive=_settings.qq_max_concurrent_expensive,
)
_capture = SecureQQEventCapture(
    _config.nalmai_qq_capture_dir,
    _config.nalmai_hmac_key.get_secret_value(),
    enabled=_config.nalmai_qq_capture_enabled,
    raw_enabled=_config.nalmai_qq_capture_raw,
)
_driver = get_driver()
_api_server: uvicorn.Server | None = None
_api_task: asyncio.Task[None] | None = None

_message = on_message(priority=1, block=True)


@_driver.on_startup
async def _start_local_api() -> None:
    global _api_server, _api_task
    api = create_app(_settings, _container, manage_resources=False)
    config = uvicorn.Config(
        api,
        host="127.0.0.1",
        port=_settings.local_api_port,
        access_log=False,
        log_level="critical",
    )
    _api_server = uvicorn.Server(config)
    _api_task = asyncio.create_task(_api_server.serve())
    for _ in range(50):
        if _api_server.started:
            print(
                "Nalmai 本机微信授权 API 已启动："
                f"127.0.0.1:{_settings.local_api_port}"
            )
            return
        if _api_task.done():
            await _api_task
            raise RuntimeError("Nalmai 本机微信授权 API 启动失败。")
        await asyncio.sleep(0.1)
    raise RuntimeError("Nalmai 本机微信授权 API 启动超时。")


@_message.handle()
async def handle_qq_message(bot: Bot, event: Event) -> None:
    if not isinstance(event, (C2CMessageCreateEvent, GroupAtMessageCreateEvent)):
        return

    text = event.get_plaintext().strip()
    try:
        payload = _event_payload(event)
        _capture.store(
            event.get_event_name(),
            payload,
            allow_raw=text == "/status",
        )
    except Exception as exc:
        logger.error("QQ event capture failed: {}", type(exc).__name__)
        await bot.send(event, "事件采集失败；未处理本次消息。")
        return

    try:
        if isinstance(event, C2CMessageCreateEvent):
            response = await _router.handle_private(
                event.author.user_openid,
                text,
                message_reference=event.id,
            )
        else:
            response = await _router.handle_group(
                event.group_openid,
                event.author.member_openid,
                text,
                message_reference=event.id,
            )
        await _send_response(bot, event, response)
    except Exception as exc:
        logger.error("QQ command routing failed: {}", type(exc).__name__)
        await bot.send(
            event,
            "Nalmai 处理失败，未回显任何凭据。请稍后重试或联系管理员。",
        )


def _event_payload(event: Event) -> dict[str, Any]:
    payload = event.model_dump(mode="json", by_alias=True)
    if not isinstance(payload, dict):
        raise TypeError("QQ event model did not produce a JSON object")
    return payload


async def _send_response(
    bot: Bot, event: Event, response: ApplicationResponse
) -> None:
    if response.image is None:
        await bot.send(event, response.text)
        return
    message = MessageSegment.text(response.text) + MessageSegment.file_image(
        response.image.content,
        response.image.filename,
    )
    await bot.send(event, message)


@_driver.on_shutdown
async def _close_resources() -> None:
    if _api_server is not None:
        _api_server.should_exit = True
    if _api_task is not None:
        await _api_task
    await _container.divingfish.close()
    _container.repository.close()
