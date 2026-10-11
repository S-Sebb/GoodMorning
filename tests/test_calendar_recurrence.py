import contextlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from support import TEMP_ROOT

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from goodmorning.calendar.calendar_recurrence import expand, occurrence_id
from goodmorning.calendar import secretary_calendar as calendar
from goodmorning.calendar.calendar_store import CalendarStore


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


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.root = Path(self.tmp.name)
        self.cache = self.root / 'cache.sqlite'
        self.con = sqlite3.connect(self.cache)
        self.con.execute('CREATE TABLE cal_events (id TEXT, cal_id TEXT, title TEXT, event_start INTEGER, '
                         'event_end INTEGER, flags INTEGER, event_start_tz TEXT, recurrence_id INTEGER, ical_status TEXT)')
        self.con.execute('CREATE TABLE cal_recurrence (item_id TEXT, cal_id TEXT, icalString TEXT)')
        self.con.execute('CREATE TABLE cal_properties (item_id TEXT, cal_id TEXT, recurrence_id INTEGER, key TEXT, value TEXT)')

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def insert(self, stamp, rule=None, cal_id='work', recurrence=None, flags=16, zone='Europe/London', status=None):
        microseconds = int(stamp.timestamp() * 1000000)
        self.con.execute('INSERT INTO cal_events VALUES (?,?,?,?,?,?,?,?,?)',
                         ('series', cal_id, 'Meeting', microseconds, microseconds + 3600000000,
                          flags, zone, recurrence, status))
        if rule:
            self.con.execute('INSERT INTO cal_recurrence VALUES (?,?,?)', ('series', cal_id, rule))
        self.con.commit()

    def parse(self, date, days=7, zone='Europe/London'):
        tz = ZoneInfo(zone)
        start = datetime.fromisoformat(date).replace(tzinfo=tz)
        return calendar.parse_betterbird(str(self.cache), start, start + timedelta(days=days), tz)

    def test_old_master_expands_and_preserves_dst_wall_time(self):
        seed = datetime(2026, 1, 5, 9, tzinfo=ZoneInfo('Europe/London'))
        self.insert(seed, 'RRULE:FREQ=WEEKLY;BYDAY=MO')
        events = self.parse('2026-10-19', 14)
        self.assertEqual([e.start.hour for e in events], [9, 9])
        self.assertEqual([e.start.utcoffset() for e in events], [timedelta(hours=1), timedelta(0)])
        self.assertEqual([e.occurrence_id for e in events], [occurrence_id(e.start) for e in events])
        self.assertEqual([e.occurrence_id for e in self.parse('2026-10-26')], [events[1].occurrence_id])

    def test_moved_exception_and_cancellation_replace_originals(self):
        seed = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
        self.insert(seed, 'RRULE:FREQ=WEEKLY;COUNT=4', zone='UTC')
        original = seed + timedelta(days=7)
        self.insert(original + timedelta(days=1, hours=2), recurrence=int(occurrence_id(original)), flags=0, zone='UTC')
        cancelled = seed + timedelta(days=14)
        self.insert(cancelled, recurrence=int(occurrence_id(cancelled)), flags=0, zone='UTC', status='CANCELLED')
        events = self.parse('2026-10-12', 14, 'UTC')
        self.assertEqual([e.start.day for e in events], [13, 19])
        self.assertEqual(events[0].occurrence_id, occurrence_id(original))
        self.assertEqual(events[1].status, 'cancelled')

    def test_exception_moved_outside_window_is_still_staged(self):
        seed = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
        self.insert(seed, 'RRULE:FREQ=WEEKLY;COUNT=3', zone='UTC')
        original = seed + timedelta(days=7)
        self.insert(original + timedelta(days=30), recurrence=int(occurrence_id(original)), flags=0, zone='UTC')
        events = self.parse('2026-10-12', 7, 'UTC')
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].start.month, 11)

    def test_same_ids_in_two_calendars_and_inherited_properties(self):
        seed = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
        for cal_id, location in [('work', 'Room A'), ('personal', 'Room B')]:
            self.insert(seed, 'RRULE:FREQ=DAILY;COUNT=3', cal_id=cal_id, zone='UTC')
            self.con.execute('INSERT INTO cal_properties VALUES (?,?,NULL,?,?)', ('series', cal_id, 'LOCATION', location))
        self.con.commit()
        events = self.parse('2026-10-05', 3, 'UTC')
        self.assertEqual(len(events), 6)
        self.assertEqual({e.location for e in events}, {'Room A', 'Room B'})

    def test_exdate_stages_cancellation_and_repeat_sync_is_unchanged(self):
        seed = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
        self.insert(seed, 'RRULE:FREQ=DAILY;COUNT=3', zone='UTC')
        self.con.execute("INSERT INTO cal_recurrence VALUES ('series','work','EXDATE:20261006T090000Z')")
        self.con.commit()
        # EXDATE takes precedence even if a stale exception row is also present.
        self.insert(seed + timedelta(days=1), recurrence=int(occurrence_id(seed + timedelta(days=1))),
                    flags=0, zone='UTC')
        args = ['--sync-betterbird', '--betterbird-path', str(self.cache), '--db', str(self.root / 'calendar.sqlite'),
                '--from', '2026-10-05', '--days', '3', '--timezone', 'UTC']
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(calendar.main(args), 0)
        self.assertEqual(json.loads(out.getvalue())['new'], 3)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(calendar.main(args), 0)
        self.assertEqual(json.loads(out.getvalue())['unchanged'], 3)
        store = CalendarStore(str(self.root / 'calendar.sqlite'))
        try:
            raw = [store.get(row['id'])['raw'] for row in store.pending()]
            self.assertEqual(sum(e['status'] == 'cancelled' for e in raw), 1)
        finally:
            store.close()

    def test_all_day_and_floating_across_dst(self):
        seed = datetime(2026, 10, 24, tzinfo=timezone.utc)
        self.insert(seed, 'RRULE:FREQ=DAILY;COUNT=3', flags=24, zone='floating')
        self.con.execute('UPDATE cal_events SET event_end = event_start + 86400000000')
        self.con.commit()
        events = self.parse('2026-10-24', 3)
        self.assertEqual([e.start.hour for e in events], [0, 0, 0])
        self.assertEqual([e.end.day - e.start.day for e in events], [1, 1, 1])
        self.assertTrue(all(e.all_day for e in events))

    def test_bad_rule_import_is_atomic_and_probe_is_metadata_only(self):
        seed = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
        self.insert(seed, 'RRULE:FREQ=DAILY;BYHOUR=9', zone='UTC')
        self.assertEqual(calendar.probe_betterbird(self.cache)['status'], 'verified')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            code = calendar.main(['--sync-betterbird', '--betterbird-path', str(self.cache),
                                  '--db', str(self.root / 'calendar.sqlite'), '--from', '2026-10-05'])
        self.assertEqual(code, 2)
        self.assertIn('unsupported recurrence', err.getvalue())
        store = CalendarStore(str(self.root / 'calendar.sqlite'))
        try:
            self.assertEqual(store.stats()['total'], 0)
        finally:
            store.close()


if __name__ == '__main__':
    unittest.main()
