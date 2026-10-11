"""Skill discovery and one synthetic capture-to-briefing workflow."""
import contextlib
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from benchmarks.reply_templates import fixtures, render
from goodmorning.calendar.secretary_calendar import main as calendar_main
from goodmorning.news.news_reports import ReportStore, context_key
from goodmorning.records.inbox_store import InboxStore, initialize
from goodmorning.records.state import main as state_main, scan_inbox


class SkillTests(unittest.TestCase):
    def test_discovery_and_workflow_references(self):
        entry = (ROOT / 'skill-source/goodmorning.md').read_text()
        self.assertIn('name: goodmorning', entry)
        self.assertEqual(list(ROOT.glob('**/SKILL.md')), [])
        for kind in ('gm', 'gn', 'eureka', 'todo', 'secretary'):
            path = 'docs/workflows/' + kind + '.md'
            self.assertIn(path, entry)
            text = (ROOT / path).read_text()
            self.assertRegex(text, rf'^---\nname: {kind}\ndescription: .+')
            for reference in re.findall(r'`((?:docs|templates)/[^`]+\.md)`', text):
                self.assertTrue((ROOT / reference).is_file(), reference)

    def test_capture_morning_delivery_and_night_records(self):
        with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as directory:
            root = Path(directory)
            (root / 'daily').mkdir()
            sources = {'feeds': [], 'countries': {'US': [
                {'name':'Synthetic feed', 'url':'https://example.invalid/feed', 'section':'national'}]}}
            source_path = root / 'news_sources.json'
            source_path.write_text(json.dumps(sources))
            (root / 'profile.md').write_text(f'secretary_language: English\ncity: London, GB\ntimezone: UTC\nnews_country: US\nnews_sources_path: {source_path}\n')

            def call(function, arguments):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = function(['--secretary-dir', directory, *arguments])
                self.assertEqual(code, 0, output.getvalue())
                return json.loads(output.getvalue())

            initialize(root)
            with contextlib.ExitStack() as stack:
                inbox = InboxStore(root, write=True); stack.callback(inbox.close)
                raw = 'Try a synthetic demo\nKeep my exact wording.'
                item = inbox.mutate('add', {'kind':'idea', 'raw':raw}, 'ses_fixture', 'capture', '2026-10-09T07:00:00+00:00')
                self.assertEqual(inbox.text(item['id'])['text'], raw)
                call(calendar_main, ['--init', '--timezone', 'UTC'])
                event = {'subject':'Demo review', 'start':'2026-10-10T10:00:00+00:00',
                         'end':'2026-10-10T11:00:00+00:00', 'location':'Room A', 'notes':'Bring slides'}
                call(calendar_main, ['--add', '--event-json', json.dumps(event), '--actor', 'ses_fixture'])
                schedule = call(calendar_main, ['--from', '2026-10-10', '--days', '1', '--timezone', 'UTC', '--json', '--details'])
                self.assertEqual(schedule[0]['notes'], 'Bring slides')
                report, morning, night = fixtures()
                store = ReportStore(directory, create=True); stack.callback(store.close)
                context = context_key('UTC', 'US', sources)
                row = store.save(context, report)
                daily = root / 'daily/2026-10-09.md'
                for kind, document in (('gm', morning), ('gn', night)):
                    reply = render(kind, document)
                    with patch.object(sys, 'stdin', io.StringIO(reply)):
                        receipt = call(state_main, ['--today', '2026-10-09', '--mark-'+kind,
                                                   '--session', 'ses_fixture', '--answer-stdin', '--json'])
                    self.assertTrue(receipt['ran'])
                    self.assertEqual((root / receipt['answer_file']).read_text(), reply)
                    if kind == 'gm':
                        self.assertNotIn('- [x]', daily.read_text())
                        self.assertEqual(store.get(context, report['date'])['status'], 'collected')
                        store.acknowledge(context, report['date'], row['report_id'], 'ses_fixture')
                        daily.write_text(daily.read_text().replace('- [ ] Demo: draft outline', '- [x] Demo: draft outline')
                                         + '\n## feedback\n- User confirmed outline complete; reading not done.\n')
                summary = call(state_main, ['--today', '2026-10-09', '--check', '--json'])
                self.assertTrue(summary['gm_today']['ran'] and summary['gn_today']['ran'])
                self.assertTrue(summary['sections_today']['feedback'])
                self.assertIn('- [ ] Demo: optional reading', daily.read_text())
                self.assertEqual(scan_inbox(directory)['pending'], 1)
                self.assertEqual(summary['news']['delivered'], 1)


if __name__ == '__main__':
    unittest.main()
