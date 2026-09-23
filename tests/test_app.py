import io
import unittest

import app


class PasswordHashingTests(unittest.TestCase):
    def test_hash_is_deterministic_for_same_salt(self):
        digest1, salt = app.hash_password("open-tune", "fixed-salt")
        digest2, _ = app.hash_password("open-tune", salt)
        self.assertEqual(digest1, digest2)

    def test_wrong_password_does_not_match(self):
        digest, salt = app.hash_password("correct", "fixed-salt")
        self.assertFalse(app.check_password("wrong", digest, salt))


class RequestBodyFramingTests(unittest.TestCase):
    class Handler:
        def __init__(self, headers, payload=b""):
            self.headers = headers
            self.rfile = io.BytesIO(payload)

    def test_negative_content_length_is_rejected(self):
        handler = self.Handler({"Content-Length": "-1"}, b'{"x": 1}')

        with self.assertRaisesRegex(ValueError, "cannot be negative"):
            app.body(handler)

    def test_transfer_encoding_is_rejected(self):
        handler = self.Handler(
            {"Transfer-Encoding": "chunked"},
            b'7\r\n{"x":1}\r\n0\r\n\r\n',
        )

        with self.assertRaisesRegex(ValueError, "Transfer-Encoding"):
            app.body(handler)

    def test_valid_content_length_still_parses_json(self):
        payload = b'{"x": 1}'
        handler = self.Handler(
            {"Content-Length": str(len(payload))},
            payload,
        )

        self.assertEqual(app.body(handler), {"x": 1})


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
