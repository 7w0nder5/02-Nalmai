from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9_-]+")
_RAW_FORBIDDEN_MARKERS = (
    "SGWCMAID",
    "Import-Token",
    "Authorization",
    "client_secret",
    "AppSecret",
    "/bind ",
)


@dataclass(frozen=True, slots=True)
class CaptureResult:
    sanitized_path: Path
    raw_path: Path | None


class SecureQQEventCapture:
    """Persist QQ event models without logging their values.

    The sanitized copy keeps every key, container, null and scalar type. Non-empty
    scalar values are replaced with deterministic HMAC pseudonyms so equal input
    values remain equal across captures while different values remain different.
    """

    def __init__(
        self,
        root: Path,
        hmac_key: str,
        *,
        enabled: bool = True,
        raw_enabled: bool = False,
    ) -> None:
        if not hmac_key:
            raise ValueError("event capture requires a non-empty HMAC key")
        self._root = root
        self._key = hmac_key.encode("utf-8")
        self._enabled = enabled
        self._raw_enabled = raw_enabled

    def store(
        self,
        event_name: str,
        payload: dict[str, Any],
        *,
        allow_raw: bool = False,
    ) -> CaptureResult | None:
        if not self._enabled:
            return None

        sanitized_dir = self._root / "sanitized"
        private_dir = self._root / "private"
        self._prepare_directory(sanitized_dir)

        stem = self._make_stem(event_name)
        sanitized_path = sanitized_dir / f"{stem}.json"
        self._write_json(sanitized_path, self._sanitize(payload))

        raw_path: Path | None = None
        if self._raw_enabled and allow_raw:
            raw_json = self._json_text(payload)
            if not self._contains_forbidden_marker(raw_json):
                self._prepare_directory(private_dir)
                raw_path = private_dir / f"{stem}.json"
                self._write_text(raw_path, raw_json)

        return CaptureResult(sanitized_path=sanitized_path, raw_path=raw_path)

    def _sanitize(self, value: Any) -> Any:
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, str):
            if value == "":
                return value
            return f"STR_{self._digest('str', value)[:20]}"
        if isinstance(value, int):
            return int(self._digest("int", str(value))[:12], 16)
        if isinstance(value, float):
            if not math.isfinite(value):
                return 0.0
            return int(self._digest("float", repr(value))[:12], 16) / 1000.0
        if isinstance(value, list):
            return [self._sanitize(item) for item in value]
        if isinstance(value, tuple):
            return [self._sanitize(item) for item in value]
        if isinstance(value, dict):
            return {key: self._sanitize(item) for key, item in value.items()}
        raise TypeError(f"unsupported event value type: {type(value).__name__}")

    def _digest(self, kind: str, value: str) -> str:
        message = f"{kind}\0{value}".encode("utf-8")
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    @staticmethod
    def _contains_forbidden_marker(raw_json: str) -> bool:
        lowered = raw_json.casefold()
        return any(marker.casefold() in lowered for marker in _RAW_FORBIDDEN_MARKERS)

    @staticmethod
    def _prepare_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        try:
            path.chmod(0o700)
        except OSError:
            pass

    @staticmethod
    def _json_text(payload: dict[str, Any]) -> str:
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        self._write_text(path, self._json_text(payload))

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        temporary = path.with_suffix(f".{uuid4().hex}.tmp")
        temporary.write_text(content, encoding="utf-8", newline="\n")
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        os.replace(temporary, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass

    @staticmethod
    def _make_stem(event_name: str) -> str:
        safe_name = _SAFE_FILENAME.sub("_", event_name).strip("_") or "QQ_EVENT"
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        return f"{timestamp}-{safe_name}-{uuid4().hex[:12]}"
