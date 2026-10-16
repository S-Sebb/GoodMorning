"""Quick chat appears on desk pages and shares the Secretary page's tab workspace."""
import html
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

from support import TEMP_ROOT, FakeChamber
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web import schedule


def scope(page, element):
    config = re.search(r'id="' + element + r'"[^>]*data-config="([^"]+)"', page)
    return json.loads(html.unescape(config[1]))['workspaceScope']


class QuickChatPageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'profile.md').write_text('secretary_language: English\ncity: London\ntimezone: Europe/London\nnews_country: GB\n')
        self.app = BrowserApp(self.root, FakeChamber())

    def test_desk_pages_share_the_secretary_workspace_and_load_helpers_once(self):
        chat = self.app.chat_page().decode()
        self.assertNotIn('id="quick-chat"', chat)
        day = self.app.today()
        pages = {'gm': self.app.page(day, 'gm', False).decode(), 'gn': self.app.page(day, 'gn', True).decode(),
                 'schedule': schedule.page(self.app, 0).decode()}
        for name, page in pages.items():
            with self.subTest(name):
                self.assertEqual(page.count('id="quick-chat"'), 1)
                self.assertEqual(scope(page, 'quick-chat'), scope(chat, 'chat-config'))
                scripts = re.findall(r'<script src="/assets/[a-f0-9]{64}/([a-z.-]+)"', page)
                for helper in ('questions.js', 'marked.js', 'markdown.js'):
                    self.assertEqual(scripts.count(helper), 1)
                    self.assertLess(scripts.index(helper), scripts.index('quick-chat.js'))
                self.assertIn('/quick-chat.css"', page)

    def test_setup_page_has_no_quick_chat(self):
        (self.root / 'profile.md').write_text('secretary_language: English\ntimezone: Europe/London\n')
        self.assertNotIn('id="quick-chat"', self.app.page(self.app.today(), 'gm', False).decode())


if __name__ == '__main__':
    unittest.main()
