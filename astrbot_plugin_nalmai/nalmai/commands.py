from __future__ import annotations

from nalmai.errors import CommandRejected
from nalmai.models import CommandKind, ParsedCommand


HELP_TEXT = """Nalmai 群友使用帮助
群聊请先 @Nalmai；Import-Token、SGWCMAID 和微信授权信息只能私聊处理。

首次使用（每位群友独立绑定）
1. 私聊：/bind <QQ号码> <Import-Token>
2. 私聊：/pair
3. 5 分钟内回到目标群：@Nalmai /pair <8位配对码>
4. 群内：@Nalmai /b50

/help
查看本帮助。

/status
检查 QQ WebSocket 是否在线。

/pair
私聊生成 8 位一次性配对码，5 分钟有效。

/pair <配对码>
在目标群绑定当前群身份；配对码使用后立即失效。

/bind
获取安全绑定说明；不要在群聊发送 Import-Token。

/bind <QQ号码> <Import-Token>
绑定水鱼账号，仅限私聊或安全入口。

SGWCMAID...
私聊提交舞萌成绩凭据。管理员启用 maimai.py 机台适配器后，可读取基础成绩
并热更新水鱼。该路线不会返回新的 FC、FS、PC 次数；缺失值保留水鱼原数据。

/wechat
仅限私聊，且由机器人管理员在运行 Nalmai 的 Windows 电脑上辅助执行。
它不是群友远程自助入口；不要把授权链接发给其他人。

/b50
生成已绑定水鱼账号的 B50 图片，包含封面、定数、RA、评级、FC/FS、
DX 星数、歌曲 ID、版本及 SD/DX 类型；PC 缺失时明确显示为 —。

Windows 微信 OAuth 页面采集是另一条本机路线，可解析 FC、FS 与单谱面 PC；
它不等同于 SGWC 身份码，也不会把两种凭据混用。

/unbind
删除绑定和本地加密凭据，仅限私聊。

请先私聊绑定并生成配对码，再到群内完成配对。
每位群友的数据按自己的私聊身份隔离。不要在群聊发送任何凭据。"""


class CommandParser:
    mention = "@Nalmai"

    def parse(self, raw_text: str) -> ParsedCommand:
        text = raw_text.strip()
        if text.startswith(self.mention):
            text = text[len(self.mention) :].strip()

        if text == "/help":
            return ParsedCommand(CommandKind.HELP)
        if text == "/pair":
            return ParsedCommand(CommandKind.PAIR_ISSUE)
        if text.startswith("/pair"):
            parts = text.split()
            if (
                len(parts) != 2
                or parts[0] != "/pair"
                or not parts[1].isascii()
                or not parts[1].isdigit()
                or len(parts[1]) != 8
            ):
                raise CommandRejected(
                    "INVALID_PAIR_SYNTAX",
                    "配对格式：/pair <8位配对码>。",
                )
            return ParsedCommand(
                CommandKind.PAIR_CONSUME,
                pairing_code=parts[1],
            )
        if text == "/bind":
            return ParsedCommand(CommandKind.BIND_GUIDE)
        if text == "/b50":
            return ParsedCommand(CommandKind.B50)
        if text == "/wechat":
            return ParsedCommand(CommandKind.WECHAT)
        if text == "/status":
            return ParsedCommand(CommandKind.STATUS)
        if text == "/unbind":
            return ParsedCommand(CommandKind.UNBIND)

        if text.startswith("/bind"):
            parts = text.split()
            if len(parts) != 3 or parts[0] != "/bind":
                raise CommandRejected(
                    "INVALID_BIND_SYNTAX",
                    "绑定格式：/bind <QQ号码> <Import-Token>，参数之间使用空格。",
                )
            claimed_qq, import_token = parts[1], parts[2]
            if not claimed_qq.isascii() or not claimed_qq.isdigit():
                raise CommandRejected("INVALID_QQ", "QQ号码必须只包含 ASCII 数字。")
            if not import_token:
                raise CommandRejected("EMPTY_IMPORT_TOKEN", "Import-Token 不能为空。")
            return ParsedCommand(
                CommandKind.BIND,
                claimed_qq=claimed_qq,
                import_token=import_token,
            )

        if text.startswith("SGWCMAID"):
            if any(ch.isspace() for ch in text):
                raise CommandRejected(
                    "INVALID_SGWC_FORMAT",
                    "SGWCMAID 凭据必须作为一个完整参数提交。",
                )
            return ParsedCommand(CommandKind.SYNC, sgwc_credential=text)

        raise CommandRejected("UNKNOWN_COMMAND", "无法识别命令。")
