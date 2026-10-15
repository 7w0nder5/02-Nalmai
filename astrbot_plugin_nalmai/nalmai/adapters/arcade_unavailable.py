from __future__ import annotations

from nalmai.errors import UpstreamNotConfigured
from nalmai.models import ScoreBatch, UserBinding


class UnavailableArcadeScoreProvider:
    async def fetch_scores(
        self, sgwc_credential: str, binding: UserBinding
    ) -> ScoreBatch:
        del sgwc_credential, binding
        raise UpstreamNotConfigured()

