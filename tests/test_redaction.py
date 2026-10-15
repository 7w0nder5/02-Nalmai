from nalmai.redaction import redact_sensitive


def test_redacts_all_supported_secret_shapes() -> None:
    raw = (
        "Import-Token: abcdef Authorization=BearerSecret "
        "client_secret=hidden SGWCMAID123456"
    )
    cleaned = redact_sensitive(raw)
    for secret in ("abcdef", "BearerSecret", "hidden", "123456"):
        assert secret not in cleaned
    assert "[REDACTED]" in cleaned

