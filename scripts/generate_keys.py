from __future__ import annotations

import secrets

from cryptography.fernet import Fernet


def main() -> None:
    print(f"NALMAI_FERNET_KEY={Fernet.generate_key().decode('ascii')}")
    print(f"NALMAI_HMAC_KEY={secrets.token_hex(32)}")
    print(f"NALMAI_INTERNAL_API_TOKEN={secrets.token_urlsafe(48)}")


if __name__ == "__main__":
    main()

