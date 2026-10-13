"""Opt-in v2 renderer checks in a real browser; synthetic records, no live accounts."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src'))
from goodmorning.records.inbox_store import initialize, InboxStore
from goodmorning.records.routing import prepare
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.briefings.briefing_web import edition
from goodmorning.web import language as ui

DAY = '2026-10-13'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screenshots', type=Path)
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='taxonomy-browser-') as temporary:
        runtime = Path(temporary)
        (runtime/'profile.md').write_text('timezone: Europe/London\n')
        initialize(runtime)
        CalendarStore(str(runtime/'calendar.sqlite')).close()
        inbox = InboxStore(runtime, write=True)
        for key, payload in enumerate([
            {'kind': 'todo', 'raw': 'Send Atlas report by Friday', 'task': {'title': 'Send Atlas report', 'due_date': '2026-10-16', 'project': 'Atlas'}},
            {'kind': 'todo', 'raw': 'Buy milk', 'task': {'planned_date': DAY}},
            {'kind': 'event_proposal', 'raw': 'Dentist Thursday', 'draft': {'title': 'Dentist', 'date': '2026-10-15', 'timezone': 'Europe/London', 'confirmed_day': True}},
            {'kind': 'project_update', 'raw': 'Confirm report scope', 'questions': ['Which comparison should the report include?']},
            {'kind': 'idea', 'raw': 'Maybe build a dashboard'},
        ]):
            inbox.mutate('add', payload, 'ses_synthetic_browser', str(key), DAY+'T12:00:00+01:00')
        inbox.close()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            for lang in ('en', 'zh-CN'):
                token = ui.CURRENT.set(lang)
                try:
                    for kind in ('gm', 'gn'):
                        items = prepare(runtime, DAY, kind)
                        document = {'v': 2, 'lang': lang, 'greeting': 'Synthetic briefing.', 'opening': 'Source-linked records.',
                                    'sections': [[tag, [items['blocks'][tag]]] for tag in ('schedule', 'tasks', 'attention') if items['blocks'][tag][1]]}
                        markup = edition(document, DAY, kind, {'gm': True, 'gn': True})
                        for width in (1440, 390, 320):
                            page = browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
                            errors = []
                            page.on('pageerror', lambda error: errors.append(str(error)))
                            def respond(route):
                                path = urlsplit(route.request.url).path.lstrip('/')
                                if path.endswith('.html'):
                                    route.fulfill(body=markup, content_type='text/html')
                                elif path in ('briefing.css', 'briefing.js'):
                                    route.fulfill(body=(ROOT/'assets/web'/path).read_bytes(), content_type='text/css' if path.endswith('.css') else 'text/javascript')
                                elif path.startswith(('fonts/', 'icons/')) and (ROOT/'assets/web'/path).is_file():
                                    route.fulfill(body=(ROOT/'assets/web'/path).read_bytes())
                                else:
                                    route.fulfill(status=404)
                            page.route('**/*', respond)
                            page.goto('http://synthetic.test/'+kind+'.html')
                            expect(page.get_by_role('heading', name=ui.text('Tasks'), exact=True)).to_be_visible()
                            expect(page.get_by_role('heading', name='Dentist', exact=True)).to_be_visible()
                            expect(page.get_by_text('Maybe build a dashboard', exact=True)).to_have_count(0)
                            expect(page.locator('.task-card')).to_have_count(2)
                            page.evaluate('document.fonts.ready')
                            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth'), (kind, lang, width)
                            assert 'task_' not in page.get_by_role('article').inner_text()
                            assert not errors, errors
                            if args.screenshots and lang == 'en' and kind == 'gm' and width in (1440, 390):
                                page.screenshot(path=str(args.screenshots/f'gm-{width}.png'), full_page=True)
                            page.close()
                finally:
                    ui.CURRENT.reset(token)
            browser.close()
    print(json.dumps({'synthetic': True, 'engine': 'Chromium', 'checks': 12, 'editions': ['gm', 'gn'], 'languages': ['en', 'zh-CN'], 'widths': [1440, 390, 320]}))


if __name__ == '__main__':
    main()
