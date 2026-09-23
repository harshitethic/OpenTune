import sqlite3
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


class PublicUserTests(unittest.TestCase):
    def test_public_user_exposes_only_profile_fields(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT
              7 AS id,
              'harshit' AS username,
              'password:secret-salt' AS password_hash,
              'recovery-digest' AS recovery_hash,
              'recovery-salt' AS recovery_salt,
              '2026-09-23 10:00:00' AS created_at
            """
        ).fetchone()

        profile = app.public_user(row)

        self.assertEqual(
            profile,
            {
                "id": 7,
                "username": "harshit",
                "created_at": "2026-09-23 10:00:00",
            },
        )
        self.assertNotIn("password_hash", profile)
        self.assertNotIn("recovery_hash", profile)
        self.assertNotIn("recovery_salt", profile)
        connection.close()

    def test_public_user_handles_anonymous_request(self):
        self.assertIsNone(app.public_user(None))


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
