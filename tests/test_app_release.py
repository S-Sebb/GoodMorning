"""The newest Android app release from synthetic GitHub answers; no network."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from goodmorning.security import app_release


def release(tag, *, draft=False, prerelease=True, asset="GoodMorning.apk", name=""):
    return {
        "tag_name": tag,
        "name": name,
        "draft": draft,
        "prerelease": prerelease,
        "assets": [
            {
                "browser_download_url": "https://github.com/S-Sebb/GoodMorning/releases/download/"
                + tag
                + "/"
                + asset
            }
        ],
    }


class AppReleaseTests(unittest.TestCase):
    def setUp(self):
        app_release._cache.update(at=0.0, release={})
        app_release._apk.update(name="", code=0, data=b"")

    def test_the_highest_published_build_with_an_apk_wins_pre_releases_included(self):
        releases = [
            release("deploy/20261021-ship-abc"),
            release("android-v9", draft=True),
            release("android-v8", asset="notes.txt"),
            release("android-v4", name="0.2"),
            release("android-v5", name="0.3"),
            release("android-v3", prerelease=False),
        ]
        self.assertEqual(
            app_release.newest(releases),
            {
                "code": 5,
                "name": "0.3",
                "apk": "https://github.com/S-Sebb/GoodMorning/releases/download/android-v5/GoodMorning.apk",
            },
        )
        self.assertEqual(app_release.newest([]), {})
        self.assertEqual(app_release.newest({"message": "rate limited"}), {})
        foreign = release("android-v6")
        foreign["assets"] = [
            {"browser_download_url": "https://evil.test/GoodMorning.apk"}
        ]
        self.assertEqual(app_release.newest([foreign]), {})

    def test_answers_are_cached_and_kept_while_github_is_unreachable(self):
        calls = []

        def fetch():
            calls.append(1)
            if len(calls) > 1:
                raise OSError("offline")
            return [release("android-v5", name="0.3")]

        clock = [1000.0]
        with (
            patch.object(app_release, "fetch", fetch),
            patch.object(app_release.time, "time", lambda: clock[0]),
        ):
            self.assertEqual(app_release.latest()["code"], 5)
            self.assertEqual(app_release.latest()["code"], 5)
            self.assertEqual(len(calls), 1)
            clock[0] += app_release.FRESH_SECONDS
            self.assertEqual(
                app_release.latest()["code"], 5
            )  # Offline now: the last answer stays.
            self.assertEqual(len(calls), 2)

    def test_the_apk_is_fetched_once_per_build_and_kept_while_github_fails(self):
        newest = [{"code": 5, "name": "0.3", "apk": "https://github.com/x/5.apk"}]
        answers = {
            "https://github.com/x/5.apk": b"PK five",
            "https://github.com/x/6.apk": OSError("offline"),
        }
        calls = []

        def download(url):
            calls.append(url)
            if isinstance(answers[url], Exception):
                raise answers[url]
            return answers[url]

        with (
            patch.object(app_release, "latest", lambda: newest[0]),
            patch.object(app_release, "download", download),
        ):
            self.assertEqual(app_release.apk(), ("0.3", b"PK five"))
            self.assertEqual(app_release.apk(), ("0.3", b"PK five"))
            self.assertEqual(len(calls), 1)
            newest[0] = {"code": 6, "name": "0.4", "apk": "https://github.com/x/6.apk"}
            self.assertEqual(
                app_release.apk(), ("0.3", b"PK five")
            )  # GitHub unreachable: the last copy stays.

    def test_nothing_is_offered_before_any_apk_was_fetched(self):
        with patch.object(app_release, "latest", dict):
            self.assertIsNone(app_release.apk())


if __name__ == "__main__":
    unittest.main()
