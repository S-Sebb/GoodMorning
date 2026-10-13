"""Project-grouped Tasks and humanized Reminders on synthetic runtimes only."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

import unittest

from goodmorning.briefings import briefing_document as native
from goodmorning.records import routing


class GroupingTests(unittest.TestCase):
    def test_detail_cleanup_keeps_genuine_notes_only(self):
        self.assertEqual(routing.clean_task_detail('Write paper', 'Write paper'), '')
        self.assertEqual(routing.clean_task_detail('Write paper', 'Write paper | deadline 2026-12-31 (soft)'), '')
        self.assertEqual(routing.clean_task_detail('Buy milk', 'Attach signed figures.'), 'Attach signed figures.')
        cleaned = routing.clean_task_detail('T', 'T · Project: Atlas · Due: 2026-10-16 · No workday assigned')
        self.assertNotIn('Project', cleaned)
        self.assertNotIn('No workday', cleaned)

    def test_action_cells_have_no_title_echo_or_workday_suffix(self):
        row = {'id': 'task_1', 'revision': 1, 'occurrence_id': '', 'date': '', 'status': 'open',
               'title': 'Calculate ranking', 'detail': 'Calculate ranking | deadline 2026-10-11',
               'project': 'YuQuant', 'optional': False, 'priority': '', 'due_date': '2026-10-11',
               'due_at': '', 'timezone': '', 'group': 'deadline', 'source_entry_id': 'ib_1',
               'owner': 'tasks', 'report_detail': '', 'created_at': '2026-10-11T12:00:00+01:00'}
        cells = routing.action_cells(row)
        detail = cells[-1]
        self.assertNotIn('Calculate ranking |', detail)
        self.assertNotIn('No workday assigned', detail)
        self.assertIn('Project: YuQuant', detail)
        self.assertIn('Due: 2026-10-11', detail)

    def test_actions_group_by_project_and_lift_shared_due(self):
        rows = [
            ['task_aaaaaaaaaaaaaaaa', 1, '', '', 'open', 'Write paper',
             'Write paper | deadline 2026-12-31 (soft) · Project: MRHarmon · Soft target: 2026-12-31 · No workday assigned'],
            ['task_dddddddddddddddd', 1, '', '', 'open', 'Fix blur',
             'Fix blur | deadline 2026-12-31 (soft) · Project: MRHarmon · Soft target: 2026-12-31 · No workday assigned'],
            ['task_aaaaaaaaaaaaaaaa2', 1, '', '', 'open', 'Calculate ranking',
             'Calculate ranking | deadline 2026-10-11 · Project: YuQuant · Due: 2026-10-11 · No workday assigned'],
        ]
        html = native.render_block(['actions', rows], {}, '2026-10-11')
        self.assertIn('MRHarmon', html)
        self.assertIn('YuQuant', html)
        self.assertIn('project-count', html)
        # Shared soft target appears once in the heading, not per card.
        self.assertEqual(html.count('Soft target: 2026-12-31'), 1)
        self.assertNotIn('Project: MRHarmon', html)
        self.assertNotIn('No workday assigned</div>', html)
        self.assertIn('No workday assigned</bdi>', html)  # date group heading stays

    def test_urgent_hard_due_group_sorts_first_and_stays_open(self):
        import re
        rows = [
            ['task_m1', 1, '', '', 'open', 'Write paper',
             'Extra · Project: MRHarmon · Soft target: 2026-12-31'],
            ['task_m2', 1, '', '', 'open', 'Fix blur',
             'Extra · Project: MRHarmon · Soft target: 2026-12-31'],
            ['task_m3', 1, '', '', 'open', 'Add tests',
             'Extra · Project: MRHarmon · Soft target: 2026-12-31'],
            ['task_m4', 1, '', '', 'open', 'Improve scans',
             'Extra · Project: MRHarmon · Soft target: 2026-12-31'],
            ['task_y1', 1, '', '', 'open', 'Calculate ranking',
             'Extra · Project: YuQuant · Due: 2026-10-11'],
        ]
        html = native.render_block(['actions', rows], {}, '2026-10-11')
        order = [m.group(1) for m in re.finditer(r'project-name" data-content>([^<]+)', html)]
        self.assertEqual(order[0], 'YuQuant')
        first = html.split('YuQuant')[0]
        self.assertIn('open', first[-600:])

    def test_decisions_are_cards_with_human_times(self):
        rows = [['abcdefabcdefabcd', 1,
                 'Review calendar change: Canceled: Imperial-QMUL Catchup',
                 'outlook · 2026-10-23T11:00:00+00:00 · 2026-10-23T12:00:00+00:00 · confirmed']]
        html = native.render_block(['decisions', rows], {}, '2026-10-11')
        self.assertIn('decision-card', html)
        self.assertIn('Canceled: Imperial-QMUL Catchup', html)
        self.assertNotIn('Review calendar change', html)
        self.assertNotIn('2026-10-23T11', html)
        self.assertIn('Fri 23 Oct 11:00', html)

    def test_calendar_review_copy_uses_action_prefix_and_human_range(self):
        from goodmorning.web import language as ui
        token = ui.CURRENT.set('en')
        try:
            title, facts = routing.calendar_review_copy(
                {'subject': 'Canceled: Imperial-QMUL Catchup', 'source': 'outlook',
                 'start': '2026-10-23T11:00:00+00:00', 'end': '2026-10-23T12:00:00+00:00',
                 'status': 'cancelled', 'raw_revision': 2}, 'Europe/London', ui)
            self.assertTrue(title.startswith('Canceled:'))
            self.assertNotIn('Review calendar change', title)
            self.assertNotIn('2026-10-23T11', facts)
            self.assertIn('23 Oct', facts)
            title2, _ = routing.calendar_review_copy(
                {'subject': 'Planning sync', 'source': 'outlook',
                 'start': '2026-10-23T10:00:00+00:00', 'end': '2026-10-23T11:00:00+00:00',
                 'status': 'confirmed', 'raw_revision': 3}, 'Europe/London', ui)
            self.assertTrue(title2.startswith('Updated:'))
        finally:
            ui.CURRENT.reset(token)


if __name__ == '__main__':
    unittest.main()
