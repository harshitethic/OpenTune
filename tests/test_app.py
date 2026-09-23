import tempfile
import unittest
from pathlib import Path

import app


class PasswordHashingTests(unittest.TestCase):
    def test_hash_is_deterministic_for_same_salt(self):
        digest1, salt = app.hash_password("open-tune", "fixed-salt")
        digest2, _ = app.hash_password("open-tune", salt)
        self.assertEqual(digest1, digest2)

    def test_wrong_password_does_not_match(self):
        digest, salt = app.hash_password("correct", "fixed-salt")
        self.assertFalse(app.check_password("wrong", digest, salt))


class AccountDeletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous_db = app.DB
        app.DB = Path(self.temp.name) / "opentune.db"
        app.init_db()

        digest, salt = app.hash_password("correct-password")
        recovery_digest, recovery_salt = app.hash_password("answer")
        connection = app.db()
        cursor = connection.execute(
            """
            INSERT INTO users(username,password_hash,recovery_hash,recovery_salt)
            VALUES(?,?,?,?)
            """,
            (
                "harshit",
                digest + ":" + salt,
                recovery_digest,
                recovery_salt,
            ),
        )
        self.user_id = cursor.lastrowid
        connection.execute(
            "INSERT INTO sessions(token,user_id) VALUES(?,?)",
            ("session-one", self.user_id),
        )
        connection.execute(
            "INSERT INTO sessions(token,user_id) VALUES(?,?)",
            ("session-two", self.user_id),
        )
        connection.execute(
            "INSERT INTO history(user_id,video_id,title) VALUES(?,?,?)",
            (self.user_id, "history-song", "History"),
        )
        connection.execute(
            "INSERT INTO likes(user_id,video_id,title) VALUES(?,?,?)",
            (self.user_id, "liked-song", "Liked"),
        )
        connection.commit()
        connection.close()

    def tearDown(self):
        app.DB = self.previous_db
        self.temp.cleanup()

    def counts(self):
        connection = app.db()
        try:
            return {
                table: connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE "
                    + ("id=?" if table == "users" else "user_id=?"),
                    (self.user_id,),
                ).fetchone()[0]
                for table in ("users", "sessions", "history", "likes")
            }
        finally:
            connection.close()

    def test_delete_account_removes_account_and_owned_data(self):
        app.delete_account(self.user_id, "correct-password")

        self.assertEqual(
            self.counts(),
            {"users": 0, "sessions": 0, "history": 0, "likes": 0},
        )

    def test_wrong_password_leaves_all_data_intact(self):
        with self.assertRaises(PermissionError):
            app.delete_account(self.user_id, "wrong-password")

        self.assertEqual(
            self.counts(),
            {"users": 1, "sessions": 2, "history": 1, "likes": 1},
        )

    def test_invalid_password_is_rejected_before_mutation(self):
        with self.assertRaises(ValueError):
            app.delete_account(self.user_id, "x")

        self.assertEqual(self.counts()["users"], 1)


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
