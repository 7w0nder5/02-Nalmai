from __future__ import annotations

import argparse
import asyncio
import ctypes
import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
from mitmproxy import http, options
from mitmproxy.tools.dump import DumpMaster

from .capture import (
    CALLBACK_HOST,
    CALLBACK_PATH,
    CaptureBundle,
    CaptureError,
    IntegratedCaptureResult,
    build_authorization_url,
    collect_and_sync,
    validate_callback_params,
)
from .local_api import LocalApiError, NalmaiLocalApiClient


OBSERVED_WECHAT_PROCESSES = (
    "Weixin.exe",
    "WeChatAppEx.exe",
)


@dataclass(slots=True)
class CaptureState:
    completed: asyncio.Event
    bundle: CaptureBundle | None = None
    integrated_result: IntegratedCaptureResult | None = None
    error_type: str | None = None
    error_message: str | None = None
    started: bool = False


class WechatCallbackAddon:
    def __init__(
        self,
        state: CaptureState,
        output_root: Path,
        shared_asset_root: Path,
        callback_hosts: frozenset[str],
        local_api: NalmaiLocalApiClient,
    ) -> None:
        self._state = state
        self._output_root = output_root
        self._shared_asset_root = shared_asset_root
        self._callback_hosts = callback_hosts
        self._local_api = local_api
        self._task: asyncio.Task[None] | None = None

    async def request(self, flow: http.HTTPFlow) -> None:
        if (
            self._state.started
            or flow.request.host not in self._callback_hosts
            or flow.request.path.split("?", 1)[0] != CALLBACK_PATH
        ):
            return
        try:
            params = validate_callback_params(
                {key: flow.request.query.get(key, "") for key in flow.request.query.keys()}
            )
        except CaptureError:
            flow.response = http.Response.make(
                400,
                "授权参数不完整，请关闭页面后重新运行采集器。".encode("utf-8"),
                {"Content-Type": "text/plain; charset=utf-8"},
            )
            return

        self._state.started = True
        flow.response = http.Response.make(
            200,
            "授权已由 Nalmai 本机采集器接收，可以关闭本页。".encode("utf-8"),
            {"Content-Type": "text/plain; charset=utf-8"},
        )
        self._task = asyncio.create_task(self._collect(params))

    async def _collect(self, params: dict[str, str]) -> None:
        try:
            result = await collect_and_sync(
                params,
                self._output_root,
                self._local_api,
                self._shared_asset_root,
            )
            self._state.integrated_result = result
            self._state.bundle = result.bundle
        except CaptureError as exc:
            self._state.error_type = type(exc).__name__
            self._state.error_message = str(exc)
        except LocalApiError as exc:
            self._state.error_type = type(exc).__name__
            self._state.error_message = str(exc)
        except httpx.HTTPStatusError as exc:
            self._state.error_type = type(exc).__name__
            self._state.error_message = f"HTTP {exc.response.status_code}"
        except Exception as exc:
            self._state.error_type = type(exc).__name__
        finally:
            self._state.completed.set()


def _is_administrator() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _copy_to_clipboard(value: str) -> None:
    subprocess.run(
        ["clip.exe"],
        input=value,
        text=True,
        encoding="ascii",
        check=True,
    )


def resolve_callback_hosts() -> frozenset[str]:
    try:
        records = socket.getaddrinfo(
            CALLBACK_HOST,
            80,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise CaptureError("无法解析华立微信授权服务器地址。") from exc
    addresses = {record[4][0] for record in records if record[4]}
    if not addresses:
        raise CaptureError("华立微信授权服务器没有返回可用地址。")
    return frozenset({CALLBACK_HOST, *addresses})


def plaintext_http_allow_pattern() -> str:
    """Route only plaintext HTTP from the selected WeChat processes.

    CDN DNS answers can differ between the Python process and WeChat.  The addon
    still accepts only the exact Wahlap callback host and path, while HTTPS on
    port 443 never enters the capture path.
    """
    return r"^.+:80$"


def callback_http_allow_pattern() -> str:
    """Accept only the plaintext Wahlap callback sent by Clash."""
    escaped_host = CALLBACK_HOST.replace(".", r"\.")
    return rf"^{escaped_host}:80$"


async def run_capture(
    output_root: Path,
    shared_asset_root: Path,
    timeout_seconds: int,
    processes: tuple[str, ...],
    proxy_mode: str,
    listen_host: str,
    listen_port: int,
    wait_for_enter: bool,
    local_api_url: str,
    internal_api_token: str,
) -> int:
    if sys.platform != "win32":
        print("本采集入口只支持 Windows 电脑微信。")
        return 2
    if proxy_mode == "local" and not _is_administrator():
        print("请关闭此窗口，并用“以管理员身份运行”的 PowerShell 重新启动。")
        return 2

    if proxy_mode == "local" and not processes:
        print("至少需要指定一个 Windows 微信进程名。")
        return 2

    output_root.mkdir(parents=True, exist_ok=True)
    shared_asset_root.mkdir(parents=True, exist_ok=True)
    callback_hosts = (
        resolve_callback_hosts()
        if proxy_mode == "local"
        else frozenset({CALLBACK_HOST})
    )
    state = CaptureState(asyncio.Event())
    try:
        local_api = NalmaiLocalApiClient(local_api_url, internal_api_token)
    except LocalApiError as exc:
        print(str(exc))
        return 2
    addon = WechatCallbackAddon(
        state,
        output_root,
        shared_asset_root,
        callback_hosts,
        local_api,
    )
    if proxy_mode == "local":
        process_spec = ",".join(name.removesuffix(".exe") for name in processes)
        proxy_options = options.Options(
            mode=[f"local:{process_spec}"],
            allow_hosts=[plaintext_http_allow_pattern()],
            show_ignored_hosts=False,
        )
    else:
        proxy_options = options.Options(
            mode=[f"regular@{listen_host}:{listen_port}"],
            allow_hosts=[callback_http_allow_pattern()],
            show_ignored_hosts=False,
        )
    master = DumpMaster(proxy_options, with_termlog=False, with_dumper=False)
    master.addons.add(addon)
    proxy_task = asyncio.create_task(master.run())

    try:
        if wait_for_enter:
            print("采集器已就绪。请先打开微信文件传输助手，准备好后在此按 Enter。")
            await asyncio.to_thread(input)
        await local_api.claim()
        print("已领取 QQ 私聊创建的微信授权任务。")
        async with httpx.AsyncClient(timeout=20.0) as client:
            auth_url = await build_authorization_url(client)
        _copy_to_clipboard(auth_url)
        print("微信授权链接已复制到剪贴板。")
        print("请在 Windows 微信中打开“文件传输助手”，粘贴并发送，然后点击该链接。")
        print("不要把链接发送给其他人；采集器会在一次授权后自动停止。")
        await asyncio.wait_for(state.completed.wait(), timeout=timeout_seconds)
    except TimeoutError:
        print("等待授权超时；未保存 Cookie 或授权参数。")
        return 3
    except CaptureError as exc:
        print(str(exc))
        return 3
    except LocalApiError as exc:
        print(str(exc))
        return 3
    except Exception as exc:
        print(f"采集器启动失败：{type(exc).__name__}。未输出凭据。")
        return 3
    finally:
        master.shutdown()
        try:
            await asyncio.wait_for(proxy_task, timeout=10)
        except (TimeoutError, asyncio.CancelledError):
            proxy_task.cancel()

    if state.bundle is None:
        detail = state.error_message or state.error_type or "UnknownError"
        print(f"采集失败：{detail}。未输出凭据。")
        return 4
    print("脱敏资料已生成：")
    print(state.bundle.archive.resolve())
    print(
        f"其中包含 {state.bundle.score_page_count} 个成绩列表页面和 "
        f"{state.bundle.detail_page_count} 个成绩详情页面，以及 "
        f"{state.bundle.profile_page_count} 个玩家资料页面。"
    )
    print(
        f"本机共享素材库已登记 {state.bundle.shared_asset_count} 张收藏图片；"
        "后续所有群友生成 B50 时可直接复用。"
    )
    print("压缩包不包含 Cookie、微信授权参数或原始网页。")
    if state.integrated_result is not None:
        result = state.integrated_result
        print(
            f"已上传 {result.score_count} 条成绩，并保存 "
            f"{result.saved_detail_count}/{result.requested_detail_count} 个 "
            "B50 谱面详情。"
        )
        if result.missing_detail_count:
            print(
                f"其中 {result.missing_detail_count} 个 B50 谱面没有匹配到详情页；"
                "已保存其余准确结果。"
            )
        if local_api.last_job_id:
            print(f"水鱼同步任务：{local_api.last_job_id}")
        print("现在可以在 QQ 中发送 /b50。")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Nalmai Windows 微信成绩页面脱敏采集器")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("./data/wechat-capture"),
        help="脱敏输出目录",
    )
    parser.add_argument(
        "--shared-output",
        type=Path,
        default=Path("./data/shared-assets"),
        help="供所有 QQ 用户共用的本机收藏素材目录",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="等待微信授权的秒数",
    )
    parser.add_argument(
        "--process",
        action="append",
        default=None,
        help="Windows 微信进程名；可重复指定",
    )
    parser.add_argument(
        "--proxy-mode",
        choices=("local", "regular"),
        default="local",
        help="local 为进程捕获；regular 供 Clash 精确规则转发",
    )
    parser.add_argument(
        "--listen-host",
        default="127.0.0.1",
        help="regular 模式监听地址",
    )
    parser.add_argument(
        "--listen-port",
        type=int,
        default=8080,
        help="regular 模式监听端口",
    )
    parser.add_argument(
        "--wait-for-enter",
        action="store_true",
        help="代理就绪后等待 Enter，再生成短时效微信授权链接",
    )
    args = parser.parse_args()
    processes = tuple(args.process or OBSERVED_WECHAT_PROCESSES)
    raise SystemExit(
        asyncio.run(
            run_capture(
                args.output,
                args.shared_output,
                args.timeout,
                processes,
                args.proxy_mode,
                args.listen_host,
                args.listen_port,
                args.wait_for_enter,
                os.getenv("NALMAI_LOCAL_API_URL", "http://127.0.0.1:8000"),
                os.getenv("NALMAI_INTERNAL_API_TOKEN", ""),
            )
        )
    )


if __name__ == "__main__":
    main()
