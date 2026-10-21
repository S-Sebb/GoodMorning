"""Published ICS feeds: Outlook-style content expands, applies to the schedule and reconciles removals."""
import contextlib
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from support import TEMP_ROOT
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from goodmorning.calendar import calendar_ics, secretary_calendar as calendar
from goodmorning.calendar.calendar_store import CalendarStore

LONDON = ZoneInfo('Europe/London')
SERIES = 'outlook-series-1'
FEED = '\r\n'.join([
    'BEGIN:VCALENDAR', 'VERSION:2.0',
    'BEGIN:VTIMEZONE', 'TZID:GMT Standard Time', 'BEGIN:STANDARD', 'DTSTART:16010101T020000',
    'TZOFFSETFROM:+0100', 'TZOFFSETTO:+0000', 'END:STANDARD', 'END:VTIMEZONE',
    # Weekly 11:00 London series across the end of summer time, one week skipped.
    'BEGIN:VEVENT', 'UID:' + SERIES, 'SUMMARY:Spatial discussion', 'LOCATION:Teams',
    'DTSTART;TZID=GMT Standard Time:20261015T110000', 'DTEND;TZID=GMT Standard Time:20261015T120000',
    'RRULE:FREQ=WEEKLY;BYDAY=TH;UNTIL=20261105T110000Z', 'EXDATE;TZID=GMT Standard Time:20261029T110000',
    'END:VEVENT',
    # One occurrence moved to Friday.
    'BEGIN:VEVENT', 'UID:' + SERIES, 'RECURRENCE-ID;TZID=GMT Standard Time:20261022T110000',
    'SUMMARY:Spatial discussion (moved)', 'DTSTART;TZID=GMT Standard Time:20261023T140000',
    'DTEND;TZID=GMT Standard Time:20261023T150000', 'END:VEVENT',
    'BEGIN:VEVENT', 'UID:single-utc', 'SUMMARY:Call with\\, Jessica', 'DESCRIPTION:Bring notes\\nand',
    '  the draft', 'DTSTART:20261019T120000Z', 'DTEND:20261019T130000Z', 'END:VEVENT',
    'BEGIN:VEVENT', 'UID:cancelled', 'STATUS:CANCELLED', 'SUMMARY:Catchup',
    'DTSTART;TZID=China Standard Time:20261020T170000', 'DURATION:PT1H', 'END:VEVENT',
    'BEGIN:VEVENT', 'UID:holiday', 'SUMMARY:Reading week', 'DTSTART;VALUE=DATE:20261026',
    'DTEND;VALUE=DATE:20261027', 'END:VEVENT',
    'BEGIN:VEVENT', 'UID:old', 'SUMMARY:Last year', 'DTSTART:20251019T120000Z', 'DTEND:20251019T130000Z', 'END:VEVENT',
    'END:VCALENDAR', ''])


class FeedTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=TEMP_ROOT)
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        (self.root / 'profile.md').write_text('timezone: Europe/London\n')
        self.store = CalendarStore(str(self.root / 'calendar.sqlite'))
        self.addCleanup(self.store.close)
        self.start = datetime(2026, 10, 18, tzinfo=LONDON)

    def sync(self, feed=FEED):
        return calendar_ics.sync(self.store, 'outlook', feed, self.start, self.start + timedelta(days=30),
                                 LONDON, 'Europe/London', 'test')

    def raw(self):
        return {(r['external_id'], r['occurrence_id']): json.loads(r['raw_json'])
                for r in self.store.con.execute('SELECT * FROM events')}

    def test_outlook_feed_expands_into_scheduled_occurrences(self):
        self.assertEqual(self.sync(), {'new': 6, 'changed': 0, 'unchanged': 0, 'removed': 0})
        raw = self.raw()
        series = sorted((v['start'], v['status'], v['subject']) for (uid, _), v in raw.items() if uid == SERIES)
        self.assertEqual(series, [
            ('2026-10-23T13:00:00+00:00', 'confirmed', 'Spatial discussion (moved)'),
            ('2026-10-29T11:00:00+00:00', 'cancelled', 'Spatial discussion'),  # 11:00 GMT after summer time ends.
            ('2026-11-05T11:00:00+00:00', 'confirmed', 'Spatial discussion')])
        single = raw['single-utc', '']
        self.assertEqual((single['subject'], single['notes']), ('Call with, Jessica', 'Bring notes\nand the draft'))
        self.assertEqual((raw['cancelled', '']['status'], raw['cancelled', '']['start']), ('cancelled', '2026-10-20T09:00:00+00:00'))
        self.assertEqual((raw['holiday', '']['all_day'], raw['holiday', '']['start']), (True, '2026-10-26'))
        self.assertNotIn(('old', ''), raw)
        self.assertEqual(len(self.store.query(self.start, self.start + timedelta(days=30), limit=-1)), 4)  # Cancelled ones stay off.

    def test_resync_keeps_identities_and_cancels_removed_events(self):
        self.sync()
        single = self.store.con.execute("SELECT id,revision FROM events WHERE external_id='single-utc'").fetchone()
        self.assertEqual(self.sync(), {'new': 0, 'changed': 0, 'unchanged': 6, 'removed': 0})
        without = FEED.replace('UID:single-utc', 'UID:gone').replace('T:20261019', 'T:20251019').replace('D:20261019', 'D:20251019')
        self.assertEqual(self.sync(without), {'new': 0, 'changed': 1, 'unchanged': 5, 'removed': 1})
        approved = self.store.get(single['id'])['approved']
        # The cancellation keeps the event it removed, so briefings can name it.
        self.assertEqual((approved['subject'], approved['status'], approved['start']),
                         ('Call with, Jessica', 'cancelled', '2026-10-19T12:00:00+00:00'))
        self.assertEqual(self.sync(without)['changed'], 0)  # An applied cancellation is not repeated.

    def test_unsupported_content_imports_nothing(self):
        for broken in (FEED.replace('China Standard Time', 'Mars Standard Time'),
                       FEED.replace('RRULE:FREQ=WEEKLY', 'RRULE:FREQ=HOURLY')):
            with self.assertRaises(ValueError):
                self.sync(broken)
        self.assertEqual(self.store.stats()['total'], 0)

    def serve(self, body):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body.encode())

            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_port}/calendar.ics'

    def test_cli_saves_the_link_after_a_successful_sync_and_briefings_refresh_it(self):
        self.store.close()
        url = self.serve(FEED)
        args = ['--secretary-dir', str(self.root), '--from', '2026-10-18', '--timezone', 'Europe/London']
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(calendar.main(args + ['--sync-ics', '--source', 'outlook', '--ics-url', url]), 0)
        self.assertEqual(json.loads(out.getvalue())['new'], 6)
        config = json.loads((self.root / 'calendar.config.json').read_text())
        self.assertEqual((config['ics_url'], config['ics_source']), (url, 'outlook'))
        self.assertEqual(oct((self.root / 'calendar.config.json').stat().st_mode & 0o777), '0o600')
        self.assertEqual(calendar_ics.refresh(self.root, '2026-10-18', 'gm'), {'new': 0, 'changed': 0, 'unchanged': 6, 'removed': 0})
        with patch.object(calendar_ics, 'fetch', side_effect=OSError('offline')):
            self.assertEqual(calendar_ics.refresh(self.root, '2026-10-18', 'gn'), {'unavailable': 'OSError'})

    def test_cli_without_a_saved_link_asks_for_one(self):
        self.store.close()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(calendar.main(['--secretary-dir', str(self.root), '--sync-ics']), 2)
        self.assertIn('--ics-url', err.getvalue())
        self.assertIsNone(calendar_ics.refresh(self.root, '2026-10-18', 'gm'))


if __name__ == '__main__':
    unittest.main()
