import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from goodmorning.calendar.calendar_recurrence import expand


class RuleTests(unittest.TestCase):
    def dates(self, rule, seed='2026-01-01T09:00:00+00:00', days=365):
        start = datetime.fromisoformat(seed)
        return [s.isoformat() for s, excluded in expand([rule], start, start + timedelta(days=days)) if not excluded]

    def test_daily_count_and_until(self):
        self.assertEqual(len(self.dates('RRULE:FREQ=DAILY;INTERVAL=2;COUNT=3')), 3)
        self.assertEqual(len(self.dates('RRULE:FREQ=DAILY;UNTIL=20260103T090000Z')), 3)

    def test_weekly_days_and_week_start(self):
        dates = self.dates('RRULE:FREQ=WEEKLY;BYDAY=TH,SA;COUNT=4')
        self.assertEqual([d[:10] for d in dates], ['2026-01-01', '2026-01-03', '2026-01-08', '2026-01-10'])
        dates = self.dates('RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=SU,MO;WKST=SU;COUNT=4', '2026-01-04T09:00:00+00:00')
        self.assertEqual([d[:10] for d in dates], ['2026-01-04', '2026-01-05', '2026-01-18', '2026-01-19'])

    def test_monthly_ordinal_and_last_weekday(self):
        dates = self.dates('RRULE:FREQ=MONTHLY;BYDAY=1TH;COUNT=3')
        self.assertEqual([d[:10] for d in dates], ['2026-01-01', '2026-02-05', '2026-03-05'])
        dates = self.dates('RRULE:FREQ=MONTHLY;BYDAY=MO,TU,WE,TH,FR;BYSETPOS=-1;COUNT=3', '2026-01-30T09:00:00+00:00')
        self.assertEqual([d[:10] for d in dates], ['2026-01-30', '2026-02-27', '2026-03-31'])

    def test_invalid_monthdays_and_leap_years_are_skipped(self):
        dates = self.dates('RRULE:FREQ=MONTHLY;COUNT=3', '2026-01-31T09:00:00+00:00')
        self.assertEqual([d[:10] for d in dates], ['2026-01-31', '2026-03-31', '2026-05-31'])
        dates = self.dates('RRULE:FREQ=YEARLY;COUNT=2', '2024-02-29T09:00:00+00:00', 2000)
        self.assertEqual([d[:10] for d in dates], ['2024-02-29', '2028-02-29'])

    def test_setpos_uses_entire_first_period(self):
        dates = self.dates('RRULE:FREQ=MONTHLY;BYDAY=TH;BYSETPOS=1;COUNT=2', '2026-01-08T09:00:00+00:00')
        self.assertEqual([d[:10] for d in dates], ['2026-01-08', '2026-02-05', '2026-03-05'])

    def test_dates_exclusions_and_folded_properties(self):
        start = datetime(2026, 1, 1, 9, tzinfo=timezone.utc)
        result = expand(['RRULE:FREQ=DAILY;\r\n COUNT=3', 'EXDATE:20260102T090000Z',
                         'RDATE:20260107T090000Z,20260108T090000Z'], start, start + timedelta(days=10))
        self.assertEqual(len(result), 5)
        self.assertEqual([s.day for s, excluded in result if excluded], [2])

    def test_nonexistent_times_do_not_count(self):
        seed = datetime(2026, 3, 7, 2, 30, tzinfo=ZoneInfo('America/New_York'))
        result = expand(['RRULE:FREQ=DAILY;COUNT=3'], seed, seed + timedelta(days=5))
        self.assertEqual([s.day for s, _ in result], [7, 9, 10])

    def test_unsupported_and_malformed_rules_fail_closed(self):
        for rule in ('RRULE:FREQ=HOURLY', 'RRULE:FREQ=DAILY;BYHOUR=2', 'EXRULE:FREQ=DAILY',
                     'RRULE:FREQ=DAILY;COUNT=0', 'RRULE:FREQ=DAILY;FREQ=WEEKLY',
                     'RDATE;VALUE=PERIOD:20260101T090000Z/20260101T100000Z'):
            with self.subTest(rule=rule), self.assertRaises(ValueError):
                self.dates(rule)


if __name__ == '__main__':
    unittest.main()
