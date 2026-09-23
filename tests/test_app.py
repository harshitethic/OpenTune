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


class LibraryItemValidationTests(unittest.TestCase):
    def test_accepts_valid_library_item(self):
        item = app.validate_library_item(
            {
                "videoId": "abc123",
                "title": "Song",
                "artist": "Artist",
                "thumbnail": "https://example.test/thumb.jpg",
            }
        )
        self.assertEqual(
            item,
            (
                "abc123",
                "Song",
                "Artist",
                "https://example.test/thumb.jpg",
            ),
        )

    def test_rejects_non_string_metadata(self):
        with self.assertRaisesRegex(ValueError, "title must be a string"):
            app.validate_library_item(
                {"videoId": "abc123", "title": {"unexpected": "object"}}
            )

    def test_rejects_oversized_video_id(self):
        with self.assertRaisesRegex(ValueError, "videoId is too long"):
            app.validate_library_item(
                {"videoId": "x" * (app.MAX_VIDEO_ID_LENGTH + 1)}
            )

    def test_rejects_oversized_thumbnail(self):
        with self.assertRaisesRegex(ValueError, "thumbnail is too long"):
            app.validate_library_item(
                {
                    "videoId": "abc123",
                    "thumbnail": "x" * (app.MAX_THUMBNAIL_LENGTH + 1),
                }
            )


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
