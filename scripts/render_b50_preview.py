from __future__ import annotations

import argparse
import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from nalmai.adapters.b50_rich import RichB50Renderer
from nalmai.adapters.divingfish import HttpDivingFishClient
from nalmai.models import LocalPlayerProfile


def _load_local_data(
    database: Path,
) -> tuple[
    str,
    dict[tuple[str, str, int], tuple[int, int | None]],
    LocalPlayerProfile | None,
]:
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        user = connection.execute(
            "SELECT platform_user_id, divingfish_username "
            "FROM users ORDER BY bound_at DESC LIMIT 1"
        ).fetchone()
        if user is None:
            raise RuntimeError("数据库中没有已绑定用户。")
        rows = connection.execute(
            "SELECT title, chart_type, level_index, play_count, dx_star "
            "FROM local_chart_stats WHERE platform_user_id = ?",
            (user["platform_user_id"],),
        ).fetchall()
        profile_table = connection.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'local_player_profiles'"
        ).fetchone()
        profile_row = (
            connection.execute(
                "SELECT * FROM local_player_profiles WHERE platform_user_id = ?",
                (user["platform_user_id"],),
            ).fetchone()
            if profile_table is not None
            else None
        )
    finally:
        connection.close()

    stats = {
        (str(row["title"]), str(row["chart_type"]), int(row["level_index"])): (
            int(row["play_count"]),
            int(row["dx_star"]) if row["dx_star"] is not None else None,
        )
        for row in rows
    }
    profile = None
    if profile_row is not None:
        profile = LocalPlayerProfile(
            platform_user_id=str(profile_row["platform_user_id"]),
            player_name=str(profile_row["player_name"]),
            rating=int(profile_row["rating"]),
            title_text=str(profile_row["title_text"]),
            title_rarity=str(profile_row["title_rarity"]),
            star_count=int(profile_row["star_count"]),
            avatar_name=str(profile_row["avatar_name"]),
            nameplate_name=str(profile_row["nameplate_name"]),
            nameplate_description=str(profile_row["nameplate_description"]),
            frame_name=str(profile_row["frame_name"]),
            frame_description=str(profile_row["frame_description"]),
            version_logo=bytes(profile_row["version_logo"]),
            avatar=bytes(profile_row["avatar"]),
            rating_base=bytes(profile_row["rating_base"]),
            course_rank=bytes(profile_row["course_rank"]),
            class_rank=bytes(profile_row["class_rank"]),
            nameplate=bytes(profile_row["nameplate"]),
            frame=bytes(profile_row["frame"]),
            updated_at=datetime.fromisoformat(profile_row["updated_at"]),
        )
    return str(user["divingfish_username"]), stats, profile


def _merge_stats(
    payload: dict[str, Any],
    stats: dict[tuple[str, str, int], tuple[int, int | None]],
) -> None:
    charts = payload.get("charts")
    if not isinstance(charts, dict):
        return
    for section in ("sd", "dx"):
        entries = charts.get(section)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            key = (entry["title"], entry["type"], entry["level_index"])
            local = stats.get(key)
            if local is not None:
                entry["play_count"], entry["dx_star"] = local


async def render(database: Path, output: Path) -> None:
    username, stats, profile = _load_local_data(database)
    cover_cache = output.parent / "cover-cache"
    client = HttpDivingFishClient(30, cover_cache_dir=cover_cache)
    try:
        payload = await client.query_b50(username)
        _merge_stats(payload, stats)
        if profile is not None:
            payload["local_player_profile"] = profile
        result = await RichB50Renderer(client).render(payload)
    finally:
        await client.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(result.content)
    charts = payload["charts"]["sd"] + payload["charts"]["dx"]
    unique_song_ids = {entry["song_id"] for entry in charts}
    available = sum(
        client._cover_cache.get(song_id) is not None for song_id in unique_song_ids
    )
    print(f"Preview: {output}")
    print(f"Charts: {len(charts)}")
    print(f"Unique covers: {available}/{len(unique_song_ids)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    asyncio.run(render(args.database.resolve(), args.output.resolve()))


if __name__ == "__main__":
    main()
