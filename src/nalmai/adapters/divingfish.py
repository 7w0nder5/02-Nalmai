from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

from nalmai.errors import NalmaiError
from nalmai.models import UploadReceipt


class HttpDivingFishClient:
    base_url = "https://www.diving-fish.com/api/maimaidxprober"
    cover_sources = (
        "https://www.diving-fish.com/covers/{song_id:05d}.png",
        "https://assets.awmc.team/covers/{song_id}.png",
        "https://meta.salt.realtvop.top/covers/{salt_id}.png",
    )

    def __init__(
        self,
        timeout_seconds: float = 15.0,
        cover_cache_dir: Path | None = Path("./data/covers"),
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout_seconds,
            headers={"User-Agent": "Nalmai/0.1"},
        )
        self._music_data: list[dict[str, Any]] | None = None
        self._cover_cache: dict[int, bytes | None] = {}
        self._cover_cache_dir = cover_cache_dir
        self._asset_semaphore = asyncio.Semaphore(6)

    async def close(self) -> None:
        await self._client.aclose()

    async def get_records(self, import_token: str) -> dict[str, Any]:
        response = await self._request(
            "GET", "/player/records", headers={"Import-Token": import_token}
        )
        payload = self._json_object(response)
        if not isinstance(payload.get("username"), str) or not payload["username"]:
            raise NalmaiError(
                "DIVINGFISH_SCHEMA_ERROR",
                "水鱼完整成绩响应缺少有效 username。",
            )
        if not isinstance(payload.get("records"), list):
            raise NalmaiError(
                "DIVINGFISH_SCHEMA_ERROR",
                "水鱼完整成绩响应缺少 records 数组。",
            )
        return payload

    async def upload_records(
        self, import_token: str, records: list[dict[str, Any]]
    ) -> UploadReceipt:
        response = await self._request(
            "POST",
            "/player/update_records",
            headers={"Import-Token": import_token},
            json=records,
        )
        payload = self._json_object(response)
        message = payload.get("message")
        updates = payload.get("updates")
        creates = payload.get("creates")
        if message != "更新成功" or not isinstance(updates, int) or not isinstance(creates, int):
            raise NalmaiError(
                "DIVINGFISH_SCHEMA_ERROR",
                "水鱼上传响应不符合已确认的数据结构。",
            )
        return UploadReceipt(message=message, updates=updates, creates=creates)

    async def query_b50(self, username: str) -> dict[str, Any]:
        response = await self._request(
            "POST", "/query/player", json={"username": username, "b50": "1"}
        )
        payload = self._json_object(response)
        charts = payload.get("charts")
        if not isinstance(payload.get("nickname"), str):
            raise NalmaiError("DIVINGFISH_SCHEMA_ERROR", "B50 响应缺少 nickname。")
        if not isinstance(payload.get("rating"), (int, float)):
            raise NalmaiError("DIVINGFISH_SCHEMA_ERROR", "B50 响应缺少 rating。")
        if not isinstance(charts, dict):
            raise NalmaiError("DIVINGFISH_SCHEMA_ERROR", "B50 响应缺少 charts。")
        if not isinstance(charts.get("sd"), list) or not isinstance(charts.get("dx"), list):
            raise NalmaiError(
                "DIVINGFISH_SCHEMA_ERROR", "B50 响应缺少 charts.sd 或 charts.dx。"
            )
        return payload

    async def get_music_data(self) -> list[dict[str, Any]]:
        if self._music_data is not None:
            return self._music_data
        response = await self._request("GET", "/music_data")
        try:
            payload = response.json()
        except ValueError as exc:
            raise NalmaiError(
                "DIVINGFISH_INVALID_JSON", "水鱼曲目数据返回了无效 JSON。"
            ) from exc
        if not isinstance(payload, list) or not all(
            isinstance(item, dict) for item in payload
        ):
            raise NalmaiError(
                "DIVINGFISH_SCHEMA_ERROR", "水鱼曲目数据不是对象数组。"
            )
        self._music_data = payload
        return payload

    async def get_cover(self, song_id: int) -> bytes | None:
        if song_id in self._cover_cache:
            return self._cover_cache[song_id]
        cache_path = (
            self._cover_cache_dir / f"{song_id}.png"
            if self._cover_cache_dir is not None
            else None
        )
        if cache_path is not None and cache_path.is_file():
            result = await asyncio.to_thread(cache_path.read_bytes)
            if result:
                self._cover_cache[song_id] = result
                return result

        salt_id = "00" + f"{song_id:06d}"[2:]
        result = None
        for template in self.cover_sources:
            url = template.format(song_id=song_id, salt_id=salt_id)
            result = await self._download_cover(url)
            if result is not None:
                break

        if result is not None and cache_path is not None:
            await asyncio.to_thread(cache_path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(cache_path.write_bytes, result)
        self._cover_cache[song_id] = result
        return result

    async def _download_cover(self, url: str) -> bytes | None:
        for attempt in range(2):
            try:
                async with self._asset_semaphore:
                    response = await self._client.get(url)
            except httpx.HTTPError:
                if attempt == 0:
                    await asyncio.sleep(0.4)
                    continue
                return None

            content_type = response.headers.get("content-type", "")
            if (
                response.status_code == 200
                and response.content
                and content_type.startswith("image/")
            ):
                return response.content
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 0:
                    await asyncio.sleep(0.4)
                    continue
            return None
        return None

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise NalmaiError("DIVINGFISH_TIMEOUT", "水鱼接口请求超时。") from exc
        except httpx.HTTPError as exc:
            raise NalmaiError("DIVINGFISH_NETWORK_ERROR", "水鱼接口网络错误。") from exc

        if response.status_code == 400:
            raise NalmaiError("DIVINGFISH_BAD_REQUEST", "水鱼拒绝了请求或凭据无效。")
        if response.status_code == 401:
            raise NalmaiError("DIVINGFISH_UNAUTHORIZED", "水鱼凭据无效，请重新绑定。")
        if response.status_code == 403:
            raise NalmaiError("DIVINGFISH_FORBIDDEN", "水鱼隐私设置或权限阻止了请求。")
        if response.status_code == 429:
            raise NalmaiError("DIVINGFISH_RATE_LIMITED", "水鱼请求额度已达到限制。")
        if response.status_code >= 500:
            raise NalmaiError("DIVINGFISH_SERVER_ERROR", "水鱼服务暂时不可用。")
        if not 200 <= response.status_code < 300:
            raise NalmaiError("DIVINGFISH_HTTP_ERROR", "水鱼返回未处理的 HTTP 状态。")
        return response

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise NalmaiError("DIVINGFISH_INVALID_JSON", "水鱼返回了无效 JSON。") from exc
        if not isinstance(payload, dict):
            raise NalmaiError("DIVINGFISH_SCHEMA_ERROR", "水鱼响应不是 JSON 对象。")
        return payload
