from __future__ import annotations

import json
import inspect
from pathlib import Path
import tomllib
from types import SimpleNamespace
import unittest

from nalmai.qq_main import (
    _on_bot_connect,
    _on_bot_disconnect,
    _require_capture_hmac_key,
    _require_qq_bots,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class QQProjectConfigTests(unittest.TestCase):
    def test_example_uses_exact_minimum_websocket_configuration(self) -> None:
        lines = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        value = next(line.partition("=")[2] for line in lines if line.startswith("QQ_BOTS="))
        bots = json.loads(value)

        self.assertEqual(len(bots), 1)
        bot = bots[0]
        self.assertEqual(
            set(bot), {"id", "token", "secret", "intent", "use_websocket"}
        )
        self.assertEqual(bot["token"], "")
        self.assertIs(bot["use_websocket"], True)
        enabled = {name for name, state in bot["intent"].items() if state}
        self.assertEqual(enabled, {"c2c_group_at_messages"})

    def test_qq_direct_dependencies_are_locked(self) -> None:
        project = tomllib.loads(
            (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        qq = project["project"]["optional-dependencies"]["qq"]

        self.assertIn("nonebot2[httpx,websockets]==2.5.0", qq)
        self.assertIn("nonebot-adapter-qq==1.7.2", qq)
        self.assertEqual(
            project["project"]["scripts"]["nalmai-qq"],
            "nalmai.qq_main:main",
        )

    def test_event_directory_is_ignored_by_git(self) -> None:
        ignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("data/qq-events/", ignore.splitlines())

    def test_public_mode_resource_limits_are_documented(self) -> None:
        lines = (PROJECT_ROOT / ".env.example").read_text(
            encoding="utf-8"
        ).splitlines()
        self.assertIn("NALMAI_QQ_EXPENSIVE_COOLDOWN_SECONDS=30", lines)
        self.assertIn("NALMAI_QQ_MAX_CONCURRENT_EXPENSIVE=2", lines)

    def test_startup_rejects_missing_bot_configuration_without_echoing_secret(
        self,
    ) -> None:
        for value in (None, [], "not-a-list"):
            with self.assertRaisesRegex(RuntimeError, "缺少 QQ_BOTS"):
                _require_qq_bots(SimpleNamespace(qq_bots=value))

        _require_qq_bots(SimpleNamespace(qq_bots=[self._valid_bot()]))

    def test_startup_rejects_broad_intents_and_non_websocket_mode(self) -> None:
        bot = self._valid_bot()
        bot["intent"]["guilds"] = True
        with self.assertRaisesRegex(RuntimeError, "只能启用"):
            _require_qq_bots(SimpleNamespace(qq_bots=[bot]))

        bot = self._valid_bot()
        bot["use_websocket"] = False
        with self.assertRaisesRegex(RuntimeError, "use_websocket=true"):
            _require_qq_bots(SimpleNamespace(qq_bots=[bot]))

        bot = self._valid_bot()
        bot.pop("token")
        with self.assertRaisesRegex(RuntimeError, "兼容字段"):
            _require_qq_bots(SimpleNamespace(qq_bots=[bot]))

    def test_connection_hooks_use_nonebot_compatible_bot_parameter(self) -> None:
        for hook in (_on_bot_connect, _on_bot_disconnect):
            parameters = list(inspect.signature(hook).parameters.values())
            self.assertEqual(len(parameters), 1)
            self.assertEqual(parameters[0].name, "bot")
            self.assertIs(parameters[0].annotation, inspect.Parameter.empty)

    def test_startup_requires_capture_hmac_key(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "缺少 NALMAI_HMAC_KEY"):
            _require_capture_hmac_key(SimpleNamespace(nalmai_hmac_key=""))
        _require_capture_hmac_key(SimpleNamespace(nalmai_hmac_key="secret"))

    @staticmethod
    def _valid_bot() -> dict[str, object]:
        return {
            "id": "APP-ID",
            "token": "",
            "secret": "APP-SECRET",
            "intent": {
                "guilds": False,
                "guild_members": False,
                "guild_messages": False,
                "guild_message_reactions": False,
                "direct_message": False,
                "open_forum_event": False,
                "audio_live_member": False,
                "group_members": False,
                "c2c_group_at_messages": True,
                "interaction": False,
                "message_audit": False,
                "forum_event": False,
                "audio_action": False,
                "at_messages": False,
            },
            "use_websocket": True,
        }


if __name__ == "__main__":
    unittest.main()
