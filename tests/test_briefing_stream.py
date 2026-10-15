"""Append-only preview safety, final-save binding and incremental transfer contracts."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT, FakeChamber
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.briefings import briefing_document as native
from goodmorning.briefings.briefing_stream import publish, load, require_final
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.runtime_files import runtime_lock


class StreamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'profile.md').write_text('secretary_language: English\ntimezone: Europe/London\ncity: London, GB\nnews_country: GB\n')
        (self.root / 'daily').mkdir()
        self.chamber = FakeChamber()
        self.app = BrowserApp(self.root, self.chamber, now=lambda: datetime(2026, 10, 10, 12, tzinfo=timezone.utc))
        self.identifier = 'a' * 32
        self.app.jobs['2026-10-10.gm'] = {'id': self.identifier, 'date': '2026-10-10', 'kind': 'gm', 'state': 'running', 'session': 'ses_fixture'}
        self.app.save_jobs()
        self.target = self.app.job_dir / (self.identifier + '.preview.json')
        self.plan = [['weather', 'Weather'], ['news', 'News — 2026-10-09'], ['nice-to-do', 'Optional project steps']]
        self.document = {'v': 1, 'greeting': 'Morning, take it gently.', 'opening': 'Let’s see what today needs.', 'sections': []}
        self.weather = ['weather', [['weather', [['temperature', '14°C', 'A jacket will help.']]]], 'Leave room for the weather.']
        self.news = ['news', [['news', 'World', [['A factual headline', 'A sourced account.', [['Publisher', 'https://example.org/story']]]]]], 'Keep the uncertainty in mind.']

    def initialize(self):
        return publish(self.root, self.identifier, deepcopy(self.document), self.plan)

    def append(self, section):
        self.document['sections'].append(section)
        return publish(self.root, self.identifier, deepcopy(self.document))

    def test_initialize_is_preview_not_a_saved_run(self):
        self.initialize()
        self.assertEqual(load(self.target)['document']['sections'], [])
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list((self.root / 'daily').iterdir()), [])
        with self.assertRaises(ValueError): native.parse(json.dumps(self.document))

    def test_top_down_rejects_wrong_type_without_changing_checkpoint(self):
        self.initialize()
        original = self.target.read_bytes()
        with self.assertRaises(ValueError): self.append(self.news)
        self.assertEqual(self.target.read_bytes(), original)

    def test_rejects_title_mismatch_and_multiple_new_sections(self):
        self.initialize()
        for sections in ([['weather', [['p', 'Weather detail']], '', 'Wrong title']], [self.weather, self.news]):
            document = {**self.document, 'sections': sections}
            with self.assertRaises(ValueError): publish(self.root, self.identifier, document)
        self.assertEqual(load(self.target)['outcomes'], [])

    def test_published_content_and_header_are_immutable(self):
        self.initialize(); self.append(self.weather)
        original = self.target.read_bytes()
        for field in ('greeting', 'opening', 'lang', 'sections'):
            document = deepcopy(self.document)
            if field == 'sections': document['sections'][0][2] = 'Changed note'
            else: document[field] = 'Changed' if field != 'lang' else 'zh'
            with self.assertRaises(ValueError): publish(self.root, self.identifier, document)
        with self.assertRaises(ValueError): publish(self.root, self.identifier, deepcopy(self.document), list(reversed(self.plan)))
        self.assertEqual(self.target.read_bytes(), original)

    def test_skip_optional_then_publish_closing_and_bind_final_save(self):
        self.initialize(); self.append(self.weather); self.append(self.news)
        with self.assertRaises(ValueError): require_final(self.root, self.identifier, '2026-10-10', 'gm', 'ses_fixture', self.document)
        publish(self.root, self.identifier, skip=True)
        self.document['closing'] = 'Take care.'
        publish(self.root, self.identifier, deepcopy(self.document))
        require_final(self.root, self.identifier, '2026-10-10', 'gm', 'ses_fixture', self.document)
        for date, kind, session in [('2026-10-09', 'gm', 'ses_fixture'), ('2026-10-10', 'gn', 'ses_fixture'), ('2026-10-10', 'gm', 'ses_other')]:
            with self.assertRaises(ValueError): require_final(self.root, self.identifier, date, kind, session, self.document)
        changed = deepcopy(self.document); changed['closing'] = 'Changed'
        with self.assertRaises(ValueError): require_final(self.root, self.identifier, '2026-10-10', 'gm', 'ses_fixture', changed)

    def test_no_early_closing_or_empty_initial_plan(self):
        for plan, document in [([], self.document), (self.plan, {**self.document, 'closing': 'Early closing'})]:
            with self.assertRaises(ValueError): publish(self.root, self.identifier, document, plan)
        self.assertFalse(self.target.exists())

    def test_idempotent_publication_does_not_advance(self):
        self.initialize(); self.append(self.weather)
        revision = self.app.preview(self.identifier)['revision']
        publish(self.root, self.identifier, deepcopy(self.document))
        self.assertEqual(load(self.target)['outcomes'], ['ready'])
        self.assertEqual(self.app.preview(self.identifier)['revision'], revision)

    def test_image_manifest_changes_preview_revision_without_changing_published_text(self):
        self.initialize();self.append(self.weather);self.append(self.news)
        before=self.target.read_bytes();preview=self.app.preview(self.identifier)
        cache=self.root/'browser-images/2026-10-10';cache.mkdir(parents=True)
        (cache/'manifest.json').write_text('{}')
        updated=self.app.preview(self.identifier,0)
        self.assertNotEqual(updated['revision'],preview['revision'])
        self.assertNotEqual(updated['image_revision'],preview['image_revision'])
        self.assertEqual(self.app.status(self.identifier)['preview_revision'],updated['revision'])
        self.assertEqual(self.target.read_bytes(),before)

    def test_published_image_urls_are_root_relative_on_all_preview_routes(self):
        self.initialize();self.append(self.weather);self.append(self.news)
        url=native.news_urls(load(self.target)['document'])[0]
        with patch('goodmorning.web.briefing_server.cached_previews',return_value=({url:{
                'src':'media/'+'a'*64+'.webp','status':'cached','alt':'Publisher preview'}},{})):
            self.assertIn('src="/media/'+'a'*64+'.webp"',str(self.app.preview(self.identifier)))

    def test_partial_is_readable_while_waiting_and_stopped_not_ready(self):
        self.initialize(); self.append(self.weather)
        self.assertEqual(self.app.status(self.identifier)['state'], 'waiting')
        self.assertIn('14°C', self.app.preview(self.identifier)['changes'][0]['html'])
        self.chamber.forms = []; self.chamber.permissions = []; self.chamber.busy = False
        self.assertEqual(self.app.status(self.identifier)['state'], 'stopped')
        self.assertTrue(self.target.exists())
        self.assertFalse(native.source_path(self.root, '2026-10-10', 'gm').exists())

    def test_upstream_outage_keeps_preview_available_after_refresh(self):
        self.initialize(); self.append(self.weather)
        def unavailable(_):
            raise TimeoutError('Mock outage')
        self.chamber.pending = unavailable
        app = BrowserApp(self.root, self.chamber, now=self.app.now)
        result = app.status(self.identifier)
        self.assertEqual(result['state'], 'uncertain')
        self.assertIn('preview_revision', result)
        self.assertIn('14°C', app.preview(self.identifier)['changes'][0]['html'])
        self.assertEqual(self.chamber.calls, [])

    def test_incremental_payload_does_not_retransfer_completed_sections(self):
        self.initialize(); self.append(self.weather)
        first = self.app.preview(self.identifier)
        self.assertIn('sections', first)
        self.append(self.news)
        second = self.app.preview(self.identifier, after=1)
        self.assertNotIn('sections', second)
        self.assertEqual([item['index'] for item in second['changes']], [1])
        self.assertNotIn('14°C', json.dumps(second, ensure_ascii=False))
        self.assertEqual(self.app.preview(self.identifier, after=2)['changes'], [])
        with self.assertRaises(ValueError): self.app.preview(self.identifier, after=4)

    def test_refresh_and_rollover_restore_owned_preview_without_new_session(self):
        self.initialize(); self.append(self.weather)
        app = BrowserApp(self.root, self.chamber, now=lambda: datetime(2026, 10, 11, 12, tzinfo=timezone.utc))
        self.assertEqual(app.preview(self.identifier)['changes'][0]['state'], 'ready')
        self.assertIn('generation-desk', app.page('2026-10-10', 'gm', True).decode())
        self.assertNotIn('id="generate"', app.page('2026-10-10', 'gm', True).decode())
        self.assertEqual(self.chamber.calls, [])

    def test_multiple_same_type_translated_sections_keep_separate_notes(self):
        self.plan = [['news', '昨日新闻'], ['news', '今日最新']]
        self.initialize()
        for title, note in [('昨日新闻', '第一条评述'), ('今日最新', '第二条评述')]:
            self.append(['news', [['p', '材料缺失，需要保留说明。']], note, title])
        changes = self.app.preview(self.identifier)['changes']
        self.assertIn('第一条评述', changes[0]['html'])
        self.assertIn('第二条评述', changes[1]['html'])

    def test_escaped_agent_text_and_no_automatic_publisher_fetch(self):
        self.initialize()
        self.append(['weather', [['p', '<script>alert(1)</script>']], '<img src=x>'])
        markup = self.app.preview(self.identifier)['changes'][0]['html']
        self.assertIn('&lt;script&gt;', markup)
        self.assertNotIn('<script>', markup)
        self.assertFalse((self.root / 'browser-images').exists())

    def test_symlinks_unknown_jobs_and_malformed_checkpoints_are_preserved(self):
        with self.assertRaises(ValueError): publish(self.root, 'b' * 32, self.document, self.plan)
        self.target.symlink_to(self.root / 'profile.md')
        with self.assertRaises(ValueError): self.initialize()
        self.target.unlink()
        self.target.write_text('{broken')
        self.assertIn('preview_error', self.app.status(self.identifier))
        with self.assertRaises(ValueError): self.initialize()
        self.assertEqual(self.target.read_text(), '{broken')

    def test_rejects_oversized_checkpoint_and_draft(self):
        self.initialize()
        self.target.write_bytes(b'x' * 180001)
        with self.assertRaises(ValueError): load(self.target)
        self.target.unlink()
        self.initialize()
        large = {**self.document, 'sections': [['weather', [['p', 'x' * 5000] for _ in range(31)]]]}
        with self.assertRaisesRegex(ValueError, 'native size limit'): publish(self.root, self.identifier, large)

    def test_invalid_citations_do_not_replace_the_prior_checkpoint(self):
        self.initialize(); self.append(self.weather)
        original = self.target.read_bytes()
        bad = deepcopy(self.news); bad[1][0][2][0][2] = [['Unsafe', 'javascript:alert(1)']]
        with self.assertRaises(ValueError): self.append(bad)
        self.assertEqual(self.target.read_bytes(), original)

    def test_unmatched_saved_snapshot_is_not_ready_and_preview_is_preserved(self):
        self.initialize(); self.append(self.weather)
        publish(self.root, self.identifier, skip=True); publish(self.root, self.identifier, skip=True)
        changed = deepcopy(self.document); changed['opening'] = 'Changed opening'
        (self.root / 'daily/2026-10-10.gm.json').write_text(native.encode(changed))
        self.chamber.forms = []; self.chamber.permissions = []; self.chamber.busy = False
        self.assertEqual(self.app.status(self.identifier)['state'], 'stopped')
        self.assertTrue(self.target.exists())

    def test_cli_restricts_draft_and_plan_paths_to_selected_runtime(self):
        self.initialize()
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts/goodmorning.py'), 'stream', '--secretary-dir', str(self.root), '--job', self.identifier]
        outside = self.root.parent / (self.root.name + '-outside.json')
        outside.write_text(json.dumps(self.document)); self.addCleanup(outside.unlink)
        result = subprocess.run([*command, '--answer-file', str(outside)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('inside the selected runtime', result.stdout)
        draft = self.root / 'draft.json'; draft.write_text(json.dumps(self.document))
        result = subprocess.run([*command, '--answer-file', str(draft), '--plan-file', str(outside)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('inside the selected runtime', result.stdout)

    def test_final_save_guard_and_successful_cleanup(self):
        self.initialize(); self.append(self.weather)
        draft = self.root / 'draft.json'
        def save():
            draft.write_text(json.dumps(self.document))
            return subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts/goodmorning.py'), 'state', '--secretary-dir', str(self.root), '--today', '2026-10-10', '--mark-gm', '--session', 'ses_fixture', '--browser-job', self.identifier, '--answer-file', str(draft), '--json'], capture_output=True, text=True)
        result = save()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)['error'], 'briefing_invalid')
        self.assertFalse((self.root / 'daily/2026-10-10.gm.json').exists())
        self.append(self.news); publish(self.root, self.identifier, skip=True)
        with runtime_lock(self.app.job_dir, self.identifier + '.preview.lock'):
            result = save()
            self.assertEqual(json.loads(result.stdout)['error'], 'runtime_busy')
            self.assertFalse((self.root / 'daily/2026-10-10.gm.json').exists())
        result = save(); self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.chamber.forms = []; self.chamber.permissions = []; self.chamber.busy = False
        self.assertEqual(self.app.status(self.identifier)['state'], 'ready')
        self.assertFalse(self.target.exists())
        self.assertEqual(native.parse((self.root / 'daily/2026-10-10.gm.json').read_text()), self.document)
        self.assertFalse(list((self.root / 'daily').glob('*.gm.md')))
        self.assertFalse((self.root / 'browser').exists())


if __name__ == '__main__':
    unittest.main()
