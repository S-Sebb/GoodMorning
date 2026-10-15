"""Rich layouts and publisher-image boundaries, with synthetic data only."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from support import TEMP_ROOT

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from goodmorning.briefings import briefing_images as images
from goodmorning.briefings import briefing_layout as layout
from goodmorning.briefings import briefing_document as native


class RichLayoutTests(unittest.TestCase):
    def test_agenda_preserves_dates_times_and_every_detail(self):
        rendered = native.render_block(['agenda', [['Mon 2026-10-12', '09:00–11:00', 'Teaching', 'Room A', 'Bring notes; owner Ada'], ['Tue 2026-10-13', 'TBC', 'Seminar', 'Online', 'Read brief; owner Sam']]], {})
        for value in ('Mon 2026-10-12', 'Tue 2026-10-13', '09:00–11:00', 'TBC', 'Teaching', 'Room A', 'Bring notes', 'Ada', 'Seminar', 'Online', 'Read brief', 'Sam'):
            self.assertIn(value, rendered)
        self.assertEqual(rendered.count('class="agenda-event"'), 2)
        self.assertNotIn('<table>', rendered)

    def test_unfamiliar_tables_keep_accessible_original(self):
        rendered = native.render_block(['table', ['Model', 'Score'], [['A', '0.9']]], {})
        self.assertIn('class="table-scroll"', rendered)
        self.assertIn('<th>Model</th>', rendered)
        self.assertIn('<td>0.9</td>', rendered)

    def test_weather_values_are_explicit_not_inferred_from_prose(self):
        rendered = native.render_block(['weather', [['temperature', None, 'Range 9.7–15.2°C.'], ['warning', None, 'High wind: stay indoors.']]], {})
        self.assertNotIn('class="weather-value"', rendered)
        self.assertIn('High wind: stay indoors.', rendered)
        self.assertIn('class="weather-tile other"', rendered)

    def test_news_keeps_full_summary_all_sources_and_honest_fallback(self):
        content = ['news', 'AI', [['Headline', 'Complete summary, including the warning.', [['Publisher', 'https://example.org/a']]]]]
        fallback = native.render_block(content, {})
        for value in ('Headline', 'Complete summary, including the warning.', 'Publisher'):
            self.assertIn(value, fallback)
        self.assertIn('class="news-visual illustration"', fallback)
        rendered = native.render_block(content, {'https://example.org/a': {'src': 'media/' + 'a' * 64 + '.webp', 'alt': 'A & B'}})
        self.assertIn('loading="lazy"', rendered)
        self.assertIn('alt="A &amp; B"', rendered)
        self.assertRegex(rendered, r'<figure class="news-visual"><img [^>]*><figcaption>.*Publisher.*</figcaption>')
        self.assertNotIn('illustration', rendered)

    def test_task_split_preserves_status_wording_and_nested_markup(self):
        rendered = native.render_block(['tasks', [['open', 'Ranking — with a dash', 'Due tomorrow.'], ['done', 'Confirmed task.', 'User confirmed.']]], {})
        for value in ('Ranking — with a dash', 'Due tomorrow.', 'Confirmed task.', 'aria-label="Not completed"', 'aria-label="Completed"'):
            self.assertIn(value, rendered)
        self.assertIn('class="task-title"', rendered)
        self.assertIn('class="task-detail"', rendered)

    def test_country_flags_use_explicit_categories(self):
        for country, label in [('CN', 'China'), ('GB', 'United Kingdom'), ('US', 'United States'), ('CA', 'Canada'), ('AU', 'Australia')]:
            flag = layout.category_icon('National — ' + country)
            self.assertIn('class="country-flag"', flag)
            self.assertIn('aria-label="' + label + '"', flag)
        self.assertIn('class="data-icon"', layout.category_icon('World'))
        self.assertIn('class="country-code"', layout.category_icon('National — XX'))


class PublisherBoundaryTests(unittest.TestCase):
    def test_metadata_prefers_publisher_image_and_keeps_alt(self):
        parser = images.PreviewMetadata()
        parser.feed('<meta name="twitter:image" content="/twitter.jpg"><meta property="og:image" content="/photo.jpg"><meta property="og:image:alt" content="The scene">')
        self.assertEqual(parser.image, '/photo.jpg')
        self.assertEqual(parser.alt, 'The scene')

    def test_private_protocols_addresses_and_credentials_are_refused(self):
        for url in ('http://example.org/a', 'file:///etc/passwd', 'https://user:secret@example.org/a', 'https://example.org:8443/a'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                images.public_target(url)
        for address in ('127.0.0.1', '10.0.0.2', '169.254.169.254', '::1', '192.168.1.2'):
            answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))]
            with patch.object(images.socket, 'getaddrinfo', return_value=answer), self.assertRaises(ValueError):
                images.public_target('https://example.org/a')

    def test_private_redirect_is_refused_before_second_connection(self):
        answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]
        response = unittest.mock.Mock(status=302)
        response.getheader.return_value = 'http://127.0.0.1/private'
        connection = unittest.mock.Mock()
        connection.getresponse.return_value = response
        with patch.object(images.socket, 'getaddrinfo', return_value=answer), patch.object(images, 'PinnedHTTPS', return_value=connection) as constructor:
            with self.assertRaises(ValueError):
                images.fetch_public('https://example.org/a', 1000, time.monotonic() + 10)
            self.assertEqual(constructor.call_count, 1)

    @unittest.skipUnless(importlib.util.find_spec('PIL'), 'Optional Pillow dependency not installed')
    def test_raster_cache_validates_hash_and_manifest_paths(self):
        from PIL import Image
        payload = io.BytesIO()
        Image.new('RGB', (800, 400), 'blue').save(payload, format='PNG')
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            url = 'https://example.org/story'
            responses = [(b'<meta property="og:image" content="/photo.png">', 'text/html', url),
                         (payload.getvalue(), 'image/png', 'https://example.org/photo.png')]
            with patch.object(images, 'fetch_public', side_effect=responses) as fetch:
                receipt = images.cache_previews([url], root)
                self.assertEqual(fetch.call_count, 2)
            self.assertEqual(receipt[url]['status'], 'cached')
            selected, files = images.cached_previews(root, [url])
            self.assertEqual(len(selected), 1)
            self.assertEqual(len(files), 1)
            asset = root / receipt[url]['file']
            asset.write_bytes(b'changed')
            self.assertEqual(images.cached_previews(root, [url]), ({}, {}))
            receipt[url]['file'] = '../profile.md'
            (root / 'manifest.json').write_text(json.dumps(receipt))
            self.assertEqual(images.cached_previews(root, [url]), ({}, {}))

    @unittest.skipUnless(importlib.util.find_spec('PIL'), 'Optional Pillow dependency not installed')
    def test_invalid_manifest_or_symlinked_cache_is_preserved_without_fetching(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory) / 'cache'; root.mkdir()
            manifest = root / 'manifest.json'
            for data in (b'[]', b'not json', b'{"x":"' + b'a' * 100_001 + b'"}'):
                manifest.write_bytes(data)
                with self.subTest(size=len(data)), patch.object(images, 'fetch_public') as fetch, self.assertRaises(ValueError):
                    images.cache_previews(['https://example.org/story'], root)
                fetch.assert_not_called()
                self.assertEqual(manifest.read_bytes(), data)
            outside = Path(directory) / 'outside.json'; outside.write_text('{}')
            manifest.unlink(); manifest.symlink_to(outside)
            linked = Path(directory) / 'linked'; linked.symlink_to(root, target_is_directory=True)
            for cache in (root, linked):
                with self.subTest(cache=cache.name), patch.object(images, 'fetch_public') as fetch, self.assertRaises(ValueError):
                    images.cache_previews(['https://example.org/story'], cache)
                fetch.assert_not_called()
            self.assertEqual(outside.read_text(), '{}')

    def test_corrupt_existing_image_object_is_not_overwritten(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            data = b'RIFF\0\0\0\0WEBP replacement'
            target = Path(directory) / (hashlib.sha256(data).hexdigest() + '.webp')
            target.write_bytes(b'corrupt')
            with self.assertRaises(ValueError):
                images.store_image(Path(directory), target.name, data)
            self.assertEqual(target.read_bytes(), b'corrupt')


if __name__ == '__main__':
    unittest.main()
