from __future__ import annotations

from nalmai.commands import HELP_TEXT, CommandParser
from nalmai.errors import NalmaiError
from nalmai.models import ApplicationResponse, CommandKind, InboundMessage
from nalmai.services.b50 import B50Service
from nalmai.services.binding import BindingService
from nalmai.services.sync import SyncService
from nalmai.services.wechat import WechatOAuthService


class NalmaiApplication:
    private_entry_message = (
        "该操作包含敏感凭据，请在私聊或一次性 HTTPS 页面执行。"
    )

    def __init__(
        self,
        parser: CommandParser,
        binding: BindingService,
        sync: SyncService,
        b50: B50Service,
        wechat: WechatOAuthService | None = None,
        allow_group_secrets: bool = False,
    ) -> None:
        self._parser = parser
        self._binding = binding
        self._sync = sync
        self._b50 = b50
        self._wechat = wechat
        self._allow_group_secrets = allow_group_secrets

    async def handle(self, message: InboundMessage) -> ApplicationResponse:
        try:
            command = self._parser.parse(message.text)
            if command.kind is CommandKind.HELP:
                return ApplicationResponse(HELP_TEXT)

            if command.kind in {
                CommandKind.PAIR_ISSUE,
                CommandKind.PAIR_CONSUME,
            }:
                return ApplicationResponse(
                    "配对指令只能通过 QQ 消息入口执行。",
                    error_code="QQ_ENTRY_REQUIRED",
                )

            if command.kind is CommandKind.BIND_GUIDE:
                return ApplicationResponse(self.private_entry_message)

            if command.kind is CommandKind.WECHAT:
                if not message.is_private:
                    return ApplicationResponse(
                        "请在私聊发送 /wechat。",
                        error_code="PRIVATE_CHANNEL_REQUIRED",
                    )
                if self._wechat is None:
                    return ApplicationResponse(
                        "本机微信授权服务尚未配置。",
                        error_code="WECHAT_SERVICE_NOT_CONFIGURED",
                    )
                await self._wechat.issue(message.platform_user_id)
                return ApplicationResponse(
                    "微信授权任务已创建，5 分钟内有效。请在运行 Nalmai 的同一台"
                    " Windows 电脑上，以管理员身份执行 "
                    "scripts\\run_wechat_capture.ps1，然后按提示在微信中授权。"
                )

            if command.kind in {CommandKind.BIND, CommandKind.SYNC}:
                if not message.is_private and not self._allow_group_secrets:
                    return ApplicationResponse(
                        self.private_entry_message,
                        error_code="PRIVATE_CHANNEL_REQUIRED",
                    )

            if command.kind is CommandKind.BIND:
                assert command.claimed_qq is not None
                assert command.import_token is not None
                result = await self._binding.bind(
                    message.platform_user_id,
                    command.claimed_qq,
                    command.import_token,
                )
                return ApplicationResponse(
                    "绑定成功："
                    f"QQ {result.masked_qq}，水鱼用户名 {result.username}，"
                    f"凭据 {result.masked_token}。"
                )

            if command.kind is CommandKind.SYNC:
                assert command.sgwc_credential is not None
                result = await self._sync.synchronize(
                    message.platform_user_id, command.sgwc_credential
                )
                limitation = ""
                if result.unavailable_fields:
                    limitation = (
                        " 当前华立接口未提供："
                        + "、".join(result.unavailable_fields)
                        + "；已有水鱼 FC/FS 已保留，未生成推测值。"
                    )
                return ApplicationResponse(
                    "上传成功："
                    f"玩家 {result.player_display_name}，上传 {result.uploaded_count} 条，"
                    f"跳过 {result.skipped_count} 条，任务 {result.job_id}。"
                    f"{limitation}"
                )

            if command.kind is CommandKind.B50:
                image = await self._b50.create_image(
                    message.platform_user_id,
                    display_avatar=message.display_avatar,
                )
                return ApplicationResponse("B50 生成成功。", image=image)

            if command.kind is CommandKind.STATUS:
                return ApplicationResponse(
                    await self._binding.status(message.platform_user_id)
                )

            if command.kind is CommandKind.UNBIND:
                if not message.is_private:
                    return ApplicationResponse(
                        "请在私聊执行 /unbind。",
                        error_code="PRIVATE_CHANNEL_REQUIRED",
                    )
                deleted = await self._binding.unbind(message.platform_user_id)
                return ApplicationResponse(
                    "解绑成功。" if deleted else "当前没有绑定。"
                )

            return ApplicationResponse(
                "无法识别命令。", error_code="UNKNOWN_COMMAND"
            )
        except NalmaiError as exc:
            return ApplicationResponse(exc.public_message, error_code=exc.code)
