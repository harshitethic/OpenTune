import sqlite3
import unittest

import app


class RecoverySessionTests(unittest.TestCase):
    def test_password_reset_revokes_all_tokens_only_for_target_user(self):
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, password_hash TEXT)")
            connection.execute("CREATE TABLE sessions(token TEXT, user_id INTEGER)")
            connection.executemany("INSERT INTO users(id, password_hash) VALUES (?, ?)", [(1, "old"), (2, "other")])
            connection.executemany("INSERT INTO sessions(token, user_id) VALUES (?, ?)",
                                   [("mobile", 1), ("desktop", 1), ("other", 2)])
            app.replace_password_and_revoke_sessions(connection, 1, "new-password")
            self.assertEqual(connection.execute("SELECT token FROM sessions ORDER BY token").fetchall(), [("other",)])
            stored = connection.execute("SELECT password_hash FROM users WHERE id=1").fetchone()[0]
            digest, salt = stored.split(":", 1)
            self.assertTrue(app.check_password("new-password", digest, salt))
            self.assertFalse(app.check_password("old-password", digest, salt))
        finally:
            connection.close()


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
