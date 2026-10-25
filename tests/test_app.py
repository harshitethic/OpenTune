import io
import unittest
from types import SimpleNamespace

import app


class RequestBodyLengthTests(unittest.TestCase):
    def test_negative_length_is_rejected_without_unbounded_read(self):
        stream = io.BytesIO(b'{"secret":"ignored"}')
        request = SimpleNamespace(headers={"Content-Length": "-1"}, rfile=stream)
        with self.assertRaisesRegex(ValueError, "Invalid Content-Length"):
            app.body(request)
        self.assertEqual(stream.tell(), 0)

    def test_valid_length_reads_only_declared_bytes(self):
        payload = b'{"ok":true}'
        stream = io.BytesIO(payload + b"trailing")
        request = SimpleNamespace(headers={"Content-Length": str(len(payload))}, rfile=stream)
        self.assertEqual(app.body(request), {"ok": True})
        self.assertEqual(stream.tell(), len(payload))

    def test_oversized_body_is_rejected_before_read(self):
        stream = io.BytesIO(b"{}")
        request = SimpleNamespace(headers={"Content-Length": str(app.MAX_BODY_BYTES + 1)}, rfile=stream)
        with self.assertRaisesRegex(ValueError, "too large"):
            app.body(request)
        self.assertEqual(stream.tell(), 0)


class PasswordHashingTests(unittest.TestCase):
    def test_hash_is_deterministic_for_same_salt(self):
        digest1, salt = app.hash_password("open-tune", "fixed-salt")
        digest2, _ = app.hash_password("open-tune", salt)
        self.assertEqual(digest1, digest2)

    def test_wrong_password_does_not_match(self):
        digest, salt = app.hash_password("correct", "fixed-salt")
        self.assertFalse(app.check_password("wrong", digest, salt))


class PayloadValidationTests(unittest.TestCase):
    def test_validate_username(self):
        self.assertTrue(app.validate_username("harshit"))
        self.assertTrue(app.validate_username("music_01"))
        self.assertFalse(app.validate_username("x"))
        self.assertFalse(app.validate_username("bad name"))

    def test_validate_password(self):
        self.assertTrue(app.validate_password("1234"))
        self.assertFalse(app.validate_password("123"))


if __name__ == "__main__":
    unittest.main()
