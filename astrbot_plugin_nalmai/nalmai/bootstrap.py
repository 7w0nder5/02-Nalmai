from __future__ import annotations

from dataclasses import dataclass

from nalmai.adapters.arcade_unavailable import UnavailableArcadeScoreProvider
from nalmai.adapters.b50_rich import RichB50Renderer
from nalmai.adapters.cipher import FernetCredentialCipher
from nalmai.adapters.divingfish import HttpDivingFishClient
from nalmai.adapters.sqlite_repository import SqliteRepository
from nalmai.commands import CommandParser
from nalmai.config import Settings
from nalmai.services.application import NalmaiApplication
from nalmai.services.b50 import B50Service
from nalmai.services.binding import BindingService
from nalmai.services.sync import SyncService
from nalmai.services.wechat import WechatOAuthService
from nalmai.submission import SubmissionSessionStore
from nalmai.ports import ArcadeScoreProvider


@dataclass(slots=True)
class Container:
    application: NalmaiApplication
    submissions: SubmissionSessionStore
    repository: SqliteRepository
    divingfish: HttpDivingFishClient
    wechat: WechatOAuthService


def build_container(settings: Settings) -> Container:
    repository = SqliteRepository(settings.database_path)
    cipher = FernetCredentialCipher(settings.fernet_key)
    divingfish = HttpDivingFishClient(settings.http_timeout_seconds)
    binding = BindingService(repository, cipher, divingfish)
    sync = SyncService(
        repository,
        repository,
        cipher,
        divingfish,
        _arcade_provider(settings),
        settings.hmac_key,
    )
    wechat = WechatOAuthService(
        repository,
        repository,
        sync,
        divingfish,
        settings.hmac_key,
    )
    b50 = B50Service(
        repository,
        divingfish,
        RichB50Renderer(divingfish),
        chart_stats=repository,
    )
    application = NalmaiApplication(
        CommandParser(),
        binding,
        sync,
        b50,
        wechat,
        allow_group_secrets=settings.allow_group_secrets,
    )
    return Container(
        application=application,
        submissions=SubmissionSessionStore(),
        repository=repository,
        divingfish=divingfish,
        wechat=wechat,
    )


def _arcade_provider(settings: Settings) -> ArcadeScoreProvider:
    if settings.arcade_provider == "unavailable":
        return UnavailableArcadeScoreProvider()
    if settings.arcade_provider == "maimai_py":
        from nalmai.adapters.arcade_maimai_py import MaimaiPyArcadeScoreProvider

        return MaimaiPyArcadeScoreProvider(settings.arcade_http_proxy)
    raise RuntimeError(
        "NALMAI_ARCADE_PROVIDER 只允许 unavailable 或 maimai_py。"
    )
