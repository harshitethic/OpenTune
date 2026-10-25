import sqlite3
import unittest
from unittest.mock import patch

import app


class ReadinessTests(unittest.TestCase):
    def test_sqlite_connection_failure_is_unhealthy(self):
        with patch("app.db", side_effect=sqlite3.OperationalError("database locked")):
            self.assertFalse(app.database_ready())

    def test_healthy_sqlite_connection_is_ready(self):
        connection = sqlite3.connect(":memory:")
        with patch("app.db", return_value=connection):
            self.assertTrue(app.database_ready())


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
