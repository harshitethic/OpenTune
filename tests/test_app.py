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


class PasswordResetTests(unittest.TestCase):
    def test_password_reset_revokes_existing_sessions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            previous_db = app.DB
            app.DB = Path(temp_dir) / "opentune.db"
            try:
                app.init_db()
                digest, salt = app.hash_password("old-password")
                recovery_digest, recovery_salt = app.hash_password("answer")
                c = app.db()
                c.execute(
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
                user_id = c.execute(
                    "SELECT id FROM users WHERE username='harshit'"
                ).fetchone()[0]
                c.execute(
                    "INSERT INTO sessions(token,user_id) VALUES(?,?)",
                    ("session-one", user_id),
                )
                c.execute(
                    "INSERT INTO sessions(token,user_id) VALUES(?,?)",
                    ("session-two", user_id),
                )
                c.commit()
                c.close()

                app.replace_password_and_revoke_sessions(
                    user_id,
                    "new-password",
                )

                c = app.db()
                row = c.execute(
                    "SELECT password_hash FROM users WHERE id=?",
                    (user_id,),
                ).fetchone()
                sessions = c.execute(
                    "SELECT token FROM sessions WHERE user_id=?",
                    (user_id,),
                ).fetchall()
                c.close()

                new_digest, new_salt = row["password_hash"].split(":", 1)
                self.assertTrue(
                    app.check_password("new-password", new_digest, new_salt)
                )
                self.assertFalse(
                    app.check_password("old-password", new_digest, new_salt)
                )
                self.assertEqual(sessions, [])
            finally:
                app.DB = previous_db


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
