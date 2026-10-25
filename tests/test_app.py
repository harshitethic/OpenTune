import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class SessionExpirationTests(unittest.TestCase):
    def test_expired_session_cannot_authenticate(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, "DB", Path(directory) / "sessions.db"):
            app.init_db()
            connection = sqlite3.connect(app.DB)
            try:
                connection.execute("INSERT INTO users(username,password_hash,recovery_hash,recovery_salt) VALUES(?,?,?,?)",
                                   ("listener", "hash:salt", "hash", "salt"))
                user_id = connection.execute("SELECT id FROM users").fetchone()[0]
                connection.execute("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,datetime('now','-31 days'))", ("stale", user_id))
                connection.execute("INSERT INTO sessions(token,user_id,created_at) VALUES(?,?,datetime('now','-1 day'))", ("fresh", user_id))
                connection.commit()
            finally:
                connection.close()
            self.assertIsNone(app.user_from_token("stale"))
            self.assertEqual(app.user_from_token("fresh")["username"], "listener")


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
