from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import httpx
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star
from astrbot.core.utils.astrbot_path import get_astrbot_data_path


PLUGIN_NAME = "astrbot_plugin_jwb_monitor"
NALMAI_PRIVATE_UMO_PREFIX = "nalmai_onebot:FriendMessage:"


class JwbMonitorPlugin(Star):
    """Forward local venue-monitor state changes to subscribed QQ chats."""

    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self._data_dir = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._subscriptions_path = self._data_dir / "subscriptions.json"
        self._state_path = self._data_dir / "state.json"

        monitor_state_url = str(
            config.get(
                "monitor_state_url",
                "http://127.0.0.1:3178/api/integrations/astrbot/state",
            )
        ).strip()
        parsed_url = urlparse(monitor_state_url)
        if parsed_url.scheme != "http" or parsed_url.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError("monitor_state_url must point to a local HTTP address")
        self._monitor_state_url = monitor_state_url

        self._poll_interval_seconds = int(config.get("poll_interval_seconds", 5))
        if self._poll_interval_seconds < 1:
            raise ValueError("poll_interval_seconds must be at least 1")

        self._subscriptions: set[str] = set()
        if self._subscriptions_path.is_file():
            payload = json.loads(self._subscriptions_path.read_text(encoding="utf-8"))
            if not isinstance(payload, list) or not all(
                isinstance(item, str) and item.startswith(NALMAI_PRIVATE_UMO_PREFIX)
                for item in payload
            ):
                raise RuntimeError("subscriptions.json has an invalid structure")
            self._subscriptions = set(payload)

        recipient_qq = str(config.get("recipient_qq", "")).strip()
        if not recipient_qq:
            raise ValueError("recipient_qq must be configured")
        if not re.fullmatch(r"[1-9][0-9]{4,11}", recipient_qq):
            raise ValueError("recipient_qq must be a valid numeric QQ account")
        self._fixed_recipient_umo = f"{NALMAI_PRIVATE_UMO_PREFIX}{recipient_qq}"
        self._subscriptions.add(self._fixed_recipient_umo)
        self._save_subscriptions()

        self._last_check_at: str | None = None
        self._last_available: bool | None = None
        self._available_since: str | None = None
        self._delivered_umos: set[str] = set()
        if self._state_path.is_file():
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError("state.json has an invalid structure")
            check_at = payload.get("last_check_at")
            available = payload.get("last_available")
            if check_at is not None and not isinstance(check_at, str):
                raise RuntimeError("state.json last_check_at is invalid")
            if available is not None and not isinstance(available, bool):
                raise RuntimeError("state.json last_available is invalid")
            available_since = payload.get("available_since")
            delivered_umos = payload.get("delivered_umos", [])
            if available_since is not None and not isinstance(available_since, str):
                raise RuntimeError("state.json available_since is invalid")
            if not isinstance(delivered_umos, list) or not all(
                isinstance(item, str) for item in delivered_umos
            ):
                raise RuntimeError("state.json delivered_umos is invalid")
            self._last_check_at = check_at
            self._last_available = available
            self._available_since = available_since
            self._delivered_umos = set(delivered_umos)

        self._last_error: str | None = None
        self._client = httpx.AsyncClient(timeout=5.0)
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("JWB venue monitor bridge loaded")

    @filter.command_group("jwb")
    def jwb():
        """Manage private QQ notifications for the venue monitor."""

    def _save_subscriptions(self) -> None:
        """Persist private-chat subscriptions atomically."""
        temporary = self._subscriptions_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(sorted(self._subscriptions), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self._subscriptions_path)

    def _save_state(self) -> None:
        """Persist delivery state so a plugin reload does not duplicate alerts."""
        temporary = self._state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {
                    "last_check_at": self._last_check_at,
                    "last_available": self._last_available,
                    "available_since": self._available_since,
                    "delivered_umos": sorted(self._delivered_umos),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, self._state_path)

    @staticmethod
    def _is_nalmai_private_umo(umo: str) -> bool:
        """Return whether the UMO belongs to the configured Nalmai QQ adapter."""
        return umo.startswith(NALMAI_PRIVATE_UMO_PREFIX)

    @jwb.command("on")
    async def subscribe(self, event: AstrMessageEvent):
        """Subscribe the current private chat to vacancy notifications."""
        if event.message_obj.group_id:
            yield event.plain_result("请私聊 Nalmai 后发送 /jwb on，群聊不会被订阅。")
            return
        umo = event.unified_msg_origin
        if not self._is_nalmai_private_umo(umo):
            yield event.plain_result("当前会话不是 Nalmai QQ 私聊会话，未启用通知。")
            return
        self._subscriptions.add(umo)
        self._save_subscriptions()
        yield event.plain_result(
            "交我办场馆空余提醒已开启。视觉监控发现空余时，Nalmai 会私聊通知你。"
        )

    @jwb.command("off")
    async def unsubscribe(self, event: AstrMessageEvent):
        """Remove the current private chat from vacancy notifications."""
        if event.message_obj.group_id:
            yield event.plain_result("请在订阅提醒的私聊中发送 /jwb off。")
            return
        umo = event.unified_msg_origin
        if umo == self._fixed_recipient_umo:
            yield event.plain_result("当前 QQ 是固定提醒接收方，不能通过聊天命令关闭。")
            return
        self._subscriptions.discard(umo)
        self._delivered_umos.discard(umo)
        self._save_subscriptions()
        self._save_state()
        yield event.plain_result("交我办场馆空余提醒已关闭。")

    @jwb.command("status")
    async def status(self, event: AstrMessageEvent):
        """Show subscription and local monitor status."""
        subscribed = event.unified_msg_origin in self._subscriptions
        if self._last_error:
            monitor_status = f"连接异常：{self._last_error}"
        elif self._last_check_at is None:
            monitor_status = "尚未取得视觉监控检测结果"
        elif self._last_available:
            monitor_status = f"最近一次检测可能有空余（{self._last_check_at}）"
        else:
            monitor_status = f"最近一次检测未发现空余（{self._last_check_at}）"
        yield event.plain_result(
            f"提醒订阅：{'已开启' if subscribed else '未开启'}\n"
            f"视觉监控：{monitor_status}"
        )

    @jwb.command("test")
    async def test_notification(self, event: AstrMessageEvent):
        """Send a proactive test message to the configured recipient."""
        if event.message_obj.group_id:
            yield event.plain_result("请私聊 Nalmai 后发送 /jwb test。")
            return
        if not self._is_nalmai_private_umo(event.unified_msg_origin):
            yield event.plain_result("当前会话不是 Nalmai QQ 私聊会话，未发送测试通知。")
            return
        await self.context.send_message(
            self._fixed_recipient_umo,
            MessageChain().message("交我办场馆监控测试通知：AstrBot 私聊发送正常。"),
        )
        yield event.plain_result("测试通知已发送给固定接收 QQ。")

    async def _poll_loop(self) -> None:
        """Poll the local visual monitor and notify on new available states."""
        while True:
            try:
                response = await self._client.get(self._monitor_state_url)
                response.raise_for_status()
                payload = response.json()
                monitor = payload.get("monitor")
                if not isinstance(monitor, dict):
                    raise ValueError("monitor response is missing the monitor object")
                check_at = monitor.get("lastCheckAt")
                result = monitor.get("lastResult")
                if check_at is None or result is None:
                    self._last_error = None
                    await asyncio.sleep(self._poll_interval_seconds)
                    continue
                if not isinstance(check_at, str) or not isinstance(result, dict):
                    raise ValueError("monitor response has invalid field types")
                available = result.get("available")
                if not isinstance(available, bool):
                    raise ValueError("monitor result is missing the available flag")

                if check_at != self._last_check_at:
                    previous_available = self._last_available
                    self._last_check_at = check_at
                    self._last_available = available
                    if available and previous_available is not True:
                        self._available_since = check_at
                        self._delivered_umos.clear()
                    elif not available:
                        self._available_since = None
                        self._delivered_umos.clear()
                    self._save_state()

                if available:
                    if self._available_since is None:
                        self._available_since = check_at
                        self._delivered_umos.clear()
                        self._save_state()
                    await self._deliver_notifications(check_at, result)
                self._last_error = None
            except asyncio.CancelledError:
                raise
            except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
                current_error = str(exc)
                if current_error != self._last_error:
                    logger.warning("JWB monitor connection failed: %s", current_error)
                self._last_error = current_error
            await asyncio.sleep(self._poll_interval_seconds)

    async def _deliver_notifications(self, check_at: str, result: dict) -> None:
        """Deliver the active vacancy alert and retain failures for retry."""
        matching_pixels = result.get("matchingPixels")
        facility_name = result.get("facilityName")
        facility_label = facility_name if isinstance(facility_name, str) else "目标场馆"
        date_name = result.get("dateName")
        date_label = date_name if isinstance(date_name, str) else "目标日期"
        message = (
            f"交我办“{facility_label} / {date_label}”检测到目标时段可能有空余。\n"
            f"检测时间：{check_at}\n"
        )
        if isinstance(matching_pixels, int):
            message += f"视觉匹配像素：{matching_pixels}\n"
        message += "请手动打开官方页面核实并预约。"

        pending_umos = self._subscriptions - self._delivered_umos
        for umo in tuple(pending_umos):
            try:
                await self.context.send_message(
                    umo,
                    MessageChain().message(message),
                )
            except Exception:
                logger.exception("Failed to send a JWB vacancy notification")
                continue
            self._delivered_umos.add(umo)
            self._save_state()

    async def terminate(self) -> None:
        """Stop polling and release the HTTP client."""
        self._poll_task.cancel()
        try:
            await self._poll_task
        except asyncio.CancelledError:
            pass
        await self._client.aclose()
        logger.info("JWB venue monitor bridge stopped")
