"""Clock-based edition colours, including boundaries and account timezones."""
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.web.chat_theme import clock_theme
from goodmorning.web.briefing_server import BrowserApp


class ChatThemeTests(unittest.TestCase):
    def test_six_and_eighteen_are_exact_local_boundaries(self):
        for time, expected in (('05:59:59', 'gn'), ('06:00:00', 'gm'), ('17:59:59', 'gm'), ('18:00:00', 'gn'), ('00:00:00', 'gn')):
            self.assertEqual(clock_theme('UTC', datetime.fromisoformat('2026-10-11T' + time + '+00:00'))['theme'], expected)

    def test_accounts_use_their_own_timezone_not_the_server_timezone(self):
        instant = datetime.fromisoformat('2026-10-11T10:00:00+00:00')
        self.assertEqual(clock_theme('Europe/London', instant)['theme'], 'gm')
        self.assertEqual(clock_theme('Asia/Shanghai', instant)['theme'], 'gn')
        self.assertEqual(clock_theme('America/Los_Angeles', instant)['theme'], 'gn')

    def test_daylight_saving_and_uninitialized_profiles(self):
        for zone, instant, expected in (
            ('Europe/London', '2026-07-01T05:00:00+00:00', 'gm'),
            ('Europe/London', '2026-07-01T17:00:00+00:00', 'gn'),
            ('Europe/London', '2026-12-01T05:59:59+00:00', 'gn'),
            ('Europe/London', '2026-12-01T06:00:00+00:00', 'gm')):
            self.assertEqual(clock_theme(zone, datetime.fromisoformat(instant))['theme'], expected)
        for zone in (None, '', 'Not/A_Timezone'):
            self.assertEqual(clock_theme(zone, datetime.fromisoformat('2026-10-11T12:00:00+00:00')),
                             {'timezone': 'UTC', 'theme': 'gm'})

    def test_initial_html_already_has_the_correct_theme_without_record_changes(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            profile = root / 'profile.md'
            profile.write_text('city: Shanghai\ntimezone: Asia/Shanghai\nnews_country: CN\nsecretary_language: English\n')
            original = profile.read_bytes()
            for instant, expected in (('2026-10-10T22:00:00+00:00', 'gm'), ('2026-10-11T10:00:00+00:00', 'gn')):
                app = BrowserApp(root, now=lambda: datetime.fromisoformat(instant))
                self.assertEqual(app.chat_settings()['timezone'], 'Asia/Shanghai')
                self.assertIn(f'data-edition="{expected}"', app.chat_page().decode())
            self.assertEqual(profile.read_bytes(), original)
