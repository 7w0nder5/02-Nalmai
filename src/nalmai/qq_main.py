from __future__ import annotations

from typing import Any


_QQ_INTENT_KEYS = {
    "guilds",
    "guild_members",
    "guild_messages",
    "guild_message_reactions",
    "direct_message",
    "open_forum_event",
    "audio_live_member",
    "group_members",
    "c2c_group_at_messages",
    "interaction",
    "message_audit",
    "forum_event",
    "audio_action",
    "at_messages",
}


def main() -> None:
    try:
        import nonebot
        from nonebot.adapters.qq import Adapter as QQAdapter
    except ImportError as exc:
        raise RuntimeError(
            'QQ 依赖未安装。请先执行：python -m pip install -e ".[qq]"'
        ) from exc

    nonebot.init(
        driver="~httpx+~websockets",
        log_level="ERROR",
    )
    driver = nonebot.get_driver()
    _require_qq_bots(driver.config)
    _require_capture_hmac_key(driver.config)
    driver.register_adapter(QQAdapter)

    driver.on_bot_connect(_on_bot_connect)
    driver.on_bot_disconnect(_on_bot_disconnect)

    loaded = nonebot.load_plugin("nalmai.adapters.qq_nonebot")
    if loaded is None:
        raise RuntimeError("Nalmai QQ 插件加载失败。")

    print("Nalmai QQ 正在连接；框架日志已限制为 ERROR 级别以避免输出事件内容。")
    nonebot.run()


def _require_qq_bots(config: Any) -> None:
    qq_bots = getattr(config, "qq_bots", None)
    if not isinstance(qq_bots, list) or not qq_bots:
        raise RuntimeError(
            "缺少 QQ_BOTS。请复制 .env.example 为 .env，并只在本机填写 "
            "AppID 与 AppSecret。"
        )

    for bot in qq_bots:
        if not isinstance(bot, dict):
            raise RuntimeError("QQ_BOTS 必须是 .env.example 所示的 JSON 对象列表。")
        app_id = bot.get("id")
        compatibility_token = bot.get("token")
        app_secret = bot.get("secret")
        if not isinstance(app_id, str) or not app_id or "填写" in app_id:
            raise RuntimeError("QQ_BOTS 中尚未填写有效 AppID。")
        if (
            not isinstance(app_secret, str)
            or not app_secret
            or "填写" in app_secret
        ):
            raise RuntimeError("QQ_BOTS 中尚未填写有效 AppSecret。")
        if compatibility_token != "":
            raise RuntimeError(
                "QQ_BOTS 的 token 是适配器兼容字段，必须保留为空字符串。"
            )
        if bot.get("use_websocket") is not True:
            raise RuntimeError("Nalmai QQ 接入只允许 use_websocket=true。")
        intent = bot.get("intent")
        if not isinstance(intent, dict):
            raise RuntimeError("QQ_BOTS 必须显式配置最小权限 intent。")
        if set(intent) != _QQ_INTENT_KEYS or not all(
            isinstance(state, bool) for state in intent.values()
        ):
            raise RuntimeError(
                "QQ_BOTS 的 intent 必须完整复制 .env.example，且所有值为布尔值。"
            )
        enabled = {name for name, state in intent.items() if state is True}
        if enabled != {"c2c_group_at_messages"}:
            raise RuntimeError(
                "QQ_BOTS 只能启用 c2c_group_at_messages；请恢复 .env.example 配置。"
            )


def _require_capture_hmac_key(config: Any) -> None:
    key = getattr(config, "nalmai_hmac_key", None)
    if not isinstance(key, str) or not key:
        raise RuntimeError(
            "缺少 NALMAI_HMAC_KEY。请运行 scripts/generate_keys.py 并只在本机填写。"
        )


async def _on_bot_connect(bot) -> None:
    """NoneBot 2.5 通过参数名 ``bot`` 注入连接实例。"""
    del bot
    print("Nalmai QQ WebSocket 已连接。")


async def _on_bot_disconnect(bot) -> None:
    """NoneBot 2.5 通过参数名 ``bot`` 注入断开连接的实例。"""
    del bot
    print("Nalmai QQ WebSocket 已断开，适配器将按策略重连。")


if __name__ == "__main__":
    main()
