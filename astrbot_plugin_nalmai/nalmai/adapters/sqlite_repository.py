from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from nalmai.models import (
    BindingStatus,
    JobStatus,
    LocalChartStat,
    LocalPlayerProfile,
    SyncJob,
    UserBinding,
    WechatOAuthSession,
    WechatSessionStatus,
)


class SqliteRepository:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        self._connection.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS users (
                platform_user_id TEXT PRIMARY KEY,
                claimed_qq TEXT NOT NULL,
                divingfish_username TEXT NOT NULL,
                import_token_ciphertext BLOB NOT NULL,
                credential_key_version TEXT NOT NULL,
                credential_mask TEXT NOT NULL,
                binding_status TEXT NOT NULL,
                bound_at TEXT NOT NULL,
                credential_rotated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sync_jobs (
                id TEXT PRIMARY KEY,
                platform_user_id TEXT NOT NULL,
                status TEXT NOT NULL,
                credential_digest TEXT NOT NULL,
                score_count INTEGER NOT NULL,
                uploaded_count INTEGER NOT NULL,
                skipped_count INTEGER NOT NULL,
                error_code TEXT,
                created_at TEXT NOT NULL,
                finished_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sync_jobs_user_created
                ON sync_jobs(platform_user_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS qq_identity_links (
                group_identity TEXT PRIMARY KEY,
                private_identity TEXT NOT NULL,
                linked_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_qq_identity_links_private
                ON qq_identity_links(private_identity);
            CREATE TABLE IF NOT EXISTS qq_pairing_codes (
                code_digest TEXT PRIMARY KEY,
                private_identity TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_qq_pairing_codes_private
                ON qq_pairing_codes(private_identity);
            CREATE TABLE IF NOT EXISTS wechat_oauth_sessions (
                id TEXT PRIMARY KEY,
                platform_user_id TEXT NOT NULL,
                status TEXT NOT NULL,
                token_digest TEXT UNIQUE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                claimed_at TEXT,
                finished_at TEXT,
                error_code TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_wechat_sessions_status_created
                ON wechat_oauth_sessions(status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_wechat_sessions_user_created
                ON wechat_oauth_sessions(platform_user_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS local_chart_stats (
                platform_user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                chart_type TEXT NOT NULL,
                level_index INTEGER NOT NULL,
                play_count INTEGER NOT NULL,
                dx_star INTEGER,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(platform_user_id, title, chart_type, level_index)
            );
            CREATE INDEX IF NOT EXISTS idx_local_chart_stats_user
                ON local_chart_stats(platform_user_id);
            CREATE TABLE IF NOT EXISTS local_player_profiles (
                platform_user_id TEXT PRIMARY KEY,
                player_name TEXT NOT NULL,
                rating INTEGER NOT NULL,
                title_text TEXT NOT NULL,
                title_rarity TEXT NOT NULL,
                star_count INTEGER NOT NULL,
                avatar_name TEXT NOT NULL,
                nameplate_name TEXT NOT NULL,
                nameplate_description TEXT NOT NULL,
                frame_name TEXT NOT NULL,
                frame_description TEXT NOT NULL,
                version_logo BLOB NOT NULL,
                avatar BLOB NOT NULL,
                rating_base BLOB NOT NULL,
                course_rank BLOB NOT NULL,
                class_rank BLOB NOT NULL,
                nameplate BLOB NOT NULL,
                frame BLOB NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        self._connection.commit()

    async def get(self, platform_user_id: str) -> UserBinding | None:
        row = self._connection.execute(
            "SELECT * FROM users WHERE platform_user_id = ?", (platform_user_id,)
        ).fetchone()
        if row is None:
            return None
        return UserBinding(
            platform_user_id=row["platform_user_id"],
            claimed_qq=row["claimed_qq"],
            divingfish_username=row["divingfish_username"],
            credential_ciphertext=bytes(row["import_token_ciphertext"]),
            credential_key_version=row["credential_key_version"],
            credential_mask=row["credential_mask"],
            status=BindingStatus(row["binding_status"]),
            bound_at=datetime.fromisoformat(row["bound_at"]),
            credential_rotated_at=datetime.fromisoformat(row["credential_rotated_at"]),
        )

    async def save(self, item: UserBinding | SyncJob) -> None:
        if isinstance(item, UserBinding):
            self._save_binding(item)
        elif isinstance(item, SyncJob):
            self._save_job(item)
        else:
            raise TypeError("SqliteRepository 只接受 UserBinding 或 SyncJob。")

    def _save_binding(self, binding: UserBinding) -> None:
        self._connection.execute(
            """
            INSERT INTO users (
                platform_user_id, claimed_qq, divingfish_username,
                import_token_ciphertext, credential_key_version, credential_mask,
                binding_status, bound_at, credential_rotated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform_user_id) DO UPDATE SET
                claimed_qq=excluded.claimed_qq,
                divingfish_username=excluded.divingfish_username,
                import_token_ciphertext=excluded.import_token_ciphertext,
                credential_key_version=excluded.credential_key_version,
                credential_mask=excluded.credential_mask,
                binding_status=excluded.binding_status,
                credential_rotated_at=excluded.credential_rotated_at
            """,
            (
                binding.platform_user_id,
                binding.claimed_qq,
                binding.divingfish_username,
                binding.credential_ciphertext,
                binding.credential_key_version,
                binding.credential_mask,
                binding.status.value,
                binding.bound_at.isoformat(),
                binding.credential_rotated_at.isoformat(),
            ),
        )
        self._connection.commit()

    def _save_job(self, job: SyncJob) -> None:
        self._connection.execute(
            """
            INSERT INTO sync_jobs (
                id, platform_user_id, status, credential_digest, score_count,
                uploaded_count, skipped_count, error_code, created_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,
                score_count=excluded.score_count,
                uploaded_count=excluded.uploaded_count,
                skipped_count=excluded.skipped_count,
                error_code=excluded.error_code,
                finished_at=excluded.finished_at
            """,
            (
                job.id,
                job.platform_user_id,
                job.status.value,
                job.credential_digest,
                job.score_count,
                job.uploaded_count,
                job.skipped_count,
                job.error_code,
                job.created_at.isoformat(),
                job.finished_at.isoformat() if job.finished_at else None,
            ),
        )
        self._connection.commit()

    async def delete(self, platform_user_id: str) -> bool:
        with self._connection:
            cursor = self._connection.execute(
                "DELETE FROM users WHERE platform_user_id = ?", (platform_user_id,)
            )
            self._connection.execute(
                "DELETE FROM wechat_oauth_sessions WHERE platform_user_id = ?",
                (platform_user_id,),
            )
            self._connection.execute(
                "DELETE FROM local_chart_stats WHERE platform_user_id = ?",
                (platform_user_id,),
            )
            self._connection.execute(
                "DELETE FROM local_player_profiles WHERE platform_user_id = ?",
                (platform_user_id,),
            )
        return cursor.rowcount > 0

    async def get_latest(self, platform_user_id: str) -> SyncJob | None:
        row = self._connection.execute(
            """
            SELECT * FROM sync_jobs
            WHERE platform_user_id = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (platform_user_id,),
        ).fetchone()
        if row is None:
            return None
        return SyncJob(
            id=row["id"],
            platform_user_id=row["platform_user_id"],
            status=JobStatus(row["status"]),
            credential_digest=row["credential_digest"],
            score_count=row["score_count"],
            uploaded_count=row["uploaded_count"],
            skipped_count=row["skipped_count"],
            error_code=row["error_code"],
            created_at=datetime.fromisoformat(row["created_at"]),
            finished_at=(
                datetime.fromisoformat(row["finished_at"])
                if row["finished_at"]
                else None
            ),
        )

    async def save_pairing_code(
        self, code_digest: str, private_identity: str, expires_at: datetime
    ) -> bool:
        now = datetime.now(expires_at.tzinfo)
        with self._connection:
            self._connection.execute(
                "DELETE FROM qq_pairing_codes WHERE private_identity = ? OR expires_at <= ?",
                (private_identity, now.isoformat()),
            )
            cursor = self._connection.execute(
                """
                INSERT OR IGNORE INTO qq_pairing_codes (
                    code_digest, private_identity, created_at, expires_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    code_digest,
                    private_identity,
                    now.isoformat(),
                    expires_at.isoformat(),
                ),
            )
        return cursor.rowcount == 1

    async def consume_pairing_code(
        self,
        code_digest: str,
        group_identity: str,
        consumed_at: datetime,
    ) -> str | None:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            row = self._connection.execute(
                """
                SELECT private_identity, expires_at
                FROM qq_pairing_codes
                WHERE code_digest = ?
                """,
                (code_digest,),
            ).fetchone()
            self._connection.execute(
                "DELETE FROM qq_pairing_codes WHERE code_digest = ?",
                (code_digest,),
            )
            if row is None or datetime.fromisoformat(row["expires_at"]) <= consumed_at:
                self._connection.commit()
                return None
            private_identity = str(row["private_identity"])
            self._connection.execute(
                """
                INSERT INTO qq_identity_links (
                    group_identity, private_identity, linked_at
                ) VALUES (?, ?, ?)
                ON CONFLICT(group_identity) DO UPDATE SET
                    private_identity=excluded.private_identity,
                    linked_at=excluded.linked_at
                """,
                (group_identity, private_identity, consumed_at.isoformat()),
            )
            self._connection.commit()
            return private_identity
        except Exception:
            self._connection.rollback()
            raise

    async def resolve_group_identity(self, group_identity: str) -> str | None:
        row = self._connection.execute(
            """
            SELECT private_identity
            FROM qq_identity_links
            WHERE group_identity = ?
            """,
            (group_identity,),
        ).fetchone()
        return str(row["private_identity"]) if row is not None else None

    async def delete_identity_links(self, private_identity: str) -> int:
        with self._connection:
            self._connection.execute(
                "DELETE FROM qq_pairing_codes WHERE private_identity = ?",
                (private_identity,),
            )
            cursor = self._connection.execute(
                "DELETE FROM qq_identity_links WHERE private_identity = ?",
                (private_identity,),
            )
        return cursor.rowcount

    async def create_wechat_session(self, session: WechatOAuthSession) -> None:
        with self._connection:
            self._connection.execute(
                """
                DELETE FROM wechat_oauth_sessions
                WHERE platform_user_id = ? AND status IN (?, ?, ?)
                """,
                (
                    session.platform_user_id,
                    WechatSessionStatus.PENDING.value,
                    WechatSessionStatus.CLAIMED.value,
                    WechatSessionStatus.SCORES_UPLOADED.value,
                ),
            )
            self._connection.execute(
                """
                INSERT INTO wechat_oauth_sessions (
                    id, platform_user_id, status, token_digest, created_at,
                    expires_at, claimed_at, finished_at, error_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.id,
                    session.platform_user_id,
                    session.status.value,
                    session.token_digest,
                    session.created_at.isoformat(),
                    session.expires_at.isoformat(),
                    session.claimed_at.isoformat() if session.claimed_at else None,
                    session.finished_at.isoformat() if session.finished_at else None,
                    session.error_code,
                ),
            )

    async def claim_pending_wechat_session(
        self, token_digest: str, claimed_at: datetime, expires_at: datetime
    ) -> WechatOAuthSession | None:
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            self._connection.execute(
                """
                DELETE FROM wechat_oauth_sessions
                WHERE status = ? AND expires_at <= ?
                """,
                (WechatSessionStatus.PENDING.value, claimed_at.isoformat()),
            )
            row = self._connection.execute(
                """
                SELECT * FROM wechat_oauth_sessions
                WHERE status = ? AND expires_at > ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (WechatSessionStatus.PENDING.value, claimed_at.isoformat()),
            ).fetchone()
            if row is None:
                self._connection.commit()
                return None
            self._connection.execute(
                """
                UPDATE wechat_oauth_sessions
                SET status = ?, token_digest = ?, claimed_at = ?, expires_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    WechatSessionStatus.CLAIMED.value,
                    token_digest,
                    claimed_at.isoformat(),
                    expires_at.isoformat(),
                    row["id"],
                    WechatSessionStatus.PENDING.value,
                ),
            )
            self._connection.commit()
            return WechatOAuthSession(
                id=str(row["id"]),
                platform_user_id=str(row["platform_user_id"]),
                status=WechatSessionStatus.CLAIMED,
                token_digest=token_digest,
                created_at=datetime.fromisoformat(row["created_at"]),
                expires_at=expires_at,
                claimed_at=claimed_at,
            )
        except Exception:
            self._connection.rollback()
            raise

    async def get_wechat_session_by_token(
        self, token_digest: str, accessed_at: datetime
    ) -> WechatOAuthSession | None:
        row = self._connection.execute(
            """
            SELECT * FROM wechat_oauth_sessions
            WHERE token_digest = ? AND expires_at > ?
            """,
            (token_digest, accessed_at.isoformat()),
        ).fetchone()
        return self._wechat_session_from_row(row) if row is not None else None

    async def save_wechat_session(self, session: WechatOAuthSession) -> None:
        with self._connection:
            self._connection.execute(
                """
                UPDATE wechat_oauth_sessions
                SET status = ?, token_digest = ?, expires_at = ?, claimed_at = ?,
                    finished_at = ?, error_code = ?
                WHERE id = ?
                """,
                (
                    session.status.value,
                    session.token_digest,
                    session.expires_at.isoformat(),
                    session.claimed_at.isoformat() if session.claimed_at else None,
                    session.finished_at.isoformat() if session.finished_at else None,
                    session.error_code,
                    session.id,
                ),
            )

    async def save_chart_stats(self, stats: tuple[LocalChartStat, ...]) -> None:
        if not stats:
            return
        with self._connection:
            self._connection.executemany(
                """
                INSERT INTO local_chart_stats (
                    platform_user_id, title, chart_type, level_index,
                    play_count, dx_star, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform_user_id, title, chart_type, level_index)
                DO UPDATE SET
                    play_count=excluded.play_count,
                    dx_star=excluded.dx_star,
                    updated_at=excluded.updated_at
                """,
                [
                    (
                        item.platform_user_id,
                        item.title,
                        item.chart_type,
                        item.level_index,
                        item.play_count,
                        item.dx_star,
                        item.updated_at.isoformat(),
                    )
                    for item in stats
                ],
            )

    async def get_chart_stats(
        self, platform_user_id: str
    ) -> tuple[LocalChartStat, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM local_chart_stats WHERE platform_user_id = ?
            """,
            (platform_user_id,),
        ).fetchall()
        return tuple(
            LocalChartStat(
                platform_user_id=str(row["platform_user_id"]),
                title=str(row["title"]),
                chart_type=str(row["chart_type"]),
                level_index=int(row["level_index"]),
                play_count=int(row["play_count"]),
                dx_star=(int(row["dx_star"]) if row["dx_star"] is not None else None),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
            for row in rows
        )

    async def save_player_profile(self, profile: LocalPlayerProfile) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO local_player_profiles (
                    platform_user_id, player_name, rating, title_text,
                    title_rarity, star_count, avatar_name, nameplate_name,
                    nameplate_description, frame_name, frame_description,
                    version_logo, avatar, rating_base, course_rank, class_rank,
                    nameplate, frame, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform_user_id) DO UPDATE SET
                    player_name=excluded.player_name,
                    rating=excluded.rating,
                    title_text=excluded.title_text,
                    title_rarity=excluded.title_rarity,
                    star_count=excluded.star_count,
                    avatar_name=excluded.avatar_name,
                    nameplate_name=excluded.nameplate_name,
                    nameplate_description=excluded.nameplate_description,
                    frame_name=excluded.frame_name,
                    frame_description=excluded.frame_description,
                    version_logo=excluded.version_logo,
                    avatar=excluded.avatar,
                    rating_base=excluded.rating_base,
                    course_rank=excluded.course_rank,
                    class_rank=excluded.class_rank,
                    nameplate=excluded.nameplate,
                    frame=excluded.frame,
                    updated_at=excluded.updated_at
                """,
                (
                    profile.platform_user_id,
                    profile.player_name,
                    profile.rating,
                    profile.title_text,
                    profile.title_rarity,
                    profile.star_count,
                    profile.avatar_name,
                    profile.nameplate_name,
                    profile.nameplate_description,
                    profile.frame_name,
                    profile.frame_description,
                    profile.version_logo,
                    profile.avatar,
                    profile.rating_base,
                    profile.course_rank,
                    profile.class_rank,
                    profile.nameplate,
                    profile.frame,
                    profile.updated_at.isoformat(),
                ),
            )

    async def get_player_profile(
        self, platform_user_id: str
    ) -> LocalPlayerProfile | None:
        row = self._connection.execute(
            "SELECT * FROM local_player_profiles WHERE platform_user_id = ?",
            (platform_user_id,),
        ).fetchone()
        if row is None:
            return None
        return LocalPlayerProfile(
            platform_user_id=str(row["platform_user_id"]),
            player_name=str(row["player_name"]),
            rating=int(row["rating"]),
            title_text=str(row["title_text"]),
            title_rarity=str(row["title_rarity"]),
            star_count=int(row["star_count"]),
            avatar_name=str(row["avatar_name"]),
            nameplate_name=str(row["nameplate_name"]),
            nameplate_description=str(row["nameplate_description"]),
            frame_name=str(row["frame_name"]),
            frame_description=str(row["frame_description"]),
            version_logo=bytes(row["version_logo"]),
            avatar=bytes(row["avatar"]),
            rating_base=bytes(row["rating_base"]),
            course_rank=bytes(row["course_rank"]),
            class_rank=bytes(row["class_rank"]),
            nameplate=bytes(row["nameplate"]),
            frame=bytes(row["frame"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _wechat_session_from_row(row: sqlite3.Row) -> WechatOAuthSession:
        return WechatOAuthSession(
            id=str(row["id"]),
            platform_user_id=str(row["platform_user_id"]),
            status=WechatSessionStatus(str(row["status"])),
            token_digest=(str(row["token_digest"]) if row["token_digest"] else None),
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            claimed_at=(
                datetime.fromisoformat(row["claimed_at"])
                if row["claimed_at"]
                else None
            ),
            finished_at=(
                datetime.fromisoformat(row["finished_at"])
                if row["finished_at"]
                else None
            ),
            error_code=(str(row["error_code"]) if row["error_code"] else None),
        )

    def close(self) -> None:
        self._connection.close()
