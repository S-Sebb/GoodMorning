"""Offline briefings through the real gateway with synthetic accounts: the service worker keeps the latest
morning and evening copies, shows them without a connection, keeps no token, and forgets them at sign-out
and when another account signs in. No model is contacted."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect

REPO = Path(__file__).resolve().parents[2]
# Routes the worker's own requests too, so they reach the synthetic gateway (Chromium only).
os.environ['PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS'] = '1'
HOST = 'https://gm.language.test'
CACHED = """async () => { const result = {};
    for (const name of await caches.keys()) { const cache = await caches.open(name); result[name] = {};
        for (const request of await cache.keys()) result[name][new URL(request.url).pathname] = await (await cache.match(request)).text(); }
    return result; }"""
# A synthetic unsaved evening check-in note in this sign-in's namespace (browser.js).
CHECKIN = """scope => { scope = scope || JSON.parse(document.querySelector('#browser-config').dataset.config).workspaceScope;
    localStorage.setItem('goodmorningCheckin:' + scope + ':synthetic', JSON.stringify({text: 'Private note', at: Date.now()})); return scope; }"""
CHECKINS = "Object.keys(localStorage).filter(key => key.startsWith('goodmorningCheckin:'))"


def main():
    artifacts = Path(sys.argv[1]); artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='gm-offline-') as directory:
        process = subprocess.Popen([sys.executable, str(REPO/'tests/browser/language.py'), '--serve', directory],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            while True:
                line = process.stdout.readline()
                if line.startswith('{'):
                    settings = json.loads(line); break
                if not line: raise RuntimeError('Synthetic gateway fixture did not start.')
            errors, copies = [], []
            network = {'up': True}
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                def context(width):
                    result = browser.new_context(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
                    def forward(route):
                        if not network['up']:
                            return route.abort('internetdisconnected')
                        parsed = urlsplit(route.request.url)
                        headers = {**route.request.all_headers(), 'Host': parsed.hostname,
                            'X-Forwarded-Proto': 'https', 'X-Real-IP': '192.0.2.1'}
                        response = route.fetch(url=settings['gateway']+parsed.path+('?' + parsed.query if parsed.query else ''),
                                               headers=headers, max_redirects=0)
                        if parsed.path.startswith('/offline/'):
                            copies.append((parsed.path, response.status))
                        route.fulfill(response=response)
                    result.route('https://*.language.test/**', forward)
                    return result

                def sign_in(page, name, temporary=True):
                    page.goto(HOST + '/login')
                    assert page.evaluate(CHECKINS) == []  # However the last session ended.
                    page.locator('input[name=username]').fill(name)
                    page.locator('#password-password').fill('a1' + name + ('-temporary' if temporary else '-permanent'))
                    page.locator('#account-form button[type=submit]').click()
                    if temporary:
                        expect(page.get_by_role('heading', name='Change password', exact=True)).to_be_visible()
                        expect(page.locator('#site-patch-note')).to_be_visible()
                        page.locator('#patch-note-dismiss').click()
                        expect(page.locator('#site-patch-note')).to_be_hidden()
                        page.locator('input[name=current]').fill('a1' + name + '-temporary')
                        expect(page.locator('input[name=current]')).to_have_value('a1' + name + '-temporary')
                        page.locator('input[name=replacement]').fill('a1' + name + '-permanent')
                        page.locator('input[name=repeat]').fill('a1' + name + '-permanent')
                        page.evaluate(CHECKIN, 'a' * 64)
                        with page.expect_response('**/api/auth/password'):
                            page.locator('#account-form button[type=submit]').click()
                    expect(page).not_to_have_url(re.compile(r'/(login|password)$'))
                    assert page.evaluate(CHECKINS) == []  # A password change starts without earlier answers.

                def kept(page, count):
                    # The worker refreshes its copies after each page load; wait until it holds exactly these.
                    deadline = time.monotonic() + 15
                    while True:
                        cached = page.evaluate(CACHED)
                        names = [name for name in cached if name.startswith('offline-')]
                        files = cached[names[0]] if len(names) == 1 else {}
                        if (sum(path.startswith('/offline/') for path in files) == count
                                and any(path.endswith('.css') for path in files) == (count > 0) and len(names) <= 1):
                            return cached
                        if time.monotonic() > deadline:
                            raise AssertionError(f'Offline copies never settled: { {name: sorted(value) for name, value in cached.items()} }')
                        time.sleep(.2)

                def unreachable(page):
                    # With nothing kept, a page load fails as it always did (the app then shows its can't-connect screen).
                    try:
                        page.goto(HOST + '/gm.html')
                    except Exception as error:
                        assert 'ERR_FAILED' in str(error) or 'ERR_INTERNET_DISCONNECTED' in str(error), error
                        page.wait_for_url('chrome-error://chromewebdata/')
                    else:
                        raise AssertionError('An offline copy was shown: ' + page.content()[:300])

                phone = context(390)
                page = phone.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                sign_in(page, 'alice')
                page.goto(HOST + '/gm.html')
                expect(page.get_by_role('heading', name='Existing English briefing', exact=True)).to_be_visible()
                csrf = json.loads(page.locator('#language-config').get_attribute('data-config'))['csrf']
                cached = kept(page, 2)
                [(name, files)] = cached.items()
                # Only the two copies and the files they and their stylesheets name, none carrying the session's token.
                assert not any(path.startswith(('/api/', '/login', '/logout', '/password')) for path in files), sorted(files)
                assert any(path.endswith('/desk-morning.svg') for path in files), sorted(files)
                assert not any(csrf in text or 'csrf' in text.lower() for text in files.values())

                # Another page load checks the copies without downloading them again.
                page.goto(HOST + '/chat')
                expect(page.locator('#chat-compose')).to_be_visible()
                page.wait_for_timeout(500)
                assert ('/offline/gm.html', 304) in copies and ('/offline/gn.html', 304) in copies, copies

                # Without a connection: today's copy with a clear notice, from any page, for both editions.
                network['up'] = False
                for language, suffix in (('en', ''), ('zh-CN', '-zh')):
                    page.goto(HOST + '/gm.html')
                    notice = page.locator('.offline-notice')
                    expect(notice).to_be_visible()
                    expect(page.get_by_role('heading', name='Existing English briefing', exact=True)).to_be_visible()
                    expect(page.locator('#language-config')).to_have_count(0)
                    expect(page.locator('#sign-out')).to_have_count(0)
                    if language == 'en':
                        expect(notice.locator('.offline-today')).to_have_text(re.compile(r'^You’re offline · showing the version from \d\d:\d\d\.$'))
                        expect(notice.locator('.offline-earlier')).to_be_hidden()
                        expect(page.locator('html')).to_have_attribute('data-day-scheme', re.compile('.+'))
                        assert page.evaluate("getComputedStyle(document.querySelector('.offline-notice')).borderTopStyle") == 'solid'
                    page.screenshot(path=str(artifacts/f'offline-gm-390{suffix}.png'), full_page=True)
                    page.locator('.edition-switch a[href="/gn.html"]').click()
                    expect(page).to_have_url(HOST + '/gn.html')
                    expect(page.locator('html')).to_have_attribute('data-edition', 'gn')
                    expect(page.locator('.offline-notice')).to_be_visible()
                    page.screenshot(path=str(artifacts/f'offline-gn-390{suffix}.png'), full_page=True)
                    if language == 'en':
                        page.goto(HOST + '/chat')
                        expect(page).to_have_url(HOST + '/chat')
                        expect(page.locator('.offline-notice')).to_be_visible()
                        # Switch the website language while online, then go offline again.
                        network['up'] = True
                        page.goto(HOST + '/gm.html')
                        page.locator('#account-menu > summary').click()
                        with page.expect_response('**/api/language'):
                            page.locator('#website-language').select_option('zh-CN')
                        page.goto(HOST + '/gm.html')
                        page.wait_for_timeout(500)
                        kept(page, 2)
                        network['up'] = False
                page.goto(HOST + '/gm.html')
                expect(page.locator('.offline-notice a')).to_have_text('重试')

                # Back online, Try again opens the live page; signing out forgets the copies.
                network['up'] = True
                page.locator('.offline-notice a').click()
                expect(page.locator('#language-config')).to_have_count(1)
                scope = page.evaluate(CHECKIN, None)
                page.reload()
                assert page.evaluate(CHECKINS) == ['goodmorningCheckin:' + scope + ':synthetic']
                page.locator('#account-menu > summary').click()
                page.locator('#website-language').select_option('en')
                page.locator('#sign-out').click()
                expect(page).to_have_url(HOST + '/login')
                kept(page, 0)
                assert page.evaluate(CHECKINS) == []
                network['up'] = False
                unreachable(page)
                network['up'] = True

                # A session that ends without signing out: the next account to sign in never sees the copies.
                sign_in(page, 'alice', temporary=False)
                page.goto(HOST + '/gn.html')
                kept(page, 2)
                alice = page.evaluate(CHECKIN, None)
                assert alice != scope  # Every sign-in gets its own namespace.
                # Answers an earlier sign-in wrote later, e.g. from a tab left open, are removed by this one's briefing page.
                page.evaluate(CHECKIN, scope)
                page.reload()
                assert page.evaluate(CHECKINS) == ['goodmorningCheckin:' + alice + ':synthetic']
                phone.clear_cookies()
                sign_in(page, 'bob')
                page.goto(HOST + '/gm.html')
                kept(page, 0)  # Bob has no saved briefing.
                network['up'] = False
                unreachable(page)
                network['up'] = True

                # Desktop width.
                desktop = context(1440)
                wide = desktop.new_page()
                wide.on('pageerror', lambda error: errors.append(str(error)))
                sign_in(wide, 'alice', temporary=False)
                wide.goto(HOST + '/gm.html')
                kept(wide, 2)
                network['up'] = False
                wide.goto(HOST + '/gm.html')
                expect(wide.locator('.offline-notice')).to_be_visible()
                wide.screenshot(path=str(artifacts/'offline-gm-1440.png'))
                network['up'] = True
                browser.close()
            assert not errors, errors
            report = {'copiesKept': True, 'noTokensKept': True, 'offlineNotice': ['en', 'zh-CN'], 'bothEditions': True,
                      'anyPageOffline': True, 'unchangedCopiesNotDownloaded': True, 'forgottenAtSignOut': True,
                      'forgottenForAnotherAccount': True, 'checkinAnswersForgotten': True, 'widths': [390, 1440]}
            (artifacts/'result.json').write_text(json.dumps(report, indent=2)); print(json.dumps(report))
        finally:
            process.terminate(); process.communicate(timeout=5)


if __name__ == '__main__':
    main()
