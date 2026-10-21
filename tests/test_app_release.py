"""The newest Android app release from synthetic GitHub answers; no network."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.security import app_release


def release(tag, *, draft=False, prerelease=True, asset='GoodMorning.apk', name=''):
    return {'tag_name': tag, 'name': name, 'draft': draft, 'prerelease': prerelease,
            'assets': [{'browser_download_url': 'https://github.com/S-Sebb/GoodMorning/releases/download/' + tag + '/' + asset}]}


class AppReleaseTests(unittest.TestCase):
    def setUp(self):
        app_release._cache.update(at=0.0, release={})

    def test_the_highest_published_build_with_an_apk_wins_pre_releases_included(self):
        releases = [release('deploy/20261021-ship-abc'), release('android-v9', draft=True), release('android-v8', asset='notes.txt'),
                    release('android-v4', name='0.2'), release('android-v5', name='0.3'), release('android-v3', prerelease=False)]
        self.assertEqual(app_release.newest(releases), {'code': 5, 'name': '0.3',
                         'apk': 'https://github.com/S-Sebb/GoodMorning/releases/download/android-v5/GoodMorning.apk'})
        self.assertEqual(app_release.newest([]), {})
        self.assertEqual(app_release.newest({'message': 'rate limited'}), {})
        foreign = release('android-v6')
        foreign['assets'] = [{'browser_download_url': 'https://evil.test/GoodMorning.apk'}]
        self.assertEqual(app_release.newest([foreign]), {})

    def test_answers_are_cached_and_kept_while_github_is_unreachable(self):
        calls = []
        def fetch():
            calls.append(1)
            if len(calls) > 1:
                raise OSError('offline')
            return [release('android-v5', name='0.3')]
        clock = [1000.0]
        with patch.object(app_release, 'fetch', fetch), patch.object(app_release.time, 'time', lambda: clock[0]):
            self.assertEqual(app_release.latest()['code'], 5)
            self.assertEqual(app_release.latest()['code'], 5)
            self.assertEqual(len(calls), 1)
            clock[0] += app_release.FRESH_SECONDS
            self.assertEqual(app_release.latest()['code'], 5)  # Offline now: the last answer stays.
            self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
