from __future__ import annotations

import httpx
import pytest

from nalmai.adapters.divingfish import HttpDivingFishClient


@pytest.mark.asyncio
async def test_cover_uses_raw_song_id_before_fallbacks(tmp_path) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "image/png"},
            content=b"png-data",
        )

    client = HttpDivingFishClient(cover_cache_dir=tmp_path)
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await client.get_cover(10042)
        again = await client.get_cover(10042)
    finally:
        await client.close()

    assert result == b"png-data"
    assert again == b"png-data"
    assert seen == ["https://www.diving-fish.com/covers/10042.png"]
    assert (tmp_path / "10042.png").read_bytes() == b"png-data"


@pytest.mark.asyncio
async def test_cover_falls_back_to_awmc_then_saltmeta(tmp_path) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen.append(url)
        if url == "https://meta.salt.realtvop.top/covers/001860.png":
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "image/png"},
                content=b"salt-cover",
            )
        return httpx.Response(404, request=request)

    client = HttpDivingFishClient(cover_cache_dir=tmp_path)
    await client._client.aclose()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await client.get_cover(11860)
    finally:
        await client.close()

    assert result == b"salt-cover"
    assert seen == [
        "https://www.diving-fish.com/covers/11860.png",
        "https://assets.awmc.team/covers/11860.png",
        "https://meta.salt.realtvop.top/covers/001860.png",
    ]
