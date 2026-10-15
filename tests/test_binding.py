from __future__ import annotations

import pytest

from nalmai.errors import NalmaiError
from nalmai.services.binding import BindingService
from tests.fakes import FakeCipher, FakeDivingFish, FakeRepository


@pytest.mark.asyncio
async def test_bind_validates_before_persisting_and_never_stores_plaintext() -> None:
    repository = FakeRepository()
    client = FakeDivingFish()
    service = BindingService(repository, FakeCipher(), client)

    result = await service.bind("platform-1", "123456", "top-secret-token")

    binding = repository.bindings["platform-1"]
    assert binding.divingfish_username == "water_user"
    assert b"top-secret-token" not in binding.credential_ciphertext
    assert "top-secret-token" not in result.masked_token


@pytest.mark.asyncio
async def test_failed_validation_leaves_no_binding() -> None:
    repository = FakeRepository()
    client = FakeDivingFish()
    client.error = NalmaiError("DIVINGFISH_BAD_REQUEST", "凭据无效。")
    service = BindingService(repository, FakeCipher(), client)

    with pytest.raises(NalmaiError):
        await service.bind("platform-1", "123456", "wrong-token")
    assert repository.bindings == {}


@pytest.mark.asyncio
async def test_unbind_deletes_ciphertext() -> None:
    repository = FakeRepository()
    service = BindingService(repository, FakeCipher(), FakeDivingFish())
    await service.bind("platform-1", "123456", "token")
    assert await service.unbind("platform-1") is True
    assert repository.bindings == {}

