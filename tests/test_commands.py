from __future__ import annotations

import pytest

from nalmai.commands import CommandParser
from nalmai.errors import CommandRejected
from nalmai.models import CommandKind


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("@Nalmai /help", CommandKind.HELP),
        ("@Nalmai /pair", CommandKind.PAIR_ISSUE),
        ("@Nalmai /pair 12345678", CommandKind.PAIR_CONSUME),
        ("@Nalmai /bind", CommandKind.BIND_GUIDE),
        ("@Nalmai /bind 123456 import-token", CommandKind.BIND),
        ("@Nalmai SGWCMAIDabc", CommandKind.SYNC),
        ("@Nalmai /wechat", CommandKind.WECHAT),
        ("@Nalmai /b50", CommandKind.B50),
        ("@Nalmai /status", CommandKind.STATUS),
        ("@Nalmai /unbind", CommandKind.UNBIND),
    ],
)
def test_parser_accepts_only_defined_commands(text: str, kind: CommandKind) -> None:
    assert CommandParser().parse(text).kind is kind


@pytest.mark.parametrize(
    "text",
    [
        "/bind 123456+token",
        "/bind 123456",
        "/bind abc token",
        "/bind 123 token extra",
        "SGWCMAIDabc extra",
        "/unknown",
        "/pair 123",
        "/pair abcdefgh",
        "/pair 12345678 extra",
    ],
)
def test_parser_rejects_undefined_forms(text: str) -> None:
    with pytest.raises(CommandRejected):
        CommandParser().parse(text)


def test_parser_preserves_exact_pairing_code() -> None:
    command = CommandParser().parse("/pair 01234567")
    assert command.kind is CommandKind.PAIR_CONSUME
    assert command.pairing_code == "01234567"
