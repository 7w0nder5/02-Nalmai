from __future__ import annotations

import re


_SGWC = re.compile(r"SGWCMAID[^\s]*")
_HEADER = re.compile(
    r"(?i)(Import-Token|Authorization|client_secret)\s*[:=]\s*([^\s,;]+)"
)


def redact_sensitive(value: str) -> str:
    value = _SGWC.sub("SGWCMAID[REDACTED]", value)
    return _HEADER.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)


def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "********"
    return f"{value[:4]}…{value[-4:]}"


def mask_qq(value: str) -> str:
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"

