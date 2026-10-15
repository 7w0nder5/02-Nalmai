from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable

from nalmai.commands import CommandParser
from nalmai.errors import NalmaiError
from nalmai.models import ApplicationResponse, CommandKind, InboundMessage
from nalmai.services.application import NalmaiApplication
from nalmai.services.qq_identity import QQIdentityService


class QQCommandRouter:
    _EXPENSIVE_COMMANDS = frozenset(
        {
            CommandKind.BIND,
            CommandKind.SYNC,
            CommandKind.WECHAT,
            CommandKind.B50,
        }
    )

    def __init__(
        self,
        application: NalmaiApplication,
        parser: CommandParser,
        identities: QQIdentityService,
        *,
        expensive_cooldown_seconds: float = 30.0,
        max_concurrent_expensive: int = 2,
    ) -> None:
        if expensive_cooldown_seconds < 0:
            raise ValueError("expensive_cooldown_seconds must not be negative")
        if max_concurrent_expensive < 1:
            raise ValueError("max_concurrent_expensive must be at least 1")
        self._application = application
        self._parser = parser
        self._identities = identities
        self._expensive_cooldown_seconds = expensive_cooldown_seconds
        self._expensive_slots = asyncio.Semaphore(max_concurrent_expensive)
        self._last_expensive: dict[tuple[str, CommandKind], float] = {}

    async def handle_private(
        self, user_openid: str, text: str, message_reference: str | None = None
    ) -> ApplicationResponse:
        private_identity = self._identities.private_identity(user_openid)
        try:
            command = self._parser.parse(text)
        except NalmaiError as exc:
            return ApplicationResponse(exc.public_message, error_code=exc.code)

        if command.kind is CommandKind.PAIR_ISSUE:
            pairing = await self._identities.issue(private_identity)
            return ApplicationResponse(
                "配对码："
                f"{pairing.value}\n"
                "5 分钟内在目标群发送：@Nalmai /pair "
                f"{pairing.value}\n"
                "配对码只能使用一次。"
            )
        if command.kind is CommandKind.PAIR_CONSUME:
            return ApplicationResponse(
                "请在目标群发送 /pair <8位配对码>。",
                error_code="GROUP_CHANNEL_REQUIRED",
            )
        if command.kind is CommandKind.BIND_GUIDE:
            return ApplicationResponse(
                "绑定格式：/bind <QQ号码> <Import-Token>。"
                "绑定信息只能在私聊发送。"
            )

        response = await self._dispatch(
            private_identity,
            command.kind,
            lambda: self._application.handle(
                InboundMessage(
                    platform_user_id=private_identity,
                    session_id=private_identity,
                    text=text,
                    is_private=True,
                    message_reference=message_reference,
                )
            ),
        )
        if command.kind is CommandKind.STATUS:
            response = ApplicationResponse(
                f"Nalmai QQ WebSocket 已连接；{response.text}",
                image=response.image,
                error_code=response.error_code,
            )
        if command.kind is CommandKind.UNBIND and response.error_code is None:
            await self._identities.unlink_private(private_identity)
        return response

    async def handle_group(
        self,
        group_openid: str,
        member_openid: str,
        text: str,
        message_reference: str | None = None,
    ) -> ApplicationResponse:
        group_identity = self._identities.group_identity(
            group_openid, member_openid
        )
        try:
            command = self._parser.parse(text)
        except NalmaiError as exc:
            return ApplicationResponse(exc.public_message, error_code=exc.code)

        if command.kind is CommandKind.PAIR_ISSUE:
            return ApplicationResponse(
                "请先私聊 Nalmai 发送 /pair 获取一次性配对码。",
                error_code="PRIVATE_CHANNEL_REQUIRED",
            )
        if command.kind is CommandKind.PAIR_CONSUME:
            assert command.pairing_code is not None
            try:
                private_identity = await self._identities.consume(
                    command.pairing_code, group_identity
                )
            except NalmaiError as exc:
                return ApplicationResponse(exc.public_message, error_code=exc.code)
            status = await self._application.handle(
                InboundMessage(
                    platform_user_id=private_identity,
                    session_id=group_identity,
                    text="/status",
                    is_private=False,
                    message_reference=message_reference,
                )
            )
            return ApplicationResponse(f"群聊身份配对成功；{status.text}")
        if command.kind is CommandKind.BIND_GUIDE:
            return ApplicationResponse(
                "请私聊 Nalmai 发送 /bind <QQ号码> <Import-Token>；"
                "绑定后私聊 /pair，再到本群完成配对。"
            )
        if command.kind is CommandKind.WECHAT:
            return ApplicationResponse(
                "请私聊 Nalmai 发送 /wechat 创建本机微信授权任务。",
                error_code="PRIVATE_CHANNEL_REQUIRED",
            )
        if command.kind is CommandKind.HELP:
            return await self._application.handle(
                InboundMessage(
                    platform_user_id=group_identity,
                    session_id=group_identity,
                    text=text,
                    is_private=False,
                    message_reference=message_reference,
                )
            )

        private_identity = await self._identities.resolve_group(group_identity)
        if private_identity is None:
            if command.kind is CommandKind.STATUS:
                return ApplicationResponse(
                    "Nalmai QQ WebSocket 已连接；当前群身份尚未配对。"
                    "请私聊发送 /pair。"
                )
            return ApplicationResponse(
                "当前群身份尚未配对。请先私聊绑定并发送 /pair，"
                "再到本群提交配对码。",
                error_code="QQ_IDENTITY_PAIRING_REQUIRED",
            )

        response = await self._dispatch(
            private_identity,
            command.kind,
            lambda: self._application.handle(
                InboundMessage(
                    platform_user_id=private_identity,
                    session_id=group_identity,
                    text=text,
                    is_private=False,
                    message_reference=message_reference,
                )
            ),
        )
        if command.kind is CommandKind.STATUS:
            return ApplicationResponse(
                f"Nalmai QQ WebSocket 已连接；{response.text}",
                image=response.image,
                error_code=response.error_code,
            )
        return response

    async def _dispatch(
        self,
        private_identity: str,
        command_kind: CommandKind,
        operation: Callable[[], Awaitable[ApplicationResponse]],
    ) -> ApplicationResponse:
        if command_kind not in self._EXPENSIVE_COMMANDS:
            return await operation()

        now = time.monotonic()
        key = (private_identity, command_kind)
        previous = self._last_expensive.get(key)
        if previous is not None:
            remaining = self._expensive_cooldown_seconds - (now - previous)
            if remaining > 0:
                return ApplicationResponse(
                    "该指令请求过于频繁，请在 "
                    f"{math.ceil(remaining)} 秒后重试。",
                    error_code="RATE_LIMITED",
                )

        if self._expensive_slots.locked():
            return ApplicationResponse(
                "当前正在处理其他成绩请求，请稍后重试。",
                error_code="SERVICE_BUSY",
            )

        self._last_expensive[key] = now
        self._discard_expired_cooldowns(now)
        async with self._expensive_slots:
            return await operation()

    def _discard_expired_cooldowns(self, now: float) -> None:
        if len(self._last_expensive) < 1024:
            return
        threshold = now - self._expensive_cooldown_seconds
        self._last_expensive = {
            key: timestamp
            for key, timestamp in self._last_expensive.items()
            if timestamp >= threshold
        }
