"""Chat-only Markdown dependency and prompt contracts; no private records."""
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.web.briefing_chat import page
from goodmorning.web.briefing_resources import Resources

ROOT = Path(__file__).resolve().parents[1]


class MarkdownTests(unittest.TestCase):
    def test_pinned_parser_and_license_are_unmodified(self):
        for name, expected in {
            'assets/web/marked.js': 'b82b9334406d8bdd16b6236c08de1cb65b2a859873ca9503d9cc0b292ca3c12a',
            'vendor/marked/LICENSE': '8e3a3f82f59a60958f56ca08f445647c32a4733dc7ca6c2c46f6eb898471ab9c',
        }.items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), expected)

    def test_local_immutable_scripts_load_before_chat(self):
        resources = Resources(ROOT / 'assets/web')
        html = resources.rewrite(page('synthetic', True, True))
        urls = [resources.urls[name] for name in ('marked.js', 'markdown.js', 'chat.js')]
        positions = [html.index('src="' + url + '"') for url in urls]
        self.assertEqual(positions, sorted(positions))
        for url in urls:
            self.assertEqual(resources.paths[url].mime, 'text/javascript')
        self.assertNotIn('https://', html)

    def test_markdown_guidance_does_not_change_native_briefing_contract(self):
        core = (ROOT / 'docs/core-rules.md').read_text()
        voice = (ROOT / 'docs/reply-voice.md').read_text()
        self.assertIn('use Markdown only', core)
        self.assertIn('Keep simple confirmations simple', voice)
        self.assertIn('not Markdown', voice)
        from goodmorning.briefings import briefing_document as native
        doc = {'v': 2, 'greeting': 'Hello.', 'opening': 'Plain text.', 'sections': [
            ['tasks', [['actions', [['task_'+'a'*16, 1, '', '', 'open', '**Literal title**', '']]]]]]}
        rendered = native.render_block(doc['sections'][0][1][0], {})
        self.assertIn('**Literal title**', rendered)
        self.assertNotIn('<strong>Literal title</strong>', rendered)
        self.assertEqual(native.parse(native.encode(doc)), doc)


if __name__ == '__main__':
    unittest.main()
