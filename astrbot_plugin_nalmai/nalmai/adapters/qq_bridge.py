from __future__ import annotations

from typing import Any, Protocol

from nalmai.models import InboundMessage


class QQEventBridge(Protocol):
    """Translate a verified QQ event into Nalmai's internal message model."""

    def from_verified_event(self, event: dict[str, Any]) -> InboundMessage: ...


class UnconfiguredQQEventBridge:
    def from_verified_event(self, event: dict[str, Any]) -> InboundMessage:
        del event
        raise RuntimeError(
            "QQ 事件映射尚未配置：请提供一条真实脱敏事件 JSON，"
            "再实现稳定发送者、会话、私聊标记与消息引用的准确字段映射。"
        )

