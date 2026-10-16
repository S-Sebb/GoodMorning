"""Briefing polish: weather display words, dated news badges, icon section nav."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))

import unittest

from goodmorning.briefings import briefing_document as native
from goodmorning.briefings import briefing_web as web


class WeatherDisplayTests(unittest.TestCase):
    def test_weather_parts_normalize_raw_values_into_main_and_sub(self):
        for card, raw, parts in (('temperature', '16C (14.5-20.4C)', ('16°C', '(14.5–20.4°C)')),
                                 ('temperature', '14°C', ('14°C', None)),
                                 ('precipitation', '65% - rain yes', ('65%', 'Rain likely')),
                                 ('precipitation', '0% - rain no', ('0%', 'No rain')),
                                 ('air', 'US AQI 30 - good', ('30', 'Good')),
                                 ('air', '31', ('31', None))):
            with self.subTest(card=card, raw=raw):
                self.assertEqual(native.weather_parts(card, raw), parts)

    def test_rendered_weather_never_shows_raw_or_joined_values(self):
        rendered = native.render_block(['weather', [
            ['temperature', '16C (14.5-20.4C)', 'Cool.'],
            ['precipitation', '65% - rain yes', 'Drizzle.'],
            ['air', 'US AQI 30 - good', 'Good.'],
        ]], {}, '2026-10-13')
        for bad in ('16C (', 'rain yes', 'US AQI 30'):
            self.assertNotIn(bad, rendered)
        for good in ('weather-main">16°C<', 'weather-sub">(14.5–20.4°C)<',
                     'weather-main">65%<', 'weather-sub">Rain likely<',
                     'weather-main">30<', 'weather-sub">Good<'):
            self.assertIn(good, rendered)
        for bad_joined in ('16°C (14.5–20.4°C)', '65% – Rain likely', '30 – Good'):
            self.assertNotIn(bad_joined, rendered)


class DatedTitleTests(unittest.TestCase):
    def test_news_title_splits_and_badges(self):
        base, iso = native.split_dated_title('News — 2026-10-12')
        self.assertEqual((base, iso), ('News', '2026-10-12'))
        self.assertEqual(native.split_dated_title('Weather'), ('Weather', None))
        self.assertEqual(native.humanize_iso_date('2026-10-12'), 'Oct 12')
        heading = native.heading_html('News — 2026-10-12')
        self.assertIn('section-date', heading)
        self.assertIn('Oct 12', heading)
        self.assertNotIn('News — 2026-10-12', heading)

    def test_edition_keeps_full_date_accessible_but_displays_badge(self):
        doc = {'v': 1, 'greeting': 'Hi', 'opening': 'Test', 'sections': [
            ['news', [['news', 'World', [['H', 'S', [['Src', 'https://example.org']]]]]]],
        ]}
        page = web.edition(doc, '2026-10-13', 'gm', {'gm': True})
        self.assertIn('aria-label="01: News — 2026-10-12"', page)
        self.assertIn('preview-date', page)
        self.assertIn('Oct 12', page)
        self.assertIn('section-date', page)


if __name__ == '__main__':
    unittest.main()
