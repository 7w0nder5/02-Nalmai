from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    database_path: Path
    fernet_key: str
    hmac_key: str
    internal_api_token: str
    allow_group_secrets: bool
    http_timeout_seconds: float
    b50_output_dir: Path
    arcade_provider: str = "unavailable"
    arcade_http_proxy: str | None = None
    local_api_port: int = 8000
    qq_expensive_cooldown_seconds: float = 30.0
    qq_max_concurrent_expensive: int = 2

    @classmethod
    def from_env(cls) -> "Settings":
        fernet_key = os.getenv("NALMAI_FERNET_KEY", "")
        hmac_key = os.getenv("NALMAI_HMAC_KEY", "")
        internal_api_token = os.getenv("NALMAI_INTERNAL_API_TOKEN", "")
        if not fernet_key or not hmac_key or not internal_api_token:
            raise RuntimeError(
                "NALMAI_FERNET_KEY、NALMAI_HMAC_KEY 与 "
                "NALMAI_INTERNAL_API_TOKEN 必须通过环境变量配置。"
            )
        return cls(
            database_path=Path(os.getenv("NALMAI_DATABASE_PATH", "./data/nalmai.sqlite3")),
            fernet_key=fernet_key,
            hmac_key=hmac_key,
            internal_api_token=internal_api_token,
            allow_group_secrets=_bool_env("NALMAI_ALLOW_GROUP_SECRETS"),
            http_timeout_seconds=float(os.getenv("NALMAI_HTTP_TIMEOUT_SECONDS", "15")),
            b50_output_dir=Path(os.getenv("NALMAI_B50_OUTPUT_DIR", "./data")),
            arcade_provider=os.getenv(
                "NALMAI_ARCADE_PROVIDER", "unavailable"
            ).strip(),
            arcade_http_proxy=os.getenv("NALMAI_ARCADE_HTTP_PROXY") or None,
            local_api_port=int(os.getenv("NALMAI_LOCAL_API_PORT", "8000")),
            qq_expensive_cooldown_seconds=float(
                os.getenv("NALMAI_QQ_EXPENSIVE_COOLDOWN_SECONDS", "30")
            ),
            qq_max_concurrent_expensive=int(
                os.getenv("NALMAI_QQ_MAX_CONCURRENT_EXPENSIVE", "2")
            ),
        )
