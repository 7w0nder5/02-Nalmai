from __future__ import annotations

from datetime import UTC, datetime

from nalmai.errors import NalmaiError
from nalmai.models import BindResult, BindingStatus, UserBinding
from nalmai.ports import BindingRepository, CredentialCipher, DivingFishClient
from nalmai.redaction import mask_qq, mask_secret


class BindingService:
    def __init__(
        self,
        repository: BindingRepository,
        cipher: CredentialCipher,
        divingfish: DivingFishClient,
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._divingfish = divingfish

    async def bind(
        self, platform_user_id: str, claimed_qq: str, import_token: str
    ) -> BindResult:
        payload = await self._divingfish.get_records(import_token)
        username = payload.get("username")
        nickname = payload.get("nickname")
        if not isinstance(username, str) or not username:
            raise NalmaiError(
                "DIVINGFISH_SCHEMA_ERROR",
                "水鱼绑定验证响应缺少有效 username。",
            )
        if not isinstance(nickname, str):
            raise NalmaiError(
                "DIVINGFISH_SCHEMA_ERROR",
                "水鱼绑定验证响应缺少 nickname。",
            )

        now = datetime.now(UTC)
        binding = UserBinding(
            platform_user_id=platform_user_id,
            claimed_qq=claimed_qq,
            divingfish_username=username,
            credential_ciphertext=self._cipher.encrypt(import_token),
            credential_key_version=self._cipher.key_version,
            credential_mask=mask_secret(import_token),
            status=BindingStatus.BOUND,
            bound_at=now,
            credential_rotated_at=now,
        )
        await self._repository.save(binding)
        return BindResult(
            username=username,
            nickname=nickname,
            masked_qq=mask_qq(claimed_qq),
            masked_token=binding.credential_mask,
        )

    async def unbind(self, platform_user_id: str) -> bool:
        return await self._repository.delete(platform_user_id)

    async def status(self, platform_user_id: str) -> str:
        binding = await self._repository.get(platform_user_id)
        if binding is None:
            return "未绑定水鱼账号。"
        return (
            f"绑定状态：{binding.status.value}；"
            f"QQ：{mask_qq(binding.claimed_qq)}；"
            f"水鱼用户名：{binding.divingfish_username}；"
            f"凭据：{binding.credential_mask}。"
        )

