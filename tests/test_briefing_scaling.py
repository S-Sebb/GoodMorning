"""Bounded caches and storage/HTTP reuse contracts for native editions."""
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.briefings import briefing_images as images
from goodmorning.briefings import briefing_web as web
from goodmorning.web.briefing_resources import ByteCache, Resources, accepts_gzip
from goodmorning.web.briefing_server import BrowserApp
import test_briefing_server as server_tests
from test_briefing_web import GM


class ResourceTests(unittest.TestCase):
    def test_saved_page_cache_reuses_html_and_invalidates_records_dates_and_language(self):
        from goodmorning.web import language as ui
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root=Path(directory);(root/'daily').mkdir();(root/'profile.md').write_text('timezone: Europe/London\n')
            source=root/'daily/2034-03-17.gm.json';source.write_text(GM)
            app=BrowserApp(root,now=lambda:datetime(2034,3,17,12,tzinfo=timezone.utc))
            with patch.object(ui,'page',wraps=ui.page) as render:
                first=app.page('2034-03-17','gm',False)
                self.assertIs(app.page('2034-03-17','gm',False),first)
                self.assertEqual(render.call_count,1)
                app.page('2034-03-17','gm',True);self.assertEqual(render.call_count,2)
                token=ui.CURRENT.set('zh-CN')
                try:app.page('2034-03-17','gm',False)
                finally:ui.CURRENT.reset(token)
                self.assertEqual(render.call_count,3)
                source.write_text(GM.replace('Good morning','Different greeting'))
                self.assertNotEqual(app.page('2034-03-17','gm',False),first)
                self.assertEqual(render.call_count,4)
                (root/'daily/2034-03-16.gm.json').write_text(GM)
                app.page('2034-03-17','gm',False);self.assertEqual(render.call_count,5)
                app.now=lambda:datetime(2034,3,18,12,tzinfo=timezone.utc)
                app.page('2034-03-17','gm',False);self.assertEqual(render.call_count,6)
            self.assertLessEqual(app.pages.size,8*1024*1024)
            (root/'profile.md').write_text('timezone: Asia/Tokyo\n')
            app.today();self.assertEqual(app.zone,'Asia/Tokyo')

    def test_gzip_quality_negotiation(self):
        for header in ('gzip', 'br, gzip;q=.5', '*;q=1'):
            self.assertTrue(accepts_gzip(header))
        for header in ('', 'br', 'gzip;q=0, *;q=1', 'gzip;q=broken', 'gzip;q=2'):
            self.assertFalse(accepts_gzip(header))

    def test_byte_cache_evicts_by_size_and_recency(self):
        cache = ByteCache(10, 2)
        cache.put('a', b'aaaa', 4); cache.put('b', b'bbbb', 4)
        self.assertEqual(cache.get('a'), b'aaaa')
        cache.put('c', b'cccc', 4)
        self.assertIsNone(cache.get('b')); self.assertLessEqual(cache.size, 10)
        cache.put('huge', b'x' * 20, 20)
        self.assertIsNone(cache.get('huge'))

    def test_asset_urls_are_identical_across_instances_and_font_is_shared(self):
        one = Resources(web.ASSETS); two = Resources(web.ASSETS)
        self.assertEqual(one.urls, two.urls)
        css = one.paths[one.urls['briefing.css']]
        self.assertIn(one.urls['fonts/lora-italic.woff2'].encode(), css.data)
        self.assertEqual(gzip.decompress(css.compressed), css.data)
        self.assertLess(len(css.compressed), len(css.data) * .3)
        self.assertLess(len(one.paths[one.urls['fonts/lora-italic.woff2']].data), 100000)


class TransportTests(server_tests.HTTPTests):
    def test_assets_compress_and_revalidate_without_caching_private_pages(self):
        with urlopen(self.address + '/gm.html') as response:
            page = response.read().decode()
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        path = re.search(r'href="([^\"]+/briefing.css)"', page)[1]
        with urlopen(Request(self.address + path, headers={'Accept-Encoding': 'gzip'})) as response:
            data = response.read(); etag = response.headers['ETag']
            self.assertEqual(response.headers['Content-Encoding'], 'gzip')
            self.assertIn('immutable', response.headers['Cache-Control'])
            self.assertIn(b'@font-face', gzip.decompress(data))
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(self.address + path, headers={'Accept-Encoding': 'gzip', 'If-None-Match': etag}))
        self.assertEqual(caught.exception.code, 304); caught.exception.close()
        with urlopen(Request(self.address + path, headers={'Accept-Encoding': 'gzip;q=0'})) as response:
            self.assertIsNone(response.headers.get('Content-Encoding'))
        with urlopen(Request(self.address + path, method='HEAD')) as response:
            self.assertEqual(response.read(), b'')

    def test_html_with_language_or_generation_secrets_does_not_compress(self):
        (self.root / 'daily' / f'{self.date}.gm.json').write_text(GM)
        with urlopen(Request(self.address + '/gm.html', headers={'Accept-Encoding': 'gzip'})) as response:
            self.assertIsNone(response.headers['Content-Encoding'])
            page = response.read().decode()
            self.assertIn(self.csrf, page)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        with urlopen(Request(self.address + '/gn.html', headers={'Accept-Encoding': 'gzip'})) as response:
            self.assertIsNone(response.headers.get('Content-Encoding'))
            self.assertIn(self.csrf, response.read().decode())


@unittest.skipUnless(importlib.util.find_spec('PIL'), 'Optional Pillow dependency')
class ImageReuseTests(unittest.TestCase):
    def test_failed_images_cool_down_then_recover_without_losing_other_edition(self):
        from PIL import Image
        payload = io.BytesIO(); Image.new('RGB', (64, 48), 'navy').save(payload, format='PNG')
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder:
            root = Path(folder); cache = root / '2034-03-17'; pool = root / 'objects'
            url = 'https://example.org/story'; other = 'https://example.org/evening'
            def replies(url, *args):
                return (payload.getvalue(), 'image/png', url) if url.endswith('.png') else (b'<meta property="og:image" content="/photo.png">', 'text/html', url)
            with patch.object(images.time, 'time', return_value=1000), patch.object(images, 'fetch_public', side_effect=TimeoutError('Synthetic timeout')) as fetch:
                failed = images.cache_previews([url], cache, pool)
                self.assertEqual(failed[url]['status'], 'unavailable')
                self.assertEqual(fetch.call_count, 1)
                images.cache_previews([url], cache, pool)
                self.assertEqual(fetch.call_count, 1)
            with patch.object(images.time, 'time', return_value=4601), patch.object(images, 'fetch_public', side_effect=replies):
                recovered = images.cache_previews([url], cache, pool)
                images.cache_previews([other], cache, pool)
            self.assertEqual(recovered[url]['status'], 'cached')
            self.assertEqual(set(json.loads((cache / 'manifest.json').read_text())), {url, other})
            self.assertEqual(len(list(pool.glob('*.webp'))), 1)

    def test_network_budget_is_shared(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder:
            urls = ['https://example.org/' + str(i) for i in range(40)]
            with patch.object(images.time, 'monotonic', side_effect=[0] + [25] * 64), patch.object(images, 'fetch_public', side_effect=AssertionError('Budget exhausted')) as fetch:
                result = images.cache_previews(urls, Path(folder))
            self.assertEqual(len(result), 32)
            fetch.assert_not_called()

    def test_responsive_derivatives_stay_in_memory_and_keep_original(self):
        from PIL import Image
        payload = io.BytesIO(); Image.new('RGB', (640, 360), 'navy').save(payload, format='WEBP')
        data = payload.getvalue(); name = hashlib.sha256(data).hexdigest() + '.webp'
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder:
            root = Path(folder); (root / 'daily').mkdir(); (root / 'profile.md').write_text('timezone: Europe/London\n')
            cache = root / 'browser-images/2034-03-17'; cache.mkdir(parents=True)
            (cache / name).write_bytes(data)
            url = 'https://example.org/story?a=1&b=2'
            (cache / 'manifest.json').write_text(json.dumps({url: {'status': 'cached', 'file': name, 'sha256': name[:64]}}))
            (root / 'daily/2034-03-17.gm.json').write_text(GM)
            app = BrowserApp(root, now=lambda: datetime(2034, 3, 17, 12, tzinfo=timezone.utc))
            before = {p for p in root.rglob('*') if p.is_file()}
            page = app.page('2034-03-17', 'gm', False).decode()
            self.assertIn('srcset="/media/thumb-v1/' + name, page)
            with Image.open(io.BytesIO(app.thumbnail(name))) as small:
                self.assertEqual(small.size, (320, 180))
            self.assertEqual(app.image(name), data)
            self.assertEqual(before, {p for p in root.rglob('*') if p.is_file()})
            self.assertLessEqual(app.thumbnails.size, 2 * 1024 * 1024)

    def test_same_article_and_identical_images_share_one_object_across_days(self):
        from PIL import Image
        payload = io.BytesIO(); Image.new('RGB', (640, 480), 'navy').save(payload, format='PNG')
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder:
            root = Path(folder); pool = root / 'objects'; url = 'https://example.org/article'
            replies = [(b'<meta property="og:image" content="/photo.png">', 'text/html', url), (payload.getvalue(), 'image/png', 'https://example.org/photo.png')]
            with patch.object(images, 'fetch_public', side_effect=replies):
                one = images.cache_previews([url], root / '2034-03-17', pool)
            with patch.object(images, 'fetch_public', side_effect=AssertionError('Repeated article should not refetch')):
                two = images.cache_previews([url], root / '2034-03-18', pool)
            self.assertEqual(one, two)
            self.assertEqual(len(list(pool.glob('*.webp'))), 1)
            self.assertEqual(list((root / '2034-03-17').glob('*.webp')), [])
            self.assertEqual(len(images.cached_previews(root / '2034-03-18', [url])[1]), 1)
            with patch.object(images, 'fetch_public', side_effect=replies):
                images.cache_previews(['https://example.org/different-article'], root / '2034-03-19', pool)
            self.assertEqual(len(list(pool.glob('*.webp'))), 1)

    def test_corrupt_manifest_does_not_break_briefing(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as folder:
            root = Path(folder)
            for data in ('not json', '[]', '{"https://example.org":42}', '{"https://example.org":{"status":"cached","file":42}}'):
                (root / 'manifest.json').write_text(data)
                self.assertEqual(images.cached_previews(root, ['https://example.org']), ({}, {}))


if __name__ == '__main__':
    unittest.main()
