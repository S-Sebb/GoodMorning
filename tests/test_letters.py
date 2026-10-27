"""Weekly letters: the code-built week, Sunday's evening section that saves it once, missed weeks, and the Letters pages."""
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
from goodmorning.briefings.briefing_job import act, default_plan
from goodmorning.briefings.briefing_preflight import answer, initialize as preflight
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.records import letters
from goodmorning.records.custom_store import CustomStore
from goodmorning.records.inbox_store import InboxStore, initialize
from goodmorning.records.task_store import TaskStore
from goodmorning.security.briefing_gateway import GET_ROUTES, PAGE_ROUTES
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web import letters as pages

WEEK, SUNDAY, MONDAY = '2026-10-19', '2026-10-25', '2026-10-26'
NIGHT = datetime(2026, 10, 25, 13, tzinfo=timezone.utc)  # 21:00 in Shanghai
ZONE = 'Asia/Shanghai'
WORDS = {'opening': 'You wrapped up the chapter 2 outline and kept stretching going three weeks running.',
         'signoff': 'Rest up, and see you next Sunday.'}


def visible(markup):
    return ' '.join(re.sub(r'<[^>]+>', ' ', markup).split())


def stamp(day, hour=10):
    return f'{day}T{hour:02d}:00:00+08:00'


def idea(root, raw, at):
    inbox = InboxStore(root, write=True)
    try:
        inbox.mutate('add', {'kind': 'idea', 'raw': raw}, 'ses_synthetic', raw, at)
    finally:
        inbox.close()


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

    def job(self, identifier='c' * 32, day=SUNDAY, kind='gn'):
        app = BrowserApp(self.root, now=lambda: NIGHT, preflight=True)
        job = {'id': identifier, 'date': day, 'kind': kind, 'state': 'preflight', 'session': 'ses_test'}
        app.jobs[day + '.' + kind] = job; app.save_jobs()
        fields = preflight(self.root, job)['form']['fields']
        answer(self.root, job, {field['key']: {'completed': ['none'], 'details': 'No updates today'}.get(field['key'], []) for field in fields})
        job['state'] = 'running'; app.jobs[day + '.' + kind] = job; app.save_jobs()
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

    def test_the_week_runs_on_04_00_days(self):
        idea(self.root, 'Saturday night, after midnight', '2026-10-19T02:00:00+08:00')  # Still Sunday the 18th.
        idea(self.root, 'Sunday night, after midnight', '2026-10-26T03:30:00+08:00')  # Still Sunday the 25th.
        idea(self.root, 'Monday morning', '2026-10-26T04:00:00+08:00')
        self.assertEqual(letters.facts(self.root, WEEK, 'en')['ideas'], ['Try a weekly review with Mia', 'Sunday night, after midnight'])
        self.assertEqual(letters.facts(self.root, '2026-10-12', 'en')['ideas'], ['An idea from last week', 'Saturday night, after midnight'])

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
        card = native.render_block(document['sections'][-1][1][0], {}, SUNDAY)
        self.assertIn('href="/letters/2026-10-19"', card)
        self.assertIn('5 things finished · 2 habits kept going · 1 new idea', visible(card))

        # The week is not over yet: later records join the letter once it ends at 04:00 on Monday.
        idea(self.root, 'An idea after midnight', '2026-10-26T01:30:00+08:00')
        letters.catch_up(self.root, SUNDAY, 'en')
        self.assertEqual((self.root / 'letters' / f'{WEEK}.json').read_text(), before)
        letters.catch_up(self.root, MONDAY, 'en')
        complete = letters.load(self.root, WEEK)
        self.assertEqual(complete['ideas'], ['Try a weekly review with Mia', 'A late idea', 'An idea after midnight'])
        self.assertEqual((complete['opening'], complete['signoff'], 'open' in complete), (WORDS['opening'], WORDS['signoff'], False))
        # Then it is a memory and never changes again.
        idea(self.root, 'Too late', '2026-10-25T23:00:00+08:00')
        letters.catch_up(self.root, '2026-10-27', 'en')
        self.assertEqual(letters.load(self.root, WEEK), complete)

    def test_unreadable_records_say_so_instead_of_promising_a_letter(self):
        self.job()
        self.reach_letter()
        with patch.object(letters, 'facts', side_effect=ValueError('setup_required')):
            self.step('publish', {'position': 5})
        preview = json.loads((self.root / 'browser-jobs' / ('c' * 32 + '.preview.json')).read_text())
        self.assertEqual(preview['document']['sections'][-1], ['letter', [['letter', WEEK, None]]])
        self.assertIsNone(letters.load(self.root, WEEK))
        self.assertIn('couldn’t be written', native.render_block(['letter', WEEK, None], {}))

    def test_other_days_carry_no_letter_for_a_new_account_and_the_user_can_turn_it_off(self):
        def plan(identifier, day=SUNDAY):
            self.job(identifier, day)
            self.step('init', {'greeting': 'Evening.', 'opening': 'Tonight’s review.'}, identifier)
            return [tag for tag, _ in json.loads((self.root / 'browser-jobs' / (identifier + '.preview.json')).read_text())['plan']]
        self.assertNotIn('letter', plan('a' * 32, '2026-10-24'))
        (self.root / 'profile.md').write_text((self.root / 'profile.md').read_text() + 'weekly_letter: "false"\n')
        self.assertNotIn('letter', plan('b' * 32))

    def test_a_skipped_sunday_sends_last_weeks_letter_with_the_next_briefing(self):
        (self.root / 'daily' / '2026-10-21.md').write_text('# 2026-10-21\n')  # The account was in use that week.
        self.assertIsNone(letters.due(self.root, SUNDAY, 'gm'))  # The week before was not in use yet.
        self.job(day=MONDAY)
        self.step('init', {'greeting': 'Evening.', 'opening': 'Tonight’s review.'})
        self.step('publish', {'position': 0, 'section': ['today', [['p', 'You shared no updates.']]]})
        self.step('publish', {'position': 1, 'section': ['weather', [['p', 'Tomorrow’s weather is unavailable.']], '', 'Weather tomorrow']})
        self.step('publish', {'position': 2, 'section': ['schedule', [['p', 'One appointment tomorrow.']]]})
        self.step('skip', {'position': 3})
        result = self.step('skip', {'position': 4})
        self.assertEqual(result['next']['section'], ['letter', 'Weekly letter'])
        self.assertEqual(result['next']['results'][0]['output']['week'], WEEK)
        self.step('publish', {'position': 5, 'letter': WORDS})
        # Written after its week ended, the letter is complete at once.
        self.assertNotIn('open', letters.load(self.root, WEEK))
        card = visible(native.render_block(['letter', WEEK, [5, 2, 1]], {}, MONDAY))
        self.assertIn('Last week’s letter is in your book.', card)
        self.assertIn('Last week’s letter couldn’t be written this time.', visible(native.render_block(['letter', WEEK, None], {}, MONDAY)))
        # Once written, later briefings that week carry none; a morning plan ends with it when one is due.
        self.assertIsNone(letters.due(self.root, '2026-10-27', 'gm'))
        context = {'workflow': 'gm', 'document_version': 2, 'news': {'as_of': '2026-10-27T07:00:00+08:00'}, 'weekly_letter': {'week': WEEK}}
        self.assertEqual(default_plan(context)[-1][0], 'letter')

    def test_older_missed_weeks_get_a_letter_from_code_except_while_letters_were_off(self):
        letters.save(self.root, '2026-09-28', {'signoff': 'See you.'}, 'en', '2026-10-04')
        letters.catch_up(self.root, '2026-10-27', 'en')
        # From the first letter on, every week has one; last week waits for the next briefing.
        self.assertEqual(letters.weeks(self.root), ['2026-10-12', '2026-10-05', '2026-09-28'])
        written = letters.load(self.root, '2026-10-12')
        self.assertEqual((written['opening'], written['signoff'], written['ideas']),
                         ('Here’s a look back at this week.', 'Until the next letter.', ['An idea from last week']))
        self.assertEqual(letters.load(self.root, '2026-10-05')['habits'], [['Stretching', 1, 1], ['Reading', 1, 1]])

        # Weeks while letters were off are not missed.
        for week in ('2026-10-12', '2026-10-05'):
            (self.root / 'letters' / f'{week}.json').unlink()
        profile = (self.root / 'profile.md').read_text()
        (self.root / 'profile.md').write_text(profile + 'weekly_letter: "false"\n')
        letters.catch_up(self.root, '2026-10-14', 'en')
        (self.root / 'profile.md').write_text(profile)
        (self.root / 'daily' / '2026-10-21.md').write_text('# 2026-10-21\n')
        letters.catch_up(self.root, '2026-11-03', 'en')
        self.assertEqual(letters.weeks(self.root), ['2026-10-19', '2026-09-28'])
        self.assertEqual(letters.due(self.root, '2026-11-03', 'gm'), '2026-10-26')

    def test_a_short_week_gets_its_opening_from_code(self):
        quiet = '2026-09-28'  # Before any saved record.
        output = io.StringIO()
        with patch.object(sys, 'argv', ['letter', '--secretary-dir', str(self.root), '--week', quiet]), redirect_stdout(output):
            letters.main()
        self.assertEqual(json.loads(output.getvalue())['opening'], 'This week’s letter is a short one.')
        with self.assertRaisesRegex(ValueError, 'write only'):
            letters.save(self.root, quiet, WORDS, 'zh-CN', SUNDAY)
        with self.assertRaisesRegex(ValueError, 'at most 300 characters'):  # A sign-off is about two short sentences.
            letters.save(self.root, quiet, {'signoff': '好' * 301}, 'zh-CN', SUNDAY)
        saved = letters.save(self.root, quiet, {'signoff': '下周见。'}, 'zh-CN', SUNDAY)
        self.assertEqual((saved['opening'], saved['signoff'], letters.counts(saved)), ('这周的信写得短一些。', '下周见。', [0, 0, 0]))

    def test_the_letters_page_opens_the_newest_letter_with_a_wheel_of_weeks(self):
        app = BrowserApp(self.root, now=lambda: NIGHT)
        self.assertIn('No letters yet', pages.page(app).decode())
        letters.save(self.root, '2026-10-12', {'opening': 'An earlier week.', 'signoff': 'Bye.'}, 'en', SUNDAY)
        letters.save(self.root, WEEK, WORDS, 'en', SUNDAY)
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
