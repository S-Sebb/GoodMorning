"""Source layout and CLI migration contracts; no personal data or network."""
import ast
from contextlib import redirect_stderr
import io
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from goodmorning.cli import COMMANDS, main
from goodmorning.paths import ROOT as PUBLIC_ROOT, WEB_ASSETS
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.briefings import briefing_document as native
from goodmorning.web.briefing_resources import ICON_TYPES
import tempfile


class StructureTests(unittest.TestCase):
    def test_only_two_public_command_entry_points_remain(self):
        self.assertEqual({p.name for p in (ROOT / 'scripts').iterdir() if p.is_file()},
                         {'goodmorning.py', 'projects.mjs'})
        self.assertEqual(PUBLIC_ROOT, ROOT)
        self.assertTrue((WEB_ASSETS / 'edition.html').is_file())

    def test_page_icons_work_for_setup_waiting_saved_archive_and_chat(self):
        with tempfile.TemporaryDirectory(dir='/tmp/opencode') as directory:
            root=Path(directory)
            (root/'profile.md').write_text('timezone: UTC\n')
            app=BrowserApp(root)
            for kind in ('gm','gn'):
                for page in (app.initialization_page(kind),app.page(app.today(),kind,False)):
                    self.assertIn(('/icons/'+kind+'.svg').encode(),page)
                    self.assertNotIn(b'href="icons/',page)
            (root/'profile.md').write_text('secretary_language: English\ntimezone: UTC\ncity: London, GB\nnews_country: GB\n')
            (root/'daily').mkdir()
            document={'v':1,'greeting':'Hello','opening':'Synthetic','sections':[['notes',[['p','Example']]]]}
            for kind in ('gm','gn'):
                self.assertIn(('/icons/'+kind+'.svg').encode(),app.page(app.today(),kind,False))
                (root/'daily'/f'{app.today()}.{kind}.json').write_text(native.encode(document))
                for pinned in (False,True):
                    page=app.page(app.today(),kind,pinned)
                    self.assertIn(('/icons/'+kind+'.svg').encode(),page)
                    self.assertNotIn(b'href="icons/',page)
            self.assertIn(b'/icons/secretary.svg',app.chat_page())
            self.assertEqual(len(ICON_TYPES),6)

    def test_source_imports_do_not_depend_on_old_top_level_modules(self):
        legacy = {p.stem for p in (ROOT / 'src/goodmorning').rglob('*.py')}
        for path in (ROOT / 'src/goodmorning').rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom) and not node.level:
                    self.assertNotIn((node.module or '').split('.')[0], legacy, str(path))
                elif isinstance(node, ast.Import):
                    for name in node.names:
                        self.assertNotIn(name.name.split('.')[0], legacy, str(path))

    def test_invalid_command_stops_before_any_helper(self):
        original = sys.argv
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(['missing'])
        self.assertEqual(raised.exception.code, 2)
        self.assertIs(sys.argv, original)

    def test_help_is_lazy_and_needs_no_optional_rendering_dependencies(self):
        code = ('import sys; sys.path.insert(0, sys.argv[1]); '
                'from goodmorning.cli import main; '
                '\ntry: main(["--help"])\nexcept SystemExit: pass\n'
                'assert "markdown" not in sys.modules; assert "PIL" not in sys.modules')
        result = subprocess.run([sys.executable, '-B', '-c', code, str(ROOT / 'src')],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in COMMANDS:
            self.assertIn(command, result.stdout)

    def test_removed_image_plugin_is_not_referenced_by_active_instructions(self):
        self.assertFalse((ROOT / 'plugins/briefing-delivery').is_dir())
        for path in [ROOT / 'README.md', *list((ROOT / 'docs').glob('*.md')),
                     *list((ROOT / 'docs/workflows').glob('*.md')),
                     *list((ROOT / 'templates').glob('*.md'))]:
            for obsolete in ('briefing_cards', 'plugins/briefing-delivery', 'docs/image-delivery.md'):
                self.assertNotIn(obsolete, path.read_text(), str(path))
