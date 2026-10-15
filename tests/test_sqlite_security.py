from __future__ import annotations

from datetime import UTC, datetime

from cryptography.fernet import Fernet

from nalmai.adapters.cipher import FernetCredentialCipher
from nalmai.adapters.sqlite_repository import SqliteRepository
from nalmai.models import LocalPlayerProfile
from nalmai.services.binding import BindingService
from nalmai.services.sync import SyncService
from nalmai.services.wechat import WechatOAuthService
from tests.fakes import FakeArcade, FakeDivingFish


async def test_sqlite_never_contains_import_token_plaintext(tmp_path) -> None:
    database = tmp_path / "nalmai.sqlite3"
    repository = SqliteRepository(database)
    cipher = FernetCredentialCipher(Fernet.generate_key().decode("ascii"))
    token = "secret-import-token-value"

    await BindingService(repository, cipher, FakeDivingFish()).bind(
        "platform-1", "123456", token
    )
    repository.close()

    assert token.encode("utf-8") not in database.read_bytes()


async def test_sqlite_stores_only_wechat_upload_token_digest(tmp_path) -> None:
    database = tmp_path / "nalmai.sqlite3"
    repository = SqliteRepository(database)
    cipher = FernetCredentialCipher(Fernet.generate_key().decode("ascii"))
    client = FakeDivingFish()
    await BindingService(repository, cipher, client).bind(
        "platform-1", "123456", "import-token"
    )
    sync = SyncService(
        repository,
        repository,
        cipher,
        client,
        FakeArcade(),
        "hmac-key",
    )
    service = WechatOAuthService(
        repository,
        repository,
        sync,
        client,
        "hmac-key",
    )
    await service.issue("platform-1")
    _, raw_token = await service.claim()
    repository.close()

    assert raw_token.encode("utf-8") not in database.read_bytes()


async def test_sqlite_round_trips_local_player_profile(tmp_path) -> None:
    repository = SqliteRepository(tmp_path / "nalmai.sqlite3")
    profile = LocalPlayerProfile(
        platform_user_id="platform-1",
        player_name="７ｗ０ｎｄｅｒｓ",
        rating=15896,
        title_text="あ",
        title_rarity="Gold",
        star_count=635,
        avatar_name="ソルト（ふぇすてぃばる）",
        nameplate_name="桃将",
        nameplate_description="maimai PiNK 全曲/BASIC～MASTER/RANK SSS",
        frame_name="樋口楓ちほー",
        frame_description="樋口楓ちほーで獲得",
        version_logo=b"logo",
        avatar=b"avatar",
        rating_base=b"rating",
        course_rank=b"course",
        class_rank=b"class",
        nameplate=b"nameplate",
        frame=b"frame",
        updated_at=datetime.now(UTC),
    )

    await repository.save_player_profile(profile)
    restored = await repository.get_player_profile("platform-1")
    repository.close()

    assert restored == profile
