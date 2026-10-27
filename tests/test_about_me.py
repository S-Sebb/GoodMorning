import html
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from urllib.error import HTTPError

from support import TEMP_ROOT, GatewayFixture, HTTPFixture

from goodmorning.runtime_files import profile_fields, set_profile_fields
from goodmorning.web import about_me
from goodmorning.web.briefing_server import BrowserApp

PROFILE = '''# Secretary profile

secretary_name: "Mochi"
user_name: ""
city: "Shanghai, CN"
timezone: "Asia/Shanghai"
news_country: "CN"
news_additional_countries: "JP"
anime_updates: "false"
anime_source: "anilist"
anime_account: "samwatches"
anime_titles: "1, 2"
game_sales: "false"
game_country: ""
stock_holdings: ""

## Project roots

- Thesis | /home/sam/thesis | local | read

## Setup rules

- Keep credentials in the environment, never in this file.
'''


class AboutMeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'profile.md').write_text(PROFILE)
        (self.root / 'calendar.config.json').write_text(json.dumps({'ics_url': 'https://calendar.example.test/private-key.ics'}))
        self.app = BrowserApp(self.root)

    def test_only_the_changed_line_is_rewritten_and_missing_fields_join_the_field_block(self):
        set_profile_fields(self.root, {'user_name': 'Sam', 'weekly_letter': 'false'})
        text = (self.root / 'profile.md').read_text()
        self.assertEqual(text, PROFILE.replace('user_name: ""', 'user_name: "Sam"')
                         .replace('stock_holdings: ""\n', 'stock_holdings: ""\nweekly_letter: "false"\n'))
        self.assertEqual(profile_fields(self.root)['user_name'], 'Sam')

    def test_unsafe_values_and_fields_change_nothing(self):
        for values in ({'secretary_name': 'x' * 31}, {'secretary_name': '!!'}, {'industry': 'two\nlines'},
                       {'industry': 'x' * 301}, {'City': 'Paris'}, {'city: "Paris"\nx': 'y'}):
            with self.assertRaises(ValueError):
                set_profile_fields(self.root, values)
        self.assertEqual((self.root / 'profile.md').read_text(), PROFILE)
        target = self.root / 'elsewhere.md'
        target.write_text(PROFILE)
        (self.root / 'profile.md').unlink()
        os.symlink(target, self.root / 'profile.md')
        with self.assertRaises(ValueError):
            set_profile_fields(self.root, {'industry': 'Design'})
        self.assertEqual(target.read_text(), PROFILE)

    def test_the_page_saves_text_fields_and_leaves_checked_settings_to_chat(self):
        self.assertEqual(about_me.save(self.app, {'field': 'industry', 'value': ' Education '}), {'field': 'industry', 'value': 'Education'})
        with self.assertRaises(about_me.Invalid) as error:
            about_me.save(self.app, {'field': 'secretary_name', 'value': 'x' * 31})
        self.assertEqual(str(error.exception), 'Use up to 30 characters.')
        for body in ({'field': 'city', 'value': 'Paris, FR'}, {'field': 'timezone', 'value': 'Europe/Paris'},
                     {'field': 'anime_titles', 'value': '9'}, {'field': 'industry'}, {'field': 'industry', 'value': 3}):
            with self.assertRaises(ValueError):
                about_me.save(self.app, body)
        fields = profile_fields(self.root)
        self.assertEqual((fields['city'], fields['timezone'], fields['anime_titles']), ('Shanghai, CN', 'Asia/Shanghai', '1, 2'))

    def test_public_holidays_are_picked_from_listed_regions(self):
        self.assertIn('Mochi doesn’t know yet', self.app_page().split('data-field="holiday_countries"')[1][:400])
        self.assertEqual(about_me.save(self.app, {'field': 'holiday_countries', 'value': 'gb-sct, CN'}),
                         {'field': 'holiday_countries', 'value': 'GB-SCT, CN'})
        self.assertIn('data-holidays="GB-SCT,CN">United Kingdom — Scotland, China<', self.app_page())
        self.assertEqual(about_me.save(self.app, {'field': 'holiday_countries', 'value': ''})['value'], 'none')
        self.assertIn('No public holidays', self.app_page())
        with self.assertRaises(ValueError):
            about_me.save(self.app, {'field': 'holiday_countries', 'value': 'GB'})
        self.assertEqual(profile_fields(self.root)['holiday_countries'], 'none')

    def test_extras_switch_back_on_only_after_chat_set_them_up(self):
        self.assertEqual(about_me.save(self.app, {'field': 'anime_updates', 'value': 'true'})['value'], 'true')
        self.assertEqual(about_me.save(self.app, {'field': 'weekly_letter', 'value': 'false'})['value'], 'false')
        for key in ('game_sales', 'stock_report'):
            with self.assertRaises(about_me.Invalid):
                about_me.save(self.app, {'field': key, 'value': 'true'})
        with self.assertRaises(ValueError):
            about_me.save(self.app, {'field': 'anime_updates', 'value': 'yes'})
        fields = profile_fields(self.root)
        self.assertEqual((fields['anime_updates'], fields['anime_titles'], fields['game_sales']), ('true', '1, 2', 'false'))

    def test_the_page_shows_the_profile_but_never_private_links_ids_or_paths(self):
        page = self.app_page()
        for text in ('Mochi', 'Shanghai, CN', 'data-countries="CN,JP"', 'AniList', 'Your watching list and 2 more shows',
                     'Connected', 'Thesis', 'data-quick-ask="I’d like to change my city."'):
            self.assertIn(text, page)
        for secret in ('private-key', 'samwatches', '/home/sam', 'read'):
            self.assertNotIn(secret, re.sub(r'<[^>]+>', ' ', page.split('<main', 1)[1]))
        extras = page[page.index('id="about-extras"'):page.index('id="about-calendar"')]
        self.assertEqual(extras.count('class="about-switch"'), 2)  # Episodes and the weekly letter; games and stocks were never set up.
        self.assertIn('Ask Mochi to change this', page)
        set_profile_fields(self.root, {'secretary_name': ''})
        page = self.app_page()
        self.assertIn('Your secretary’s notes about you', page)
        self.assertIn('Ask your secretary to change this', page)
        self.assertIn('Your secretary doesn’t know yet', page)

    def app_page(self):
        class Resources:
            urls = {}
            def rewrite(self, text): return text
        self.app.resources = Resources()
        return html.unescape(about_me.page(self.app).decode())


class AboutMeHTTPTests(HTTPFixture):
    def test_saving_needs_this_viewer_csrf_and_origin(self):
        for headers in ({'X-Briefing-CSRF': 'wrong'}, {'Origin': 'https://evil.example'}):
            with self.assertRaises(HTTPError) as error:
                self.request('/api/about-me', {'field': 'industry', 'value': 'Forged'}, headers)
            self.assertEqual(error.exception.code, 403)
            error.exception.close()
        self.assertNotIn('industry', profile_fields(self.root))
        self.assertEqual(self.request('/api/about-me', {'field': 'industry', 'value': 'Design'}), {'field': 'industry', 'value': 'Design'})
        with self.assertRaises(HTTPError) as error:
            self.request('/api/about-me', {'field': 'user_name', 'value': '!!'})
        self.assertEqual((error.exception.code, json.load(error.exception)['error']), (400, 'Include at least one letter or number.'))
        error.exception.close()


class AboutMeGatewayTests(GatewayFixture):
    def test_the_gateway_forwards_the_page_and_checked_saves_to_the_signed_in_account(self):
        self.permanent()
        status, _, page = self.request('/about-me')
        self.assertEqual(status, 200)
        self.assertIn(b'id="about-me-link"', page)
        status, _, _ = self.request('/api/about-me', {'field': 'industry', 'value': 'Design'}, headers={'X-Briefing-CSRF': 'wrong'})
        self.assertEqual(status, 403)
        status, _, _ = self.request('/api/about-me', {'field': 'industry', 'value': 'Design'})
        self.assertEqual(status, 202)
        self.assertEqual([path for path, _ in self.received], ['/about-me', '/api/about-me'])


if __name__ == '__main__':
    unittest.main()
