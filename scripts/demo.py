from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from nalmai.adapters.b50_basic import BasicB50Renderer
from nalmai.adapters.cipher import FernetCredentialCipher
from nalmai.adapters.memory_repository import MemoryRepository
from nalmai.commands import CommandParser
from nalmai.models import InboundMessage, NormalizedScore, ScoreBatch, UploadReceipt, UserBinding
from nalmai.services.application import NalmaiApplication
from nalmai.services.b50 import B50Service
from nalmai.services.binding import BindingService
from nalmai.services.sync import SyncService


class DemoDivingFish:
    async def get_records(self, import_token: str) -> dict[str, Any]:
        assert import_token == "demo-import-token"
        return {
            "username": "demo_water_user",
            "nickname": "Demo Player",
            "rating": 15000,
            "records": [],
        }

    async def upload_records(
        self, import_token: str, records: list[dict[str, Any]]
    ) -> UploadReceipt:
        assert import_token == "demo-import-token"
        return UploadReceipt("更新成功", updates=len(records), creates=0)

    async def query_b50(self, username: str) -> dict[str, Any]:
        assert username == "demo_water_user"
        return {
            "nickname": "Demo Player",
            "rating": 15000,
            "additional_rating": 0,
            "charts": {
                "sd": [
                    {
                        "title": "Demo Song",
                        "achievements": 100.5,
                        "ra": 300,
                        "type": "SD",
                    }
                ],
                "dx": [],
            },
        }


class DemoArcade:
    async def fetch_scores(
        self, sgwc_credential: str, binding: UserBinding
    ) -> ScoreBatch:
        assert sgwc_credential == "SGWCMAID-demo"
        assert binding.divingfish_username == "demo_water_user"
        return ScoreBatch(
            scores=(
                NormalizedScore(
                    achievements=100.5,
                    dx_score=1234,
                    fc="fc",
                    fs="",
                    level_index=3,
                    title="Demo Song",
                    chart_type="SD",
                ),
            ),
            player_display_name="Demo Player",
            account_match_verified=True,
        )


async def run() -> None:
    repository = MemoryRepository()
    cipher = FernetCredentialCipher(Fernet.generate_key().decode("ascii"))
    divingfish = DemoDivingFish()
    app = NalmaiApplication(
        CommandParser(),
        BindingService(repository, cipher, divingfish),
        SyncService(
            repository,
            repository,
            cipher,
            divingfish,
            DemoArcade(),
            "demo-hmac-key",
        ),
        B50Service(repository, divingfish, BasicB50Renderer()),
    )

    bind = await app.handle(
        InboundMessage(
            "demo-platform-user",
            "private",
            "/bind 123456 demo-import-token",
            is_private=True,
        )
    )
    print(bind.text)

    sync = await app.handle(
        InboundMessage(
            "demo-platform-user",
            "private",
            "SGWCMAID-demo",
            is_private=True,
        )
    )
    print(sync.text)

    b50 = await app.handle(
        InboundMessage("demo-platform-user", "group", "/b50", is_private=False)
    )
    if b50.image is None:
        raise RuntimeError(b50.text)
    output = Path("data/demo-b50.png")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b50.image.content)
    print(f"B50 image: {output.resolve()}")


if __name__ == "__main__":
    asyncio.run(run())

