from __future__ import annotations

import pytest

from nalmai.errors import NalmaiError
from nalmai.submission import SubmissionSessionStore


def test_submission_nonce_is_single_use() -> None:
    store = SubmissionSessionStore(ttl_seconds=300)
    nonce = store.create("platform-1")
    assert store.consume(nonce) == "platform-1"
    with pytest.raises(NalmaiError):
        store.consume(nonce)

