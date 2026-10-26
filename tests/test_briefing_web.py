"""Native browser editions preserve saved content without changing records."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.briefings import briefing_document as native
from goodmorning.briefings import briefing_web as web

GM = native.encode({'v': 1, 'greeting': 'Good morning', 'opening': 'Make room for today.', 'sections': [
    ['weather', [['weather', [['temperature', '14°C', 'Cool.'], ['precipitation', '0%', 'No rain.'], ['air', '31', 'Good air.']]]]],
    ['news', [['news', 'World', [['A complete story.', 'A full summary.', [['Source', 'https://example.org/story?a=1&b=2']]]]]]],
    ['schedule', [['agenda', [['2026-10-10', '09:00–11:00', 'Teaching', 'Room A', 'Bring notes']]]]],
    ['must-do', [['tasks', [['open', 'Ranking', 'Due tomorrow.'], ['done', 'Confirmed task.', 'User confirmed.']]]]]],
    'closing': 'A warm closing.'})
GN = native.encode({'v': 1, 'greeting': 'Good evening.', 'opening': 'Keep the evening clear.', 'sections': [
    ['today', [['p', 'Progress unreported.']]], ['tomorrow', [['p', 'Sunday is clear.']]]]})


class BrowserBriefingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.runtime = Path(self.temp.name)
        (self.runtime / 'daily').mkdir()
        self.source = self.runtime / 'daily/2026-10-10.gm.json'
        self.source.write_text(GM)

    def test_real_structure_and_source_unchanged(self):
        before = hashlib.sha256(self.source.read_bytes()).hexdigest()
        files = web.build(self.runtime, '2026-10-10')
        page = files['gm.html'].decode()
        self.assertLess(page.index('<h2>Weather'), page.index('14°C'))
        self.assertLess(page.index('14°C'), page.index('<h2>News'))
        self.assertIn('href="https://example.org/story?a=1&amp;b=2"', page)
        self.assertEqual(page.count('class="edition-unavailable"'), 1)
        self.assertNotIn('href="gn.html"', page)
        self.assertEqual(files['gm.json'], self.source.read_bytes())
        self.assertEqual(before, hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertFalse((self.runtime / 'browser').exists())

    def test_both_editions_and_evening_only(self):
        (self.runtime / 'daily/2026-10-10.gn.json').write_text(GN)
        files = web.build(self.runtime, '2026-10-10')
        self.assertIn('href="gn.html"', files['gm.html'].decode())
        self.assertIn('data-edition="gn"', files['gn.html'].decode())
        self.source.unlink()
        files = web.build(self.runtime, '2026-10-10')
        self.assertNotIn('gm.html', files)
        self.assertEqual(files['index.html'], files['gn.html'])
        self.assertIn('class="edition-unavailable"', files['gn.html'].decode())
        self.assertNotIn('href="gm.html"', files['gn.html'].decode())

    def test_toolbar_artwork_tagline_and_font_are_self_contained(self):
        files = web.build(self.runtime, '2026-10-10')
        page = files['gm.html'].decode()
        for value in ('class="wordmark"', 'class="celestial-art"', 'class="sky-scene"', 'class="back-to-top"'):
            self.assertIn(value, page)
        self.assertLess(page.index('class="briefing-tools"'), page.index('<article'))
        self.assertLess(page.index('href="gm.json"'), page.index('<article'))
        self.assertIn('fonts/lora-italic.woff2', files)
        self.assertIn('fonts/OFL.txt', files)

    def test_refuses_invalid_missing_or_symlinked_inputs(self):
        for date in ('2026-10-9', '../../profile', '2026-02-30', '2026-10-11'):
            with self.subTest(date=date), self.assertRaises(ValueError):
                web.build(self.runtime, date)
        linked = self.runtime / 'original.json'
        self.source.rename(linked)
        self.source.symlink_to(linked)
        with self.assertRaises(ValueError):
            web.build(self.runtime, '2026-10-10')

    def test_scroll_map_uses_safe_section_previews(self):
        page = web.edition(json.loads(GM), '2026-10-10', 'gm', {'gm': True})
        self.assertEqual(page.count('class="scroll-chunk"'), 4)
        self.assertEqual(page.count('role="tooltip"'), 4)
        self.assertEqual(page.count('class="touch-hint"'), 4)
        for value in ('aria-label="01: Weather"', 'aria-describedby="preview-1"', 'viewport-fit=cover'):
            self.assertIn(value, page)
        self.assertLess(len(web.PreviewText().excerpt('<p>' + 'word ' * 200 + '</p>')), 185)

    def test_cli_fetches_previews_only_with_explicit_flag_and_never_exports(self):
        argv = ['web', '--secretary-dir', str(self.runtime), '--date', '2026-10-10']
        with patch.object(sys, 'argv', argv), patch.object(web, 'cache_previews') as fetch, \
                contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            web.main()
        fetch.assert_not_called()
        output = io.StringIO()
        with patch.object(sys, 'argv', argv + ['--fetch-images']), patch.object(web, 'cache_previews') as fetch, contextlib.redirect_stdout(output):
            web.main()
        fetch.assert_called_once()
        self.assertFalse(json.loads(output.getvalue())['exported'])
        self.assertFalse((self.runtime / 'browser').exists())


if __name__ == '__main__':
    unittest.main()
