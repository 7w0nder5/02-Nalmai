from __future__ import annotations

from nalmai.models import SyncJob, UserBinding


class MemoryRepository:
    def __init__(self) -> None:
        self.bindings: dict[str, UserBinding] = {}
        self.jobs: dict[str, SyncJob] = {}

    async def get(self, platform_user_id: str) -> UserBinding | None:
        return self.bindings.get(platform_user_id)

    async def save(self, item: UserBinding | SyncJob) -> None:
        if isinstance(item, UserBinding):
            self.bindings[item.platform_user_id] = item
        elif isinstance(item, SyncJob):
            self.jobs[item.id] = item
        else:
            raise TypeError("MemoryRepository 只接受 UserBinding 或 SyncJob。")

    async def delete(self, platform_user_id: str) -> bool:
        return self.bindings.pop(platform_user_id, None) is not None

    async def get_latest(self, platform_user_id: str) -> SyncJob | None:
        matches = [
            item for item in self.jobs.values() if item.platform_user_id == platform_user_id
        ]
        return max(matches, key=lambda item: item.created_at) if matches else None

