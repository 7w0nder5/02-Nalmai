from __future__ import annotations

import asyncio
import json
import math
import os
import secrets
import sys
import time
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
import astrbot.api.message_components as Comp
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from cryptography.fernet import Fernet
import httpx


PLUGIN_NAME = "astrbot_plugin_nalmai"
PLUGIN_ROOT = Path(__file__).resolve().parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from nalmai.bootstrap import Container, build_container  # noqa: E402
from nalmai.config import Settings  # noqa: E402
from nalmai.models import ApplicationResponse, InboundMessage  # noqa: E402


HELP_TEXT = """Nalmai AstrBot 指令

以下三种格式效果一致：
/nalmai <指令>、/NAlmai <指令>、@机器人 /<指令>

/nalmai help
查看本帮助。

/nalmai bind <QQ号码> <Import-Token>
私聊绑定水鱼账号；不要在群聊发送 Import-Token。

/nalmai update <SGWCMAID...>
私聊读取本次舞萌成绩并热更新水鱼。

/nalmai assetsync
私聊创建一次管理员共享素材同步任务；仅机器人主机可完成后续微信授权采集。

/nalmai b50 或 @机器人 /b50
私聊或群聊生成自己的 B50 图片，三种格式输出完全一致。

/nalmai status
查看自己的绑定与最近同步状态。

/nalmai unbind
私聊删除自己的绑定、加密凭据及本地资料。

AstrBot OneBot 使用同一 QQ ID 识别群聊与私聊用户，因此不需要 /pair。"""


class NalmaiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self._data_dir = (
            Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        )
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._image_dir = self._data_dir / "images"
        self._image_dir.mkdir(parents=True, exist_ok=True)
        self._avatar_dir = self._data_dir / "qq_avatars"
        self._avatar_dir.mkdir(parents=True, exist_ok=True)
        self._shared_asset_dir = self._data_dir / "shared_assets"
        self._shared_asset_dir.mkdir(parents=True, exist_ok=True)
        os.environ["NALMAI_SHARED_ASSET_DIR"] = str(self._shared_asset_dir)

        settings = self._build_settings(config)
        self._container: Container = build_container(settings)
        self._cooldown_seconds = float(config.get("cooldown_seconds", 30.0))
        max_concurrent = int(config.get("max_concurrent_requests", 2))
        if self._cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must not be negative")
        if max_concurrent < 1:
            raise ValueError("max_concurrent_requests must be at least 1")
        self._slots = asyncio.Semaphore(max_concurrent)
        self._last_expensive: dict[tuple[str, str], float] = {}
        self._avatar_client = httpx.AsyncClient(
            timeout=float(config.get("http_timeout_seconds", 15.0)),
            follow_redirects=True,
            headers={"User-Agent": "Nalmai/0.1"},
        )
        self._cleanup_images()
        logger.info("Nalmai AstrBot 插件已加载。")

    @filter.command(
        "nalmai help",
        alias={"Nalmai help", "NAlmai help", "NALMAI help"},
    )
    async def help_command(self, event: AstrMessageEvent):
        """查看 Nalmai 指令帮助。"""
        if not self._valid_command_message(event, "help", argument_count=0):
            event.stop_event()
            return
        yield event.plain_result(HELP_TEXT)

    @filter.command(
        "nalmai bind",
        alias={"Nalmai bind", "NAlmai bind", "NALMAI bind"},
    )
    async def bind_command(
        self,
        event: AstrMessageEvent,
        qq_number: str = "",
        import_token: str = "",
    ):
        """私聊绑定水鱼 Import-Token。"""
        if not self._valid_command_message(event, "bind", argument_count=2):
            event.stop_event()
            return
        if not self._is_private(event):
            yield event.plain_result(
                "绑定信息只能私聊发送；请撤回群内凭据并立即更换 Token。"
            )
            return
        response = await self._handle(
            event,
            f"/bind {qq_number} {import_token}",
            operation="bind",
            expensive=True,
        )
        yield self._event_result(event, response)

    @filter.command(
        "nalmai update",
        alias={"Nalmai update", "NAlmai update", "NALMAI update"},
    )
    async def update_command(
        self,
        event: AstrMessageEvent,
        credential: str = "",
    ):
        """私聊使用 SGWCMAID 凭据更新水鱼成绩。"""
        if not self._valid_command_message(event, "update", argument_count=1):
            event.stop_event()
            return
        if not self._is_private(event):
            yield event.plain_result(
                "SGWCMAID 凭据只能私聊发送；请撤回群内消息并重新获取凭据。"
            )
            return
        response = await self._handle(
            event,
            credential,
            operation="update",
            expensive=True,
        )
        yield self._event_result(event, response)

    @filter.command(
        "nalmai b50",
        alias={"Nalmai b50", "NAlmai b50", "NALMAI b50"},
    )
    async def b50_command(self, event: AstrMessageEvent):
        """生成当前 QQ 用户的 B50 图片。"""
        if not self._valid_command_message(event, "b50", argument_count=0):
            event.stop_event()
            return
        yield await self._b50_result(event)

    @filter.command(
        "nalmai assetsync",
        alias={
            "Nalmai assetsync",
            "NAlmai assetsync",
            "NALMAI assetsync",
        },
    )
    async def asset_sync_command(self, event: AstrMessageEvent):
        """创建管理员共享收藏素材同步任务。"""
        if not self._valid_command_message(event, "assetsync", argument_count=0):
            event.stop_event()
            return
        if not self._is_private(event):
            yield event.plain_result("共享素材同步任务只能在私聊创建。")
            return
        response = await self._handle(
            event,
            "/wechat",
            operation="assetsync",
            expensive=True,
        )
        yield self._event_result(event, response)

    @filter.command("b50")
    async def b50_shortcut_command(self, event: AstrMessageEvent):
        """艾特机器人发送 b50，生成与 /nalmai b50 相同的图片。"""
        event.stop_event()
        async for result in self.b50_command(event):
            yield result

    @filter.command("help")
    async def help_shortcut_command(self, event: AstrMessageEvent):
        """Use @bot /help with the same behavior as /nalmai help."""
        event.stop_event()
        async for result in self.help_command(event):
            yield result

    @filter.command("bind")
    async def bind_shortcut_command(
        self,
        event: AstrMessageEvent,
        qq_number: str = "",
        import_token: str = "",
    ):
        """Use @bot /bind with the same behavior as /nalmai bind."""
        event.stop_event()
        async for result in self.bind_command(event, qq_number, import_token):
            yield result

    @filter.command("update")
    async def update_shortcut_command(
        self,
        event: AstrMessageEvent,
        credential: str = "",
    ):
        """Use @bot /update with the same behavior as /nalmai update."""
        event.stop_event()
        async for result in self.update_command(event, credential):
            yield result

    @filter.command("assetsync")
    async def asset_sync_shortcut_command(self, event: AstrMessageEvent):
        """Use @bot /assetsync with the same behavior as /nalmai assetsync."""
        event.stop_event()
        async for result in self.asset_sync_command(event):
            yield result

    @filter.command("status")
    async def status_shortcut_command(self, event: AstrMessageEvent):
        """Use @bot /status with the same behavior as /nalmai status."""
        event.stop_event()
        async for result in self.status_command(event):
            yield result

    @filter.command("unbind")
    async def unbind_shortcut_command(self, event: AstrMessageEvent):
        """Use @bot /unbind with the same behavior as /nalmai unbind."""
        event.stop_event()
        async for result in self.unbind_command(event):
            yield result

    async def _b50_result(self, event: AstrMessageEvent):
        response = await self._handle(
            event,
            "/b50",
            operation="b50",
            expensive=True,
        )
        return self._event_result(event, response)

    @filter.command(
        "nalmai status",
        alias={"Nalmai status", "NAlmai status", "NALMAI status"},
    )
    async def status_command(self, event: AstrMessageEvent):
        """查看当前 QQ 用户的绑定和同步状态。"""
        if not self._valid_command_message(event, "status", argument_count=0):
            event.stop_event()
            return
        response = await self._handle(
            event,
            "/status",
            operation="status",
            expensive=False,
        )
        yield self._event_result(event, response)

    @filter.command(
        "nalmai unbind",
        alias={"Nalmai unbind", "NAlmai unbind", "NALMAI unbind"},
    )
    async def unbind_command(self, event: AstrMessageEvent):
        """私聊删除当前 QQ 用户的 Nalmai 数据。"""
        if not self._valid_command_message(event, "unbind", argument_count=0):
            event.stop_event()
            return
        if not self._is_private(event):
            yield event.plain_result("请在私聊执行 /nalmai unbind。")
            return
        response = await self._handle(
            event,
            "/unbind",
            operation="unbind",
            expensive=False,
        )
        yield self._event_result(event, response)

    async def _handle(
        self,
        event: AstrMessageEvent,
        text: str,
        *,
        operation: str,
        expensive: bool,
    ) -> ApplicationResponse:
        user_id = self._platform_user_id(event)
        if expensive:
            limited = self._check_limit(user_id, operation)
            if limited is not None:
                return limited
            if self._slots.locked():
                return ApplicationResponse(
                    "当前正在处理其他成绩请求，请稍后重试。",
                    error_code="SERVICE_BUSY",
                )
            self._last_expensive[(user_id, operation)] = time.monotonic()
            async with self._slots:
                return await self._dispatch(event, user_id, text)
        return await self._dispatch(event, user_id, text)

    async def _dispatch(
        self,
        event: AstrMessageEvent,
        user_id: str,
        text: str,
    ) -> ApplicationResponse:
        display_avatar = (
            await self._get_qq_avatar(event) if text == "/b50" else None
        )
        return await self._container.application.handle(
            InboundMessage(
                platform_user_id=user_id,
                session_id=event.unified_msg_origin,
                text=text,
                is_private=self._is_private(event),
                message_reference=str(event.message_obj.message_id),
                display_avatar=display_avatar,
            )
        )

    async def _get_qq_avatar(self, event: AstrMessageEvent) -> bytes | None:
        sender_id = str(event.get_sender_id()).strip()
        if not sender_id.isdigit():
            return None
        cache_path = self._avatar_dir / f"{sender_id}.png"
        try:
            if (
                cache_path.is_file()
                and time.time() - cache_path.stat().st_mtime < 7 * 24 * 60 * 60
            ):
                cached = cache_path.read_bytes()
                if cached:
                    return cached

            response = await self._avatar_client.get(
                "https://q1.qlogo.cn/g",
                params={"b": "qq", "nk": sender_id, "s": "640"},
            )
            content_type = response.headers.get("content-type", "").casefold()
            if (
                response.status_code != 200
                or not content_type.startswith("image/")
                or not response.content
                or len(response.content) > 2 * 1024 * 1024
            ):
                return None
            temporary = cache_path.with_suffix(
                f".{secrets.token_hex(4)}.tmp"
            )
            temporary.write_bytes(response.content)
            os.replace(temporary, cache_path)
            return response.content
        except (httpx.HTTPError, OSError):
            logger.warning(
                "QQ 头像读取失败，将使用已保存的华立头像或 Nalmai 默认图形。"
            )
            return None

    def _check_limit(
        self,
        user_id: str,
        operation: str,
    ) -> ApplicationResponse | None:
        now = time.monotonic()
        previous = self._last_expensive.get((user_id, operation))
        if previous is None:
            return None
        remaining = self._cooldown_seconds - (now - previous)
        if remaining <= 0:
            return None
        return ApplicationResponse(
            f"该指令请求过于频繁，请在 {math.ceil(remaining)} 秒后重试。",
            error_code="RATE_LIMITED",
        )

    def _event_result(
        self,
        event: AstrMessageEvent,
        response: ApplicationResponse,
    ):
        if response.image is None:
            return event.plain_result(response.text)
        image_path = self._save_image(
            self._platform_user_id(event), response.image.content
        )
        return event.chain_result(
            [
                Comp.Plain(response.text),
                Comp.Image.fromFileSystem(str(image_path)),
            ]
        )

    def _save_image(self, user_id: str, content: bytes) -> Path:
        digest = secrets.token_hex(8)
        path = self._image_dir / f"b50-{digest}.png"
        path.write_bytes(content)
        return path

    @staticmethod
    def _valid_command_message(
        event: AstrMessageEvent,
        command: str,
        *,
        argument_count: int,
    ) -> bool:
        parts = event.get_message_str().strip().split()
        if parts and parts[0] in {"nalmai", "Nalmai", "NAlmai", "NALMAI"}:
            return (
                len(parts) == argument_count + 2
                and parts[1] == command
            )
        return len(parts) == argument_count + 1 and parts[0] == command

    @staticmethod
    def _is_private(event: AstrMessageEvent) -> bool:
        return not bool(event.message_obj.group_id)

    @staticmethod
    def _platform_user_id(event: AstrMessageEvent) -> str:
        sender_id = str(event.get_sender_id()).strip()
        if not sender_id:
            raise ValueError("AstrBot event sender id is empty")
        return f"astrbot:{sender_id}"

    def _build_settings(self, config: AstrBotConfig) -> Settings:
        secrets_data = self._load_or_create_secrets()
        return Settings(
            database_path=self._data_dir / "nalmai.sqlite3",
            fernet_key=secrets_data["fernet_key"],
            hmac_key=secrets_data["hmac_key"],
            internal_api_token=secrets_data["internal_api_token"],
            allow_group_secrets=False,
            http_timeout_seconds=float(config.get("http_timeout_seconds", 15.0)),
            b50_output_dir=self._image_dir,
            arcade_provider=str(config.get("arcade_provider", "maimai_py")),
            arcade_http_proxy=(
                str(config.get("arcade_http_proxy", "")).strip() or None
            ),
        )

    def _load_or_create_secrets(self) -> dict[str, str]:
        path = self._data_dir / "security.json"
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            required = {"fernet_key", "hmac_key", "internal_api_token"}
            if not isinstance(payload, dict) or set(payload) != required:
                raise RuntimeError("Nalmai security.json 结构无效。")
            if not all(isinstance(payload[key], str) and payload[key] for key in required):
                raise RuntimeError("Nalmai security.json 含空密钥。")
            return payload

        payload = {
            "fernet_key": Fernet.generate_key().decode("ascii"),
            "hmac_key": secrets.token_urlsafe(48),
            "internal_api_token": secrets.token_urlsafe(48),
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)
        try:
            path.chmod(0o600)
        except OSError:
            logger.warning("无法调整 Nalmai security.json 文件权限。")
        return payload

    def _cleanup_images(self) -> None:
        threshold = time.time() - 24 * 60 * 60
        for path in self._image_dir.glob("b50-*.png"):
            try:
                if path.stat().st_mtime < threshold:
                    path.unlink()
            except OSError:
                logger.warning("无法清理过期的 Nalmai B50 图片。")

    async def terminate(self) -> None:
        await self._avatar_client.aclose()
        await self._container.divingfish.close()
        self._container.repository.close()
        logger.info("Nalmai AstrBot 插件已停止。")
