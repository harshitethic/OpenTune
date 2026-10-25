import sqlite3
import unittest

import app


class RecentHistoryTests(unittest.TestCase):
    def test_history_is_bounded_per_user_and_keeps_newest(self):
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("CREATE TABLE history(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, video_id TEXT, title TEXT, artist TEXT, thumbnail TEXT)")
            app.add_history(connection, 2, "other-user")
            for index in range(105):
                app.add_history(connection, 1, str(index))
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM history WHERE user_id=1").fetchone()[0], 100)
            self.assertEqual(connection.execute("SELECT MIN(CAST(video_id AS INT)), MAX(CAST(video_id AS INT)) FROM history WHERE user_id=1").fetchone(), (5, 104))
            self.assertEqual(connection.execute("SELECT video_id FROM history WHERE user_id=2").fetchone(), ("other-user",))
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
