"""The newest Android app release, read from this repository's GitHub releases and cached.

The app and the website inside it ask their own GoodMorning server, so a phone needs no access to
GitHub's API to learn about updates; the APK itself still downloads from the release.
"""
import json
import re
import threading
import time
from urllib.request import Request, build_opener

RELEASES = 'https://api.github.com/repos/S-Sebb/GoodMorning/releases?per_page=10'
FRESH_SECONDS = 600
_cache = {'at': 0.0, 'release': {}}
_lock = threading.Lock()


def newest(releases):
    """The highest published android-v<code> release with an APK, pre-releases included while the app is in beta."""
    best = {}
    for release in releases if isinstance(releases, list) else []:
        tag = re.fullmatch(r'android-v(\d{1,6})', str(release.get('tag_name', '')))
        if not tag or release.get('draft') or int(tag[1]) <= best.get('code', 0):
            continue
        apk = next((asset['browser_download_url'] for asset in release.get('assets', [])
                    if str(asset.get('browser_download_url', '')).startswith('https://github.com/')
                    and asset['browser_download_url'].endswith('.apk')), None)
        if apk:
            best = {'code': int(tag[1]), 'name': str(release.get('name') or tag[0])[:40], 'apk': apk}
    return best


def fetch():
    """Separate so tests can replace the network."""
    request = Request(RELEASES, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'GoodMorning'})
    with build_opener().open(request, timeout=10) as response:
        return json.loads(response.read(1 << 20))


def latest():
    """The cached newest release, refreshed every ten minutes; the last answer stays while GitHub is unreachable."""
    with _lock:
        if time.time() - _cache['at'] >= FRESH_SECONDS:
            _cache['at'] = time.time()
            try:
                _cache['release'] = newest(fetch())
            except (OSError, ValueError):
                pass
        return _cache['release']
