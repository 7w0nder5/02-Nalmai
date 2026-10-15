from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from nalmai.errors import NalmaiError


class FernetCredentialCipher:
    key_version = "fernet-v1"

    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise RuntimeError("NALMAI_FERNET_KEY 不是有效 Fernet key。") from exc

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            return self._fernet.decrypt(ciphertext).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise NalmaiError(
                "CREDENTIAL_DECRYPT_FAILED",
                "本地凭据无法解密，请重新执行 /bind。",
            ) from exc

