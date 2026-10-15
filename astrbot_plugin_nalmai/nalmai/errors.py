from __future__ import annotations


class NalmaiError(Exception):
    """A safe application error carrying a stable, non-secret code."""

    def __init__(self, code: str, public_message: str) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message


class CommandRejected(NalmaiError):
    pass


class BindingRequired(NalmaiError):
    def __init__(self) -> None:
        super().__init__("BINDING_REQUIRED", "请先使用 /bind 完成水鱼绑定。")


class UpstreamNotConfigured(NalmaiError):
    def __init__(self) -> None:
        super().__init__(
            "ARCADE_PROVIDER_NOT_CONFIGURED",
            "成绩采集适配器尚未配置，无法读取 SGWCMAID 凭据。",
        )

