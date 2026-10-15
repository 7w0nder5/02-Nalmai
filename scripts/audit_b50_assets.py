from __future__ import annotations

import argparse
import asyncio
import sqlite3
from pathlib import Path
from typing import Any

import httpx


DIVINGFISH_BASE = "https://www.diving-fish.com/api/maimaidxprober"
DIVINGFISH_COVER = "https://www.diving-fish.com/covers/{song_id:05d}.png"
AWMC_COVER = "https://assets.awmc.team/covers/{song_id}.png"


def _username(database: Path) -> str:
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            "SELECT divingfish_username FROM users ORDER BY bound_at DESC LIMIT 1"
        ).fetchone()
    finally:
        connection.close()
    if row is None or not isinstance(row[0], str) or not row[0]:
        raise RuntimeError("数据库中没有已绑定的水鱼用户名。")
    return row[0]


async def _is_image(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    url: str,
) -> bool:
    try:
        async with semaphore:
            response = await client.get(url)
    except httpx.HTTPError:
        return False
    return (
        response.status_code == 200
        and response.headers.get("content-type", "").startswith("image/")
        and bool(response.content)
    )


async def audit(database: Path) -> None:
    username = _username(database)
    async with httpx.AsyncClient(
        timeout=30,
        headers={"User-Agent": "Nalmai-cover-audit/1.0"},
    ) as client:
        response = await client.post(
            f"{DIVINGFISH_BASE}/query/player",
            json={"username": username, "b50": "1"},
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()
        charts = payload["charts"]["sd"] + payload["charts"]["dx"]
        semaphore = asyncio.Semaphore(8)

        async def inspect(item: dict[str, Any]) -> tuple[int, str, bool, bool]:
            song_id = item["song_id"]
            title = item["title"]
            primary, fallback = await asyncio.gather(
                _is_image(
                    client,
                    semaphore,
                    DIVINGFISH_COVER.format(song_id=song_id),
                ),
                _is_image(
                    client,
                    semaphore,
                    AWMC_COVER.format(song_id=song_id),
                ),
            )
            return song_id, title, primary, fallback

        results = await asyncio.gather(*(inspect(item) for item in charts))

    print(f"B50 charts: {len(results)}")
    print(f"Song IDs: {sorted(item['song_id'] for item in charts)}")
    print(f"Rates: {sorted({item.get('rate') for item in charts})}")
    print(f"FC: {sorted({item.get('fc') or '' for item in charts})}")
    print(f"FS: {sorted({item.get('fs') or '' for item in charts})}")
    print(f"Diving-Fish raw ID covers: {sum(item[2] for item in results)}")
    print(f"AWMC raw ID covers: {sum(item[3] for item in results)}")
    print(
        "Covered by at least one source: "
        f"{sum(item[2] or item[3] for item in results)}"
    )
    print("Single-source differences:")
    for song_id, title, primary, fallback in results:
        if primary != fallback:
            print(
                f"- {song_id}: {title}; "
                f"Diving-Fish={primary}, AWMC={fallback}"
            )
    print("Missing from both sources:")
    for song_id, title, primary, fallback in results:
        if not primary and not fallback:
            print(f"- {song_id}: {title}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    asyncio.run(audit(args.database.resolve()))


if __name__ == "__main__":
    main()
