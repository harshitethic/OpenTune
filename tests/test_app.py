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


class PlaylistTests(unittest.TestCase):
    def with_temp_db(self):
        temp = tempfile.TemporaryDirectory()
        previous = app.DB
        app.DB = Path(temp.name) / "opentune.db"
        app.init_db()
        return temp, previous

    def create_user(self, username):
        connection = app.db()
        cursor = connection.execute(
            """
            INSERT INTO users(username,password_hash,recovery_hash,recovery_salt)
            VALUES(?,?,?,?)
            """,
            (username, "digest:salt", "recovery", "salt"),
        )
        connection.commit()
        user_id = cursor.lastrowid
        connection.close()
        return user_id

    def test_playlist_crud_and_item_counts(self):
        temp, previous = self.with_temp_db()
        try:
            user_id = self.create_user("harshit")
            playlist = app.create_playlist(user_id, "Gym")
            self.assertEqual(playlist["name"], "Gym")

            added = app.add_playlist_item(
                user_id,
                playlist["id"],
                {
                    "videoId": "abc123",
                    "title": "Track",
                    "artist": "Artist",
                    "thumbnail": "https://example.test/cover.jpg",
                },
            )
            self.assertTrue(added)
            self.assertFalse(
                app.add_playlist_item(
                    user_id,
                    playlist["id"],
                    {"videoId": "abc123", "title": "Track"},
                )
            )

            rows = app.list_playlists(user_id)
            self.assertEqual(rows[0]["item_count"], 1)

            detail = app.get_playlist(user_id, playlist["id"])
            self.assertEqual(detail["item_count"], 1)
            self.assertEqual(detail["items"][0]["video_id"], "abc123")

            self.assertTrue(
                app.remove_playlist_item(user_id, playlist["id"], "abc123")
            )
            self.assertEqual(
                app.get_playlist(user_id, playlist["id"])["item_count"],
                0,
            )
        finally:
            app.DB = previous
            temp.cleanup()

    def test_playlist_ownership_is_enforced(self):
        temp, previous = self.with_temp_db()
        try:
            owner_id = self.create_user("owner")
            other_id = self.create_user("other")
            playlist = app.create_playlist(owner_id, "Private")

            with self.assertRaises(LookupError):
                app.get_playlist(other_id, playlist["id"])
            with self.assertRaises(LookupError):
                app.add_playlist_item(
                    other_id,
                    playlist["id"],
                    {"videoId": "abc123"},
                )
            with self.assertRaises(LookupError):
                app.delete_playlist(other_id, playlist["id"])
        finally:
            app.DB = previous
            temp.cleanup()

    def test_deleting_playlist_cascades_items(self):
        temp, previous = self.with_temp_db()
        try:
            user_id = self.create_user("cascade")
            playlist = app.create_playlist(user_id, "Delete me")
            app.add_playlist_item(
                user_id,
                playlist["id"],
                {"videoId": "song-one"},
            )

            app.delete_playlist(user_id, playlist["id"])

            connection = app.db()
            items = connection.execute(
                "SELECT COUNT(*) FROM playlist_items WHERE playlist_id=?",
                (playlist["id"],),
            ).fetchone()[0]
            connection.close()
            self.assertEqual(items, 0)
            with self.assertRaises(LookupError):
                app.get_playlist(user_id, playlist["id"])
        finally:
            app.DB = previous
            temp.cleanup()

    def test_playlist_name_validation_and_uniqueness(self):
        temp, previous = self.with_temp_db()
        try:
            user_id = self.create_user("names")
            app.create_playlist(user_id, "Road Trip")
            with self.assertRaisesRegex(ValueError, "already exists"):
                app.create_playlist(user_id, "Road Trip")
            with self.assertRaisesRegex(ValueError, "required"):
                app.create_playlist(user_id, "   ")
        finally:
            app.DB = previous
            temp.cleanup()


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
