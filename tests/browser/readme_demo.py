"""Capture README demos from current UI with fictional records and no network integrations.

python tests/browser/readme_demo.py /tmp/opencode/goodmorning-readme-demo
Review the resulting PNGs before copying them into assets/readme/.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(ROOT / 'src'))
from support import TEMP_ROOT, returning_viewer
from support import MockChamber
from support import start_server
from goodmorning.briefings.briefing_document import encode, source_path
from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.records.inbox_store import InboxStore, initialize
from goodmorning.records.routing import prepare, validate_sources
from goodmorning.records.task_store import TaskStore
from goodmorning.web.briefing_server import BrowserApp
from goodmorning.web.color_schemes import write as write_colors

DAY = '2026-10-13'
NOW = datetime(2026, 10, 13, 9, tzinfo=timezone.utc)
CHAT = 'a' * 32
SESSION = 'ses_readme_demo'


def fixture(runtime):
    (runtime / 'profile.md').write_text(
        'secretary_name: Aria\nsecretary_language: English\n'
        'city: London, GB\ntimezone: Europe/London\nnews_country: GB\n')
    (runtime / 'daily').mkdir()
    initialize(runtime)
    calendar = CalendarStore(str(runtime / 'calendar.sqlite'))
    try:
        for title, day, start, end, place, notes in (
            ('Team check-in', DAY, '09:30', '10:00', 'Studio 2', 'Bring the outline and one open question.'),
            ('Design review', '2026-10-14', '14:00', '15:00', 'Library', 'Bring the two draft layouts.'),
            ('Tea with Sam', '2026-10-16', '15:00', '16:00', 'Garden café', ''),
        ):
            calendar.add({'subject': title, 'start': f'{day}T{start}:00+01:00',
                          'end': f'{day}T{end}:00+01:00', 'location': place, 'notes': notes})
        calendar.stage('Demo calendar', [{'external_id': 'demo-invitation', 'subject': 'Planning workshop',
            'start': '2026-10-14T14:30:00+01:00', 'end': '2026-10-14T15:30:00+01:00', 'location': 'Studio 1'}])
    finally:
        calendar.close()
    inbox = InboxStore(runtime, write=True)
    receipts = {}
    try:
        for key, fields in {
            'outline': {'title': 'Review the outline', 'project': 'Atlas', 'planned_date': '2026-10-12'},
            'methods': {'title': 'Draft the methods', 'project': 'Atlas', 'planned_date': DAY,
                        'due_date': '2026-10-16', 'detail': 'Use the two agreed baselines to keep the comparison focused.'},
            'figures': {'title': 'Prepare the comparison figure', 'project': 'Atlas', 'planned_date': DAY,
                        'due_date': '2026-10-16', 'detail': 'The first layout is ready; check the axis labels before sharing.'},
            'parcel': {'title': 'Pick up the library books', 'planned_date': DAY, 'detail': 'The collection email is ready.'},
            'walk': {'title': 'Take a short walk', 'planned_date': DAY, 'optional': True,
                     'detail': 'A little daylight between focused sessions.'},
            'slides': {'title': 'Prepare the review slides', 'project': 'Atlas', 'planned_date': '2026-10-14',
                       'detail': 'Choose the two layouts you want feedback on.'},
            'plants': {'title': 'Water the balcony plants', 'timezone': 'Europe/London',
                       'repeat': {'weekdays': [1, 5], 'start': DAY}},
        }.items():
            receipts[key] = inbox.mutate('add', {'kind': 'todo', 'raw': fields['title'], 'task': fields},
                                         SESSION, key, NOW.isoformat())
        inbox.mutate('add', {'kind': 'event_proposal', 'raw': 'Dentist Thursday; time still to be confirmed',
            'draft': {'title': 'Dentist', 'date': '2026-10-15', 'timezone': 'Europe/London',
                      'confirmed_day': True, 'location': 'Town Clinic', 'detail': 'Bring the referral.'}},
            SESSION, 'dentist', NOW.isoformat())
        TaskStore(inbox).mutate(receipts['outline']['task_id'], 1,
            {'status': 'done', 'confirmed_completion': True}, SESSION, 'outline-done', NOW.isoformat())
    finally:
        inbox.close()
    morning = prepare(runtime, DAY, 'gm')
    news = [
        ['news', 'AI & research', [['A smaller model, a clearer research question',
            'Fictional story: a research team shares a compact model and a careful account of its limitations.',
            [['Demo source', 'https://example.com/demo/research']]]]],
        ['news', 'World', [['Cities make more room for quiet public spaces',
            'Fictional story: a public-space pilot explores shaded paths, shared gardens, and places to pause.',
            [['Demo source', 'https://example.com/demo/world']]]]],
        ['news', 'United Kingdom', [['A new chapter for the neighbourhood library',
            'Fictional story: a local library opens a reading room and a weekend workshop programme.',
            [['Demo source', 'https://example.com/demo/uk']]]], 'GB'],
    ]
    document = {'v': 2, 'lang': 'en', 'greeting': 'Good morning. A little room for today.',
        'opening': 'London · A clear plan, one useful step at a time. Fictional demo, not a live report.',
        'sections': [
            ['weather', [['weather', [
                ['temperature', '16°C (12–18°C)', 'A cool start, with a softer afternoon. A light layer should do.'],
                ['precipitation', '65% – Rain likely', 'Bring a small umbrella if you are heading out.'],
                ['air', '30 – good', 'A comfortable day for a short walk.']]]]],
            ['news', news, 'Fictional stories and example source links, included only to demonstrate the layout.', 'News — 2026-10-12'],
            ['schedule', [morning['blocks']['schedule']], 'Today and the next two days, from your saved appointments.'],
            ['tasks', [morning['blocks']['tasks']], 'Atlas is the main thread today. Keep the comparison focused; the walk is optional.'],
            ['attention', [morning['blocks']['attention']], 'One invitation needs review. Check the overlap before accepting.'],
        ], 'closing': 'Less noise. One thing at a time.'}
    validate_sources(runtime, document, DAY, 'gm')
    source_path(runtime, DAY, 'gm').write_text(encode(document))
    inbox = InboxStore(runtime, write=True)
    try:
        tasks = TaskStore(inbox)
        tasks.mutate(receipts['parcel']['task_id'], 1, {'status': 'done', 'confirmed_completion': True},
                     SESSION, 'books-done', NOW.isoformat(), day=DAY)
        tasks.mutate(receipts['methods']['task_id'], 1,
            {'status': 'partial', 'detail': 'The first baseline is written up; the second comparison is still open.'},
            SESSION, 'methods-partial', NOW.isoformat(), day=DAY)
    finally:
        inbox.close()
    evening = prepare(runtime, DAY, 'gn')
    document = {'v': 2, 'lang': 'en', 'greeting': 'Good evening. You can put the day down.',
        'opening': 'Some things finished, some still open. Fictional demo, with reported progress rather than guesses.',
        'sections': [[tag, [evening['blocks'][tag]], note] for tag, note in (
            ('today', 'The books are collected. The methods have moved forward, but are not finished.'),
            ('schedule', 'The design review is tomorrow. Bring the two layouts; the dentist time is still to be confirmed.'),
            ('tasks', 'Prepare the review slides tomorrow. Unfinished work stays on its original date.'),
            ('attention', 'The workshop invitation still needs your decision.'))],
        'closing': 'That is enough for tonight. Let tomorrow have its own space.'}
    validate_sources(runtime, document, DAY, 'gn')
    source_path(runtime, DAY, 'gn').write_text(encode(document))
    returning_viewer(runtime)
    chamber = MockChamber(runtime)
    return BrowserApp(runtime, chamber, now=lambda: NOW)


def chat_status():
    return {'mode': 'secretary', 'state': 'idle', 'label': 'Ready for your reply',
        'language': 'en', 'secretary_name': 'Aria', 'forms': [], 'permissions': [], 'messages': [
            {'id': 'hello', 'role': 'user', 'text': 'Save the Atlas slides for tomorrow. Keep the balcony garden as an idea.'},
            {'id': 'reply', 'role': 'assistant', 'text': '## A little room for the review\n\nThe slides are saved for tomorrow. Choose the **two layouts** you want feedback on.\n\nThe balcony garden stays an idea, not another obligation.'},
            {'id': 'task', 'role': 'assistant', 'kind': 'action', 'text': 'Prepare the review slides',
             'action': {'operation': 'added', 'target': 'task'}},
            {'id': 'idea', 'role': 'assistant', 'kind': 'action', 'text': 'A tiny balcony garden',
             'action': {'operation': 'added', 'target': 'idea'}},
            {'id': 'question', 'role': 'assistant', 'kind': 'question', 'text': 'Accept the workshop invitation despite the clash?'},
            {'id': 'answer', 'role': 'user', 'kind': 'answer', 'text': 'Not yet. Leave it pending while I check.'},
        ]}


def capture(app, output):
    server = start_server(app)
    address = f'http://127.0.0.1:{server.server_address[1]}'
    errors, pictures = [], []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={'width': 1440, 'height': 1050}, reduced_motion='reduce')

            def route(request):
                path = urlsplit(request.request.url)
                assert request.request.url.startswith(address + '/'), request.request.url
                if path.path == '/api/chats':
                    request.fulfill(json={**app.chat_settings(), 'chats': [
                        {'id': CHAT, 'mode': 'secretary', 'title': 'A little room for the Atlas review',
                         'updated': NOW.isoformat(), 'state': 'idle'}]})
                elif path.path.startswith('/api/chats/'):
                    request.fulfill(json=chat_status())
                else:
                    request.continue_()

            context.route('**/*', route)
            page = context.new_page()
            page.clock.set_system_time(NOW)
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('response', lambda response: errors.append(f'{response.status} {urlsplit(response.url).path}')
                    if response.status >= 400 else None)

            def open_page(path, day='first-light'):
                write_colors(app.runtime, {'day': day, 'night': 'starry'})
                page.goto(address + path)
                page.evaluate('document.fonts.ready')
                page.evaluate('''() => Promise.all(Array.from(document.images)
                    .filter(img => img.loading !== 'lazy' && img.getAttribute('src'))
                    .map(img => img.decode()))''')
                assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')

            def shot(name, locator=None, full_page=False):
                page.mouse.move(0, 0)
                if page.viewport_size['width'] <= 700:
                    for rail in page.locator('.scroll-rail:not([hidden])').all():
                        expect(rail).to_have_css('opacity', '0')
                options = {'path': str(output / f'{name}.png')}
                if locator is None:
                    options['full_page'] = full_page
                else:
                    locator.evaluate('element => window.scrollTo(0, Math.max(0, element.offsetTop - 120))')
                    expect(locator).to_be_in_viewport(ratio=1)
                (locator or page).screenshot(**options)
                pictures.append(name)

            open_page('/gm.html')
            expect(page.locator('.briefing-section h2')).to_have_text(
                ['Weather', 'News · 12 Oct (2026-10-12)', 'Schedule', 'Tasks', 'Reminders'])
            shot('morning')
            page.set_viewport_size({'width': 1440, 'height': 1800})
            for name, selector in [('weather', '.weather'), ('news', '.news'), ('schedule', '.schedule'),
                                   ('priorities', '.tasks'), ('reminders', '.attention')]:
                shot(name, page.locator('.briefing-section' + selector))
            page.set_viewport_size({'width': 1440, 'height': 1050})
            open_page('/gn.html')
            expect(page.locator('html')).to_have_attribute('data-night-scheme', 'starry')
            shot('evening')
            page.set_viewport_size({'width': 1440, 'height': 1800})
            shot('tomorrow', page.locator('.briefing-section.schedule'))
            page.set_viewport_size({'width': 1440, 'height': 1050})
            open_page('/schedule', 'warm')
            expect(page.locator('.schedule-day')).to_have_count(7)
            shot('weekly-schedule', full_page=True)
            open_page('/chat?id=' + CHAT, 'warm')
            expect(page.locator('[data-special="action"]')).to_have_count(2)
            expect(page.locator('[data-special="question"]')).to_have_count(1)
            page.locator('#chat-scroll').evaluate('element => element.scrollTop = 0')
            shot('secretary')
            open_page('/gm.html', 'morning-sky')
            expect(page.locator('html')).to_have_attribute('data-day-scheme', 'morning-sky')
            shot('morning-sky')
            page.set_viewport_size({'width': 390, 'height': 844})
            open_page('/chat?id=' + CHAT, 'warm')
            expect(page.locator('#chat-compose')).to_be_visible()
            page.locator('#chat-scroll').evaluate('element => element.scrollTop = 0')
            shot('secretary-mobile')
            open_page('/gm.html', 'morning-sky')
            expect(page.locator('#mobile-sections')).to_be_visible()
            shot('morning-mobile')
            assert not errors, errors
            assert not app.chamber.calls and not app.chamber.replies, 'Demo must never dispatch agent work'
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    report = {'synthetic': True, 'modelCalls': 0, 'externalRequests': 0, 'pageErrors': errors,
              'date': DAY, 'viewports': ['1440×1050', '1440×1800 (section close-ups)', '390×844'],
              'screenshots': pictures}
    (output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error('Capture artifacts outside the source tree; copy only reviewed PNGs into assets/readme/')
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir=TEMP_ROOT, prefix='gm-readme-') as directory:
        capture(fixture(Path(directory)), output)


if __name__ == '__main__':
    main()
