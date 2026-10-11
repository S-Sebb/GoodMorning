"""Removed interfaces stay unavailable; initialized profiles remain unchanged."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.cli import COMMANDS
from goodmorning.briefings import briefing_document, briefing_web
from goodmorning.calendar.secretary_calendar import main as calendar_main
from goodmorning.news.news import load_sources
from goodmorning.records import inbox, inbox_store, state, workflow
from goodmorning.setup_check import profile_status


class NativeOnlyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_removed_commands_flags_and_renderers_are_unavailable(self):
        self.assertFalse({'presentation', 'progress'} & COMMANDS.keys())
        for function, arguments in [(inbox.main, ['--migrate']), (inbox.main, ['--list', '--filter', 'pending']),
                                    (calendar_main, ['--migrate-md', 'unused']), (state.main, ['--check', '--briefing-json'])]:
            with self.subTest(arguments=arguments), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                function(arguments)
            self.assertEqual(error.exception.code, 2)
        self.assertFalse(hasattr(inbox_store, 'migrate'))
        for name in ('markdown_html', 'split_briefing', 'section_type', 'serve'):
            self.assertFalse(hasattr(briefing_web, name))

    def test_text_sources_are_ignored_and_preserved(self):
        (self.root / 'daily').mkdir()
        original = self.root / 'daily/2026-10-10.gm.md'
        original.write_text('Unrelated private text.\n')
        self.assertEqual(briefing_document.source_path(self.root, '2026-10-10', 'gm').suffix, '.json')
        with self.assertRaises(ValueError):
            briefing_web.build(self.root, '2026-10-10')
        archived = self.root / 'inbox.md'; archived.write_text('- 2026-10-10 | Saved text | pending |\n')
        self.assertEqual(state.scan_inbox(str(self.root))['total'], 0)
        inbox_store.initialize(self.root)
        self.assertEqual(archived.read_text(), '- 2026-10-10 | Saved text | pending |\n')
        self.assertEqual(original.read_text(), 'Unrelated private text.\n')

    def test_preparation_does_not_reset_initialized_modified_profile(self):
        profile = self.root / 'profile.md'
        saved = 'secretary_language: English\ncity: London, GB\ntimezone: UTC\nnews_country: GB\nsecretary_tone: My modified tone\ncustom_preference: Keep this exactly\n'
        profile.write_text(saved)
        result = workflow.prepare(self.root, 'todo', '2026-10-10')
        self.assertTrue(result['ready'])
        self.assertEqual(result['profile']['secretary_tone'], 'My modified tone')
        self.assertEqual(profile.read_bytes(), saved.encode())

    def test_obsolete_news_policy_is_rejected(self):
        path = self.root / 'sources.json'
        path.write_text(json.dumps({'feeds': [], 'ranking_policy': 'legacy'}))
        with self.assertRaisesRegex(ValueError, 'unsupported ranking policy'):
            load_sources(path)

    def test_profile_cannot_bypass_required_language_by_omitting_the_key(self):
        (self.root / 'profile.md').write_text('city: London, GB\ntimezone: UTC\nnews_country: GB\n')
        result = profile_status(self.root, {'city': 'London, GB', 'timezone': 'UTC', 'news_country': 'GB'})
        self.assertFalse(result['profile_ready'])
        self.assertEqual(result['missing_fields'], ['secretary_language'])
