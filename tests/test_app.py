import io
import unittest
from types import SimpleNamespace

import app


class StrictJsonRequestTests(unittest.TestCase):
    def parse(self, payload):
        req = SimpleNamespace(headers={"Content-Length": str(len(payload))}, rfile=io.BytesIO(payload))
        return app.body(req)

    def test_invalid_utf8_is_client_error(self):
        with self.assertRaisesRegex(ValueError, "valid JSON"):
            self.parse(b'{"text":"\\xff"}')

    def test_nonfinite_json_numbers_are_rejected(self):
        for token in (b"NaN", b"Infinity", b"-Infinity"):
            with self.subTest(token=token), self.assertRaisesRegex(ValueError, "non-finite"):
                self.parse(b'{"value":' + token + b"}")

    def test_valid_json_still_parses(self):
        self.assertEqual(self.parse(b'{"value":3,"active":true}'), {"value": 3, "active": True})


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
