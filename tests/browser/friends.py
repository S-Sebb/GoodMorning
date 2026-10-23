"""Friends through the real gateway and isolated synthetic viewers: requests, per-friend sharing, the friend
page in both languages and phone width, and renaming yourself. Writes screenshots to ARTIFACTS."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO/'src')); sys.path.insert(0, str(REPO/'tests'))
ZONE = 'Europe/London'


def records(runtime):
    """A week of synthetic plans and yesterday's evening reads for one account."""
    from zoneinfo import ZoneInfo
    from goodmorning import anime, games, stocks
    from goodmorning.calendar.calendar_store import CalendarStore
    today = datetime.now(ZoneInfo(ZONE)).date()
    monday = today - timedelta(days=today.weekday())
    (runtime/'profile.md').write_text(f'city: London\ntimezone: {ZONE}\nnews_country: GB\nsecretary_language: English\n')
    (runtime/'daily').mkdir()
    store = CalendarStore(str(runtime/'calendar.sqlite'))
    try:
        for offset, start, end, subject, place in ((0, '09:30', '10:00', 'Team check-in', 'Studio 2'), (1, '13:00', '14:00', 'Lunch with Mei', 'Noodle bar'),
                                                   (2, '10:00', '11:30', 'Design review', 'Library'), (4, '18:30', '21:00', 'Concert', 'Royal Albert Hall')):
            day = (monday + timedelta(days=offset)).isoformat()
            store.add({'subject': subject, 'start': f'{day}T{start}:00+01:00', 'end': f'{day}T{end}:00+01:00', 'location': place, 'notes': 'Private note'})
        store.add({'subject': 'Weekend away', 'start': (monday + timedelta(days=5)).isoformat(), 'end': (monday + timedelta(days=7)).isoformat(),
                   'all_day': True, 'timezone': ZONE})
    finally:
        store.close()
    for offset, text in ((0, '- [x] Send the slides\n- [ ] Book the train'), (1, '- [ ] Buy a birthday card'), (3, '- [ ] Water the plants')):
        day = (monday + timedelta(days=offset)).isoformat()
        (runtime/'daily'/(day + '.md')).write_text(f'# {day}\n\n## flexible\n{text}\n')
    yesterday = (today - timedelta(days=1)).isoformat()
    stocks.save(runtime, yesterday, {'block': ['holdings', [
        ['usAAPL', 'Apple', yesterday, 12, 231.4, 227.9, 180.0, 'USD', 0, 0, False],
        ['sh600519', 'Kweichow Moutai', yesterday, 10, 1488.0, 1502.5, 1650.5, 'CNY', 0, 0, False]]]})
    anime.save(runtime, yesterday, {'block': ['episodes', [['anilist:1', 'Frieren', '葬送的芙莉莲', '7', 'A Small Journey', '', yesterday + 'T23:00', '']]]})
    games.save(runtime, yesterday, {'block': ['deals', [['steam:1145360', 'Hades', 75, '£4.99', '£19.99', '', '']]]})


def fixture(root):
    from http.server import ThreadingHTTPServer
    from goodmorning.security.briefing_accounts import Accounts
    from goodmorning.security.briefing_gateway import Gateway, handler_for
    from goodmorning.web.briefing_server import BrowserApp, serve_live
    from support import MockChamber
    hosts = {kind + '.friends.test': kind for kind in ('gm', 'gn', 'sec')}
    origins = ['https://' + host for host in hosts]
    (root/'accounts').mkdir(mode=0o700)
    store = Accounts(root/'accounts', testing=True, n=1024)
    registry = {}
    for name in ('alice', 'bob', 'carol'):
        identifier = store.create(name, 'a1' + name + '-password')
        with store.db() as db:
            db.execute('UPDATE users SET temporary=0 WHERE id=?', (identifier,))
        runtime = root/name; runtime.mkdir(mode=0o700)
        records(runtime)
        with socket.socket() as check:
            check.bind(('127.0.0.1', 0)); port = check.getsockname()[1]
        key = secrets.token_urlsafe(32)
        app = BrowserApp(runtime, MockChamber(runtime))
        threading.Thread(target=serve_live, args=(app, port), kwargs={'gateway_key': key, 'public_origins': origins}, daemon=True).start()
        deadline = time.monotonic() + 15
        while True:
            try:
                with urlopen(Request(f'http://127.0.0.1:{port}/api/day', headers={'Authorization': 'Bearer ' + key, 'X-GoodMorning-Origin': origins[0]}), timeout=2):
                    break
            except Exception:
                if time.monotonic() >= deadline: raise
                time.sleep(.1)
        registry[identifier] = {'port': port, 'key': key}
    (root/'accounts/backends.json').write_text(json.dumps(registry))
    gateway = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(Gateway(store, hosts, testing=True)))
    print(json.dumps({'gateway': 'http://127.0.0.1:' + str(gateway.server_port)}), flush=True)
    gateway.serve_forever()


def run(artifacts):
    from playwright.sync_api import sync_playwright, expect
    artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='gm-friends-') as directory:
        process = subprocess.Popen([sys.executable, __file__, '--serve', directory], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        while True:
            line = process.stdout.readline()
            if line.startswith('{'): settings = json.loads(line); break
            if not line: raise RuntimeError('Friends fixture failed to start: ' + process.stderr.read()[-1500:])
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                errors = []

                def person(name, width=1280, height=900, first=True):
                    context = browser.new_context(viewport={'width': width, 'height': height}, reduced_motion='reduce')
                    def forward(route):
                        parsed = urlsplit(route.request.url)
                        headers = {**route.request.all_headers(), 'Host': parsed.hostname, 'X-Forwarded-Proto': 'https', 'X-Real-IP': '192.0.2.1'}
                        route.fulfill(response=route.fetch(url=settings['gateway'] + parsed.path + ('?' + parsed.query if parsed.query else ''),
                                                           headers=headers, max_redirects=0))
                    context.route('https://*.friends.test/**', forward)
                    page = context.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('dialog', lambda dialog: dialog.accept())
                    page.goto('https://gm.friends.test/login')
                    page.locator('input[name=username]').fill(name)
                    page.locator('#password-password').fill('a1' + name + '-password')
                    page.locator('#account-form button[type=submit]').click()
                    expect(page).not_to_have_url('https://gm.friends.test/login')
                    # A new account first sees the patch notes once.
                    if first:
                        expect(page.locator('#site-patch-note')).to_be_visible()
                        page.locator('#patch-note-dismiss').click()
                    return page

                def friends_menu(page):
                    if page.locator('#friends-menu').get_attribute('open') is None:
                        page.locator('#friends-menu > summary').click()
                    return page.locator('#friends-menu .menu-panel')

                def shot(page, name, target=None):
                    (target or page).screenshot(path=str(artifacts/(name + '.png')))

                alice, bob, carol = person('alice'), person('bob'), person('carol')
                panel = friends_menu(alice)
                expect(panel.locator('#friend-empty')).to_be_visible()
                panel.locator('#friend-name').fill('nobody')
                panel.get_by_role('button', name='Send request').click()
                expect(panel.locator('#friend-feedback')).to_have_text('No account has that username. Check the spelling.')
                for name in ('Bob', 'carol'):
                    panel.locator('#friend-name').fill(name)
                    panel.get_by_role('button', name='Send request').click()
                    expect(panel.locator('#friend-feedback')).to_have_text(f'Request sent. {name.lower()} will see it in their Friends menu.')
                expect(panel.locator('#friend-outgoing li')).to_have_count(2)
                shot(alice, '01-alice-requests-sent', panel)

                # Someone who is not (yet) a friend sees the same page as for a name that does not exist.
                carol.goto('https://gm.friends.test/friends/alice')
                expect(carol.get_by_role('heading', name='Page not available')).to_be_visible()

                bob.reload()
                expect(bob.locator('#friends-badge')).to_have_text('1')
                shot(bob, '02-bob-badge', bob.locator('.toolbar-row'))
                panel = friends_menu(bob)
                panel.locator('#friend-incoming').get_by_role('button', name='Accept').click()
                panel.get_by_label('Schedule').check()
                panel.get_by_label('Stocks').check()
                panel.get_by_label('New episodes').check()
                shot(bob, '03-bob-accepting', panel)
                panel.locator('#friend-incoming').get_by_role('button', name='Accept').click()
                expect(panel.locator('#friend-feedback')).to_have_text('You and alice are friends now.')
                expect(bob.locator('#friends-badge')).to_be_hidden()
                panel.locator('#friend-list summary').click()
                shot(bob, '04-bob-friend-row', panel)

                carol.reload()
                friends_menu(carol).locator('#friend-incoming').get_by_role('button', name='Decline').click()
                expect(friends_menu(carol).locator('#friend-requests')).to_be_hidden()

                alice.reload()
                panel = friends_menu(alice)
                expect(panel.locator('#friend-list summary')).to_contain_text('bob')
                expect(panel.locator('#friend-outgoing li')).to_have_text(['carolWaiting for them to acceptCancel'])
                panel.locator('#friend-list summary').click()
                panel.get_by_label('To-dos').check()
                expect(panel.locator('#friend-feedback')).to_have_text('Saved. bob sees this the next time their page loads.')
                shot(alice, '05-alice-friends', panel)
                panel.get_by_role('link', name='Open bob’s page').click()
                expect(alice.get_by_role('heading', name='bob', exact=True)).to_be_visible()
                expect(alice.locator('.shared-sections')).to_contain_text('Team check-in')
                expect(alice.locator('.shared-sections')).to_contain_text('Kweichow Moutai')
                expect(alice.locator('.shared-sections')).to_contain_text('Frieren')
                for private in ('Studio 2', 'Private note', 'Book the train', 'Hades'):
                    expect(alice.locator('body')).not_to_contain_text(private)
                assert not alice.evaluate('document.documentElement.scrollWidth > innerWidth')
                shot(alice, '06-friend-page-desktop')
                alice.screenshot(path=str(artifacts/'06-friend-page-desktop-full.png'), full_page=True)

                bob.reload()
                panel = friends_menu(bob)
                panel.locator('#friend-list summary').click()
                panel.get_by_label('Game sales').check()
                expect(panel.locator('#friend-feedback')).to_contain_text('Saved.')
                alice.reload()
                expect(alice.locator('.shared-sections')).to_contain_text('Hades')

                phone = person('alice', 390, 844, first=False)
                phone.goto('https://gm.friends.test/friends/bob')
                assert not phone.evaluate('document.documentElement.scrollWidth > innerWidth')
                phone.screenshot(path=str(artifacts/'07-friend-page-phone.png'), full_page=True)
                friends_menu(phone)
                shot(phone, '08-friends-menu-phone')

                # Website language is per account: alice switches to Chinese.
                alice.locator('#account-menu > summary').click()
                alice.locator('#website-language').select_option('zh-CN')
                expect(alice.locator('html')).to_have_attribute('lang', 'zh-CN')
                alice.reload()
                expect(alice.get_by_text('分享给你', exact=True)).to_be_visible()
                alice.screenshot(path=str(artifacts/'09-friend-page-zh.png'), full_page=True)
                shot(alice, '10-friends-menu-zh', friends_menu(alice))

                # Renaming: bob becomes robert; alice's link follows the new name.
                bob.locator('#account-menu > summary').click()
                form = bob.locator('#username-form')
                expect(form.locator('#username-new')).to_have_value('bob')
                form.locator('#username-new').fill('robert')
                form.locator('#username-password').fill('a1bob-password')
                shot(bob, '11-account-username', bob.locator('#account-menu .menu-panel'))
                form.get_by_role('button', name='Change username').click()
                expect(form.locator('#username-feedback')).to_have_text('Your username is now robert. Use it the next time you sign in.')
                alice.goto('https://gm.friends.test/friends/bob')
                expect(alice.locator('main h1')).not_to_have_text('bob')
                alice.goto('https://gm.friends.test/friends/robert')
                expect(alice.get_by_role('heading', name='robert', exact=True)).to_be_visible()

                # Removing ends it for both.
                bob.reload()
                panel = friends_menu(bob)
                panel.locator('#friend-list summary').click()
                panel.get_by_role('button', name='Remove friend').click()
                expect(panel.locator('#friend-empty')).to_be_visible()
                alice.reload()
                expect(alice.locator('main h1')).not_to_have_text('robert')
                assert not errors, errors
                browser.close()
        finally:
            process.terminate(); process.communicate(timeout=10)
    print('Friends browser flow passed; screenshots in', artifacts)


if __name__ == '__main__':
    if '--serve' in sys.argv: fixture(Path(sys.argv[-1]))
    else: run(Path(sys.argv[1]))
