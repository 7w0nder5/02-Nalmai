from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from nalmai.adapters.qq_capture import SecureQQEventCapture


class SecureQQEventCaptureTests(unittest.TestCase):
    def test_sanitized_capture_preserves_structure_and_scalar_types(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            capture = SecureQQEventCapture(root, "test-hmac-key")
            payload = {
                "author": {
                    "user_openid": "USER-A",
                    "member_openid": "MEMBER-A",
                    "union_openid": None,
                },
                "same_user_again": "USER-A",
                "items": ["value", "", 42, 3.5, True, None],
            }

            result = capture.store("C2C_MESSAGE_CREATE", payload)

            self.assertIsNotNone(result)
            assert result is not None
            self.assertIsNone(result.raw_path)
            cleaned = json.loads(result.sanitized_path.read_text(encoding="utf-8"))
            self.assertEqual(list(cleaned), list(payload))
            self.assertEqual(list(cleaned["author"]), list(payload["author"]))
            self.assertIsNone(cleaned["author"]["union_openid"])
            self.assertEqual(
                cleaned["author"]["user_openid"], cleaned["same_user_again"]
            )
            self.assertNotEqual(
                cleaned["author"]["user_openid"],
                cleaned["author"]["member_openid"],
            )
            self.assertEqual(cleaned["items"][1], "")
            self.assertIsInstance(cleaned["items"][2], int)
            self.assertIsInstance(cleaned["items"][3], float)
            self.assertIsInstance(cleaned["items"][4], bool)
            self.assertIsNone(cleaned["items"][5])

    def test_raw_capture_requires_explicit_enable_and_safe_message(self) -> None:
        with TemporaryDirectory() as directory:
            capture = SecureQQEventCapture(
                Path(directory),
                "test-hmac-key",
                raw_enabled=True,
            )
            payload = {"content": "/status", "id": "MESSAGE-A"}

            blocked = capture.store(
                "C2C_MESSAGE_CREATE", payload, allow_raw=False
            )
            allowed = capture.store(
                "C2C_MESSAGE_CREATE", payload, allow_raw=True
            )

            self.assertIsNotNone(blocked)
            self.assertIsNotNone(allowed)
            assert blocked is not None and allowed is not None
            self.assertIsNone(blocked.raw_path)
            self.assertIsNotNone(allowed.raw_path)
            assert allowed.raw_path is not None
            self.assertEqual(
                json.loads(allowed.raw_path.read_text(encoding="utf-8")), payload
            )

    def test_raw_capture_refuses_credentials_even_when_caller_allows_it(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            capture = SecureQQEventCapture(
                Path(directory),
                "test-hmac-key",
                raw_enabled=True,
            )

            for content in (
                "SGWCMAID-secret",
                "/bind 123456 import-token-value",
                "Import-Token: import-token-value",
            ):
                result = capture.store(
                    "C2C_MESSAGE_CREATE",
                    {"content": content},
                    allow_raw=True,
                )
                self.assertIsNotNone(result)
                assert result is not None
                self.assertIsNone(result.raw_path)
                self.assertNotIn(
                    content,
                    result.sanitized_path.read_text(encoding="utf-8"),
                )

    def test_capture_can_be_disabled(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            capture = SecureQQEventCapture(
                root,
                "test-hmac-key",
                enabled=False,
            )

            self.assertIsNone(
                capture.store("C2C_MESSAGE_CREATE", {"content": "/status"})
            )
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
