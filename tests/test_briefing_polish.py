"""Briefing polish: weather display words, dated news badges, icon section nav."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[0]))

import unittest

from goodmorning.briefings import briefing_document as native
from goodmorning.briefings import briefing_web as web


class WeatherDisplayTests(unittest.TestCase):
    def test_temperature_uses_celsius_symbol_and_range_dash(self):
        self.assertEqual(native.weather_display('temperature', '16C (14.5-20.4C)'), '16°C (14.5–20.4°C)')
        self.assertEqual(native.weather_display('temperature', '14°C'), '14°C')

    def test_precipitation_never_shows_raw_rain_tokens(self):
        self.assertEqual(native.weather_display('precipitation', '65% - rain yes'), '65% – Rain likely')
        self.assertEqual(native.weather_display('precipitation', '0% - rain no'), '0% – No rain')
        rendered = native.render_block(['weather', [
            ['temperature', '16C (14.5-20.4C)', 'Cool.'],
            ['precipitation', '65% - rain yes', 'Drizzle.'],
            ['air', 'US AQI 30 - good', 'Good.'],
        ]], {}, '2026-10-13')
        for bad in ('16C (', 'rain yes', 'US AQI 30'):
            self.assertNotIn(bad, rendered)
        for good in ('16°C (14.5–20.4°C)', '65% – Rain likely', '30 – good'):
            self.assertIn(good, rendered)

    def test_aqi_strips_scale_prefix(self):
        self.assertEqual(native.weather_display('air', 'US AQI 30 - good'), '30 – good')
        self.assertEqual(native.weather_display('air', '31'), '31')


class DatedTitleTests(unittest.TestCase):
    def test_news_title_splits_and_badges(self):
        base, iso = native.split_dated_title('News — 2026-10-12')
        self.assertEqual((base, iso), ('News', '2026-10-12'))
        self.assertEqual(native.split_dated_title('Weather'), ('Weather', None))
        self.assertEqual(native.humanize_iso_date('2026-10-12'), '12 Oct')
        heading = native.heading_html('News — 2026-10-12')
        self.assertIn('section-date', heading)
        self.assertIn('12 Oct', heading)
        self.assertNotIn('News — 2026-10-12', heading)

    def test_edition_keeps_full_date_accessible_but_displays_badge(self):
        doc = {'v': 1, 'greeting': 'Hi', 'opening': 'Test', 'sections': [
            ['news', [['news', 'World', [['H', 'S', [['Src', 'https://example.org']]]]]]],
        ]}
        page = web.edition(doc, '2026-10-13', 'gm', {'gm': True})
        self.assertIn('aria-label="01: News — 2026-10-12"', page)
        self.assertIn('preview-date', page)
        self.assertIn('12 Oct', page)
        self.assertIn('section-date', page)


if __name__ == '__main__':
    unittest.main()
