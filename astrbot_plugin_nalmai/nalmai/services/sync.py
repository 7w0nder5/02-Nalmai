from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
import uuid
from datetime import UTC, datetime
from typing import Awaitable, Callable

from nalmai.errors import BindingRequired, NalmaiError
from nalmai.models import (
    JobStatus,
    NormalizedScore,
    ScoreBatch,
    SyncJob,
    SyncResult,
    UserBinding,
)
from nalmai.ports import (
    ArcadeScoreProvider,
    BindingRepository,
    CredentialCipher,
    DivingFishClient,
    JobRepository,
)


class SyncService:
    allowed_fc = {"", "fc", "fcp", "ap", "app"}
    allowed_fs = {"", "sync", "fs", "fsp", "fsd", "fsdp"}

    def __init__(
        self,
        bindings: BindingRepository,
        jobs: JobRepository,
        cipher: CredentialCipher,
        divingfish: DivingFishClient,
        arcade: ArcadeScoreProvider,
        hmac_key: str,
        idempotency_seconds: int = 300,
    ) -> None:
        self._bindings = bindings
        self._jobs = jobs
        self._cipher = cipher
        self._divingfish = divingfish
        self._arcade = arcade
        self._hmac_key = hmac_key.encode("utf-8")
        self._idempotency_seconds = idempotency_seconds
        self._locks: dict[str, asyncio.Lock] = {}
        self._recent_digests: dict[str, float] = {}

    async def synchronize(
        self, platform_user_id: str, sgwc_credential: str
    ) -> SyncResult:
        if not sgwc_credential.startswith("SGWCMAID"):
            raise NalmaiError("INVALID_SGWC_FORMAT", "不是完整的 SGWCMAID 凭据。")

        async def fetch(binding: UserBinding) -> ScoreBatch:
            return await self._arcade.fetch_scores(sgwc_credential, binding)

        try:
            return await self._synchronize_with_batch(
                platform_user_id,
                self._digest(sgwc_credential),
                fetch,
            )
        finally:
            sgwc_credential = ""

    async def synchronize_authorized_scores(
        self,
        platform_user_id: str,
        scores: tuple[NormalizedScore, ...],
        authorization_id: str,
        *,
        player_display_name: str = "Windows 微信授权玩家",
    ) -> SyncResult:
        if not authorization_id:
            raise ValueError("authorization_id must not be empty")

        async def fetch(_: UserBinding) -> ScoreBatch:
            return ScoreBatch(
                scores=scores,
                player_display_name=player_display_name,
                upload_authorized=True,
            )

        return await self._synchronize_with_batch(
            platform_user_id,
            self._digest(f"wechat-oauth\0{authorization_id}"),
            fetch,
        )

    async def _synchronize_with_batch(
        self,
        platform_user_id: str,
        digest: str,
        fetch_batch: Callable[[UserBinding], Awaitable[ScoreBatch]],
    ) -> SyncResult:

        lock = self._locks.setdefault(platform_user_id, asyncio.Lock())
        async with lock:
            binding = await self._bindings.get(platform_user_id)
            if binding is None:
                raise BindingRequired()

            self._reject_recent_replay(digest)
            job = SyncJob(
                id=str(uuid.uuid4()),
                platform_user_id=platform_user_id,
                status=JobStatus.CREATED,
                credential_digest=digest,
            )
            await self._jobs.save(job)

            try:
                job.status = JobStatus.CREDENTIAL_ACCEPTED
                await self._jobs.save(job)

                job.status = JobStatus.FETCHING_SCORES
                await self._jobs.save(job)
                batch = await fetch_batch(binding)
                if not batch.upload_authorized:
                    raise NalmaiError(
                        "UPLOAD_NOT_AUTHORIZED",
                        "当前会话没有获得把该二维码成绩写入已绑定水鱼账号的授权。",
                    )

                job.status = JobStatus.NORMALIZING
                job.score_count = len(batch.scores)
                await self._jobs.save(job)
                records, skipped = self._normalize(batch.scores)
                if not records:
                    raise NalmaiError("NO_VALID_SCORES", "没有可上传的有效成绩。")

                import_token = self._cipher.decrypt(binding.credential_ciphertext)
                if any(
                    record.get("fc") is None or record.get("fs") is None
                    for record in records
                ):
                    existing = await self._divingfish.get_records(import_token)
                    records = self._preserve_unknown_special_fields(records, existing)
                job.status = JobStatus.UPLOADING
                job.skipped_count = skipped
                await self._jobs.save(job)
                receipt = await self._divingfish.upload_records(import_token, records)
                job.uploaded_count = receipt.affected

                if receipt.affected != len(records):
                    job.status = JobStatus.UPLOADED_UNVERIFIED
                    job.error_code = "UPLOAD_COUNT_MISMATCH"
                    job.finished_at = datetime.now(UTC)
                    await self._jobs.save(job)
                    raise NalmaiError(
                        "UPLOAD_COUNT_MISMATCH",
                        "水鱼已处理部分成绩，但数量与提交数量不一致。",
                    )

                verified_payload = await self._divingfish.get_records(import_token)
                if not self._uploaded_scores_are_visible(records, verified_payload):
                    job.status = JobStatus.UPLOADED_UNVERIFIED
                    job.error_code = "SCORE_VERIFY_FAILED"
                    job.finished_at = datetime.now(UTC)
                    await self._jobs.save(job)
                    raise NalmaiError(
                        "SCORE_VERIFY_FAILED",
                        "水鱼已接收上传，但重新读取时尚未确认新成绩，请稍后查询状态。",
                    )

                job.status = JobStatus.VERIFYING_B50
                await self._jobs.save(job)
                try:
                    await self._divingfish.query_b50(binding.divingfish_username)
                except NalmaiError as exc:
                    job.status = JobStatus.UPLOADED_UNVERIFIED
                    job.error_code = exc.code
                    job.finished_at = datetime.now(UTC)
                    await self._jobs.save(job)
                    raise NalmaiError(
                        "B50_VERIFY_FAILED",
                        "成绩已上传，但 B50 验证失败。",
                    ) from exc

                job.status = JobStatus.SUCCEEDED
                job.finished_at = datetime.now(UTC)
                await self._jobs.save(job)
                self._recent_digests[digest] = time.monotonic()
                return SyncResult(
                    job_id=job.id,
                    uploaded_count=job.uploaded_count,
                    skipped_count=job.skipped_count,
                    player_display_name=batch.player_display_name,
                    unavailable_fields=batch.unavailable_fields,
                )
            except NalmaiError as exc:
                if job.status is not JobStatus.UPLOADED_UNVERIFIED:
                    job.status = JobStatus.FAILED
                    job.error_code = exc.code
                    job.finished_at = datetime.now(UTC)
                    await self._jobs.save(job)
                raise

    def _digest(self, credential: str) -> str:
        return hmac.new(
            self._hmac_key, credential.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    def _reject_recent_replay(self, digest: str) -> None:
        now = time.monotonic()
        self._recent_digests = {
            key: timestamp
            for key, timestamp in self._recent_digests.items()
            if now - timestamp < self._idempotency_seconds
        }
        if digest in self._recent_digests:
            raise NalmaiError("DUPLICATE_CREDENTIAL", "该二维码凭据刚刚已成功处理。")

    def _normalize(
        self, scores: tuple[NormalizedScore, ...]
    ) -> tuple[list[dict[str, object]], int]:
        records: list[dict[str, object]] = []
        skipped = 0
        for score in scores:
            if not self._is_valid(score):
                skipped += 1
                continue
            records.append(score.to_divingfish_record())
        return records, skipped

    def _is_valid(self, score: NormalizedScore) -> bool:
        return (
            bool(score.title)
            and score.chart_type in {"SD", "DX"}
            and isinstance(score.level_index, int)
            and score.level_index >= 0
            and isinstance(score.dx_score, int)
            and score.dx_score >= 0
            and isinstance(score.achievements, (int, float))
            and (score.fc is None or score.fc in self.allowed_fc)
            and (score.fs is None or score.fs in self.allowed_fs)
        )

    def _preserve_unknown_special_fields(
        self,
        records: list[dict[str, object]],
        existing_payload: dict[str, object],
    ) -> list[dict[str, object]]:
        raw_existing = existing_payload.get("records")
        if not isinstance(raw_existing, list):
            raise NalmaiError(
                "DIVINGFISH_SCHEMA_ERROR",
                "水鱼完整成绩响应缺少 records 数组。",
            )
        existing: dict[tuple[str, str, int], dict[str, object]] = {}
        for item in raw_existing:
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            chart_type = item.get("type")
            level_index = item.get("level_index")
            if (
                isinstance(title, str)
                and isinstance(chart_type, str)
                and isinstance(level_index, int)
            ):
                existing[(title, chart_type, level_index)] = item

        merged: list[dict[str, object]] = []
        for record in records:
            item = dict(record)
            key = (item["title"], item["type"], item["level_index"])
            previous = existing.get(key) if isinstance(key[0], str) and isinstance(key[1], str) and isinstance(key[2], int) else None
            if item.get("fc") is None:
                previous_fc = previous.get("fc") if previous else ""
                item["fc"] = previous_fc if previous_fc in self.allowed_fc else ""
            if item.get("fs") is None:
                previous_fs = previous.get("fs") if previous else ""
                item["fs"] = previous_fs if previous_fs in self.allowed_fs else ""
            merged.append(item)
        return merged

    @staticmethod
    def _uploaded_scores_are_visible(
        uploaded: list[dict[str, object]],
        payload: dict[str, object],
    ) -> bool:
        raw_records = payload.get("records")
        if not isinstance(raw_records, list):
            return False
        visible: dict[tuple[str, str, int], dict[str, object]] = {}
        for item in raw_records:
            if not isinstance(item, dict):
                continue
            title = item.get("title")
            chart_type = item.get("type")
            level_index = item.get("level_index")
            if (
                isinstance(title, str)
                and isinstance(chart_type, str)
                and isinstance(level_index, int)
            ):
                visible[(title, chart_type, level_index)] = item

        for item in uploaded:
            title = item.get("title")
            chart_type = item.get("type")
            level_index = item.get("level_index")
            achievements = item.get("achievements")
            dx_score = item.get("dxScore")
            if (
                not isinstance(title, str)
                or not isinstance(chart_type, str)
                or not isinstance(level_index, int)
                or not isinstance(achievements, (int, float))
                or not isinstance(dx_score, int)
            ):
                return False
            record = visible.get((title, chart_type, level_index))
            if record is None:
                return False
            visible_achievements = record.get("achievements")
            visible_dx_score = record.get("dxScore")
            if (
                not isinstance(visible_achievements, (int, float))
                or not isinstance(visible_dx_score, int)
                or visible_achievements + 0.00005 < achievements
                or visible_dx_score < dx_score
            ):
                return False
        return True
