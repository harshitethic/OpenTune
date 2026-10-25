import unittest

import app


class PublicUserTests(unittest.TestCase):
    def test_only_public_fields_are_returned(self):
        record = {"id": 12, "username": "listener", "created_at": "2026-01-01",
                  "password_hash": "sensitive", "recovery_hash": "secret",
                  "recovery_salt": "also-secret"}
        self.assertEqual(app.public_user(record), {
            "id": 12, "username": "listener", "created_at": "2026-01-01"
        })

    def test_absent_session_returns_none(self):
        self.assertIsNone(app.public_user(None))


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
