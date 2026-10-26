"""Weekly letters: the code-built week, Sunday's evening section that saves it once, and the Letters pages."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

from support import TEMP_ROOT, offline_provider_reads
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.briefings import briefing_document as native
from goodmorning.briefings.briefing_job import act
from goodmorning.briefings.briefing_preflight import answer, initialize as preflight
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.records import letters
from goodmorning.records.custom_store import CustomStore
from goodmorning.records.inbox_store import InboxStore, initialize
from goodmorning.records.task_store import TaskStore
from goodmorning.security.briefing_gateway import GET_ROUTES, PAGE_ROUTES
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web import letters as pages

WEEK, SUNDAY = '2026-10-19', '2026-10-25'
NIGHT = datetime(2026, 10, 25, 13, tzinfo=timezone.utc)  # 21:00 in Shanghai
ZONE = 'Asia/Shanghai'
WORDS = {'opening': 'You wrapped up the chapter 2 outline and kept stretching going three weeks running.',
         'signoff': 'Rest up, and see you next Sunday.'}


def visible(markup):
    return ' '.join(re.sub(r'<[^>]+>', ' ', markup).split())


def stamp(day, hour=10):
    return f'{day}T{hour:02d}:00:00+08:00'


def records(root):
    """One synthetic week: work finished this week and last, habits, ideas and next week's plans."""
    initialize(root)
    inbox = InboxStore(root, write=True)
    tasks = TaskStore(inbox)
    try:
        def add(key, fields, day='2026-10-12'):
            return inbox.mutate('add', {'kind': 'todo', 'raw': fields['title'], 'task': {'timezone': ZONE, **fields}},
                                'ses_synthetic', key, stamp(day))['task_id']

        def done(task, day, key, at=None):
            revision = tasks.show(task)['revision']
            tasks.mutate(task, revision, {'status': 'done', 'confirmed_completion': True}, 'ses_synthetic', 'done-' + key,
                         at or stamp(day, 21), day=day if at is None else None)

        done(add('outline', {'title': 'Draft chapter 2 outline', 'project': 'Thesis', 'planned_date': '2026-10-20'}), '2026-10-20', 'outline')
        done(add('figures', {'title': 'Send figures to Dr. Lee', 'project': 'Thesis', 'planned_date': '2026-10-15'}), '2026-10-15', 'figures')
        done(add('photo', {'title': 'Renew passport photo', 'project': 'Home'}), None, 'photo', at=stamp('2026-10-22'))
        plants = add('plants', {'title': 'Water the plants', 'repeat': {'weekdays': [0, 2, 4], 'start': '2026-10-12'}})
        for day in ('2026-10-14', '2026-10-19', '2026-10-21', '2026-10-23'):
            done(plants, day, 'plants-' + day)
        add('slides', {'title': 'Prepare slides', 'planned_date': '2026-10-27'})
        add('abstract', {'title': 'Submit abstract', 'due_date': '2026-10-28'})
        for key, raw, day in (('mia', 'Try a weekly review with Mia', '2026-10-21'), ('old', 'An idea from last week', '2026-10-14')):
            inbox.mutate('add', {'kind': 'idea', 'raw': raw}, 'ses_synthetic', key, stamp(day))
    finally:
        inbox.close()
    custom = CustomStore(root, write=True)
    try:
        for title, days in (('Stretching', ('2026-10-06', '2026-10-13', '2026-10-19', '2026-10-20', '2026-10-22', '2026-10-24')),
                            ('Reading', ('2026-10-07', '2026-10-21')), ('Running', ('2026-10-15',))):
            rule = custom.add({'title': title, 'timezone': ZONE, 'policy': {'base': 'weekdays', 'weekdays': [0, 1, 2, 3, 4, 5, 6],
                               'start': '2026-10-01', 'anchor': 'fixed', 'miss_policy': 'fixed'}}, 'ses_synthetic', title, stamp('2026-10-01'))['id']
            for revision, day in enumerate(days, 1):
                custom.report(rule, revision, {'status': 'done', 'confirmed_completion': True}, 'ses_synthetic', title + day, stamp(day, 22), day)
    finally:
        custom.close()
    calendar = CalendarStore(str(root / 'calendar.sqlite'))
    try:
        calendar.add({'subject': 'Group meeting', 'start': '2026-10-26T10:00:00+08:00', 'end': '2026-10-26T11:00:00+08:00'})
        calendar.add({'subject': 'Day out', 'start': '2026-10-30', 'end': '2026-10-31', 'all_day': True, 'timezone': ZONE})
        calendar.add({'subject': 'This week’s dentist', 'start': '2026-10-23T14:00:00+08:00', 'end': '2026-10-23T15:00:00+08:00'})
    finally:
        calendar.close()


class LetterTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        env = patch.dict(os.environ, {}, clear=True)
        env.start(); self.addCleanup(env.stop)
        offline_provider_reads(self)
        (self.root / 'profile.md').write_text(f'city: Shanghai, CN\ntimezone: {ZONE}\nnews_country: CN\nsecretary_language: English\n')
        (self.root / 'daily').mkdir()
        records(self.root)

    def job(self, identifier='c' * 32, day=SUNDAY):
        app = BrowserApp(self.root, now=lambda: NIGHT, preflight=True)
        job = {'id': identifier, 'date': day, 'kind': 'gn', 'state': 'preflight', 'session': 'ses_test'}
        app.jobs[day + '.gn'] = job; app.save_jobs()
        fields = preflight(self.root, job)['form']['fields']
        answer(self.root, job, {field['key']: {'completed': ['none'], 'details': 'No updates today'}.get(field['key'], []) for field in fields})
        job['state'] = 'running'; app.jobs[day + '.gn'] = job; app.save_jobs()
        return identifier

    def step(self, action, payload=None, identifier='c' * 32):
        return act(self.root, identifier, 'ses_test', action, payload)

    def reach_letter(self, identifier='c' * 32):
        self.step('init', {'greeting': 'Evening.', 'opening': 'Tonight’s review.'}, identifier)
        self.step('publish', {'position': 0, 'section': ['today', [['p', 'You shared no updates.']]]}, identifier)
        self.step('publish', {'position': 1, 'section': ['weather', [['p', 'Tomorrow’s weather is unavailable.']], '', 'Weather tomorrow']}, identifier)
        self.step('publish', {'position': 2, 'section': ['schedule', [['p', 'One appointment tomorrow.']]]}, identifier)
        self.step('skip', {'position': 3}, identifier)
        return self.step('skip', {'position': 4}, identifier)

    def test_the_week_comes_from_saved_records_only(self):
        self.assertEqual(letters.facts(self.root, WEEK, 'en'), {
            # Last week's figures and plant watering stay out; repeats are counted, projects keep their order.
            'finished': [['Thesis', [['Draft chapter 2 outline', 1]]], ['Home', [['Renew passport photo', 1]]],
                         ['', [['Water the plants', 3]]]],
            # Stretching has three weeks in a row; Reading's run restarted; Running had a quiet week and is left out.
            'habits': [['Stretching', 4, 3], ['Reading', 1, 1]],
            'ideas': ['Try a weekly review with Mia'],
            'next': {'events': [['2026-10-26', '10:00', 'Group meeting'], ['2026-10-30', '', 'Day out']],
                     'deadlines': [['2026-10-28', 'Submit abstract']], 'planned': 4, 'complete': True}})

    def test_sunday_evening_saves_the_letter_once_then_shows_its_notice(self):
        self.job()
        result = self.reach_letter()
        self.assertEqual(result['next']['section'], ['letter', 'Weekly letter'])
        self.assertEqual(result['next']['input'], {'position': 5, 'letter': {'opening': '…', 'signoff': '…'}})
        read = result['next']['results'][0]
        self.assertEqual((read['exit'], read['output']['saved'], read['output']['letter']['habits'][0]), (0, False, ['Stretching', 4, 3]))
        self.assertIn('Never mention unfinished work', result['next']['writing'])
        with self.assertRaisesRegex(ValueError, 'do not skip'):
            self.step('skip', {'position': 5})
        with self.assertRaisesRegex(ValueError, 'write the letter'):
            self.step('publish', {'position': 5})
        with self.assertRaisesRegex(ValueError, 'opening'):
            self.step('publish', {'position': 5, 'letter': {'opening': 'Hi'}})
        self.step('publish', {'position': 5, 'letter': WORDS})
        saved = letters.load(self.root, WEEK)
        self.assertEqual((saved['opening'], saved['lang'], letters.counts(saved)), (WORDS['opening'], 'en', [5, 2, 1]))
        # An identical retry reuses the published notice.
        self.assertTrue(self.step('publish', {'position': 5, 'letter': WORDS})['reused'])

        # This job stops before saving the briefing; the next job for the same Sunday keeps the first letter,
        # even after records change.
        before = (self.root / 'letters' / f'{WEEK}.json').read_text()
        inbox = InboxStore(self.root, write=True)
        try:
            inbox.mutate('add', {'kind': 'idea', 'raw': 'A late idea'}, 'ses_synthetic', 'late', stamp(SUNDAY, 22))
        finally:
            inbox.close()
        again = 'd' * 32
        self.job(again)
        result = self.reach_letter(again)
        self.assertEqual(result['next']['input'], {'position': 5})
        self.assertEqual(result['next']['results'][0]['output'], {'week': WEEK, 'saved': True, 'counts': [5, 2, 1]})
        self.step('publish', {'position': 5, 'letter': {'opening': 'Rewritten.', 'signoff': 'Bye.'}}, again)
        self.assertEqual((self.root / 'letters' / f'{WEEK}.json').read_text(), before)
        self.assertTrue(self.step('finish', {}, again)['saved'])
        document = json.loads((self.root / 'daily' / f'{SUNDAY}.gn.json').read_text())
        self.assertEqual(document['sections'][-1], ['letter', [['letter', WEEK, [5, 2, 1]]]])
        card = native.render_block(document['sections'][-1][1][0], {})
        self.assertIn('href="/letters/2026-10-19"', card)
        self.assertIn('5 things finished · 2 habits kept going · 1 new idea', visible(card))

    def test_unreadable_records_say_so_instead_of_promising_a_letter(self):
        self.job()
        self.reach_letter()
        with patch.object(letters, 'facts', side_effect=ValueError('setup_required')):
            self.step('publish', {'position': 5})
        preview = json.loads((self.root / 'browser-jobs' / ('c' * 32 + '.preview.json')).read_text())
        self.assertEqual(preview['document']['sections'][-1], ['letter', [['letter', WEEK, None]]])
        self.assertIsNone(letters.load(self.root, WEEK))
        self.assertIn('couldn’t be written', native.render_block(['letter', WEEK, None], {}))

    def test_only_sunday_evenings_carry_it_and_the_user_can_turn_it_off(self):
        def plan(identifier, day=SUNDAY):
            self.job(identifier, day)
            self.step('init', {'greeting': 'Evening.', 'opening': 'Tonight’s review.'}, identifier)
            return [tag for tag, _ in json.loads((self.root / 'browser-jobs' / (identifier + '.preview.json')).read_text())['plan']]
        self.assertNotIn('letter', plan('a' * 32, '2026-10-24'))
        (self.root / 'profile.md').write_text((self.root / 'profile.md').read_text() + 'weekly_letter: "false"\n')
        self.assertNotIn('letter', plan('b' * 32))

    def test_a_short_week_gets_its_opening_from_code(self):
        quiet = '2026-09-28'  # Before any saved record.
        output = io.StringIO()
        with patch.object(sys, 'argv', ['letter', '--secretary-dir', str(self.root), '--week', quiet]), redirect_stdout(output):
            letters.main()
        self.assertEqual(json.loads(output.getvalue())['opening'], 'This week’s letter is a short one.')
        with self.assertRaisesRegex(ValueError, 'write only'):
            letters.save(self.root, quiet, WORDS, 'zh-CN')
        saved = letters.save(self.root, quiet, {'signoff': '下周见。'}, 'zh-CN')
        self.assertEqual((saved['opening'], saved['signoff'], letters.counts(saved)), ('这周的信写得短一些。', '下周见。', [0, 0, 0]))

    def test_the_letters_page_opens_the_newest_letter_with_a_wheel_of_weeks(self):
        app = BrowserApp(self.root, now=lambda: NIGHT)
        self.assertIn('No letters yet', pages.page(app).decode())
        letters.save(self.root, '2026-10-12', {'opening': 'An earlier week.', 'signoff': 'Bye.'}, 'en')
        letters.save(self.root, WEEK, WORDS, 'en')
        newest = pages.page(app).decode()
        self.assertIn('<a href="/letters/2026-10-19" aria-current="page"><span class="wheel-range">Oct 19 – 25</span>', newest)
        self.assertIn('<a href="/letters/2026-10-12"><span class="wheel-range">Oct 12 – 18</span>', newest)
        letter = visible(newest)
        for text in ('No. 2', 'Latest', WORDS['opening'], 'Thesis', 'Draft chapter 2 outline', 'Water the plants ×3',
                     'Stretching 4 times this week 3 weeks in a row', 'Reading 1 time this week', 'Try a weekly review with Mia',
                     '10:00 Group meeting', 'All day Day out', 'Due Submit abstract', '4 tasks planned across the week', WORDS['signoff']):
            self.assertIn(text, letter)
        self.assertNotIn('Running', letter)
        earlier = visible(pages.page(app, '2026-10-12').decode())
        self.assertIn('No. 1', earlier)
        self.assertIn('An earlier week.', earlier)
        with self.assertRaises(ValueError):
            pages.page(app, '2026-10-05')
        (self.root / 'profile.md').write_text((self.root / 'profile.md').read_text() + 'weekly_letter: "false"\n')
        self.assertIn('Weekly letters are turned off', pages.page(app).decode())
        for path in ('/letters', '/letters/2026-10-19'):
            self.assertTrue(GET_ROUTES.fullmatch(path) and PAGE_ROUTES.fullmatch(path))

if __name__ == '__main__':
    unittest.main()
