"""Notification settings through the real gateway with synthetic accounts; no push service or model is contacted."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect

REPO = Path(__file__).resolve().parents[2]


def main():
    artifacts = Path(sys.argv[1]); artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='gm-notify-') as directory:
        process = subprocess.Popen([sys.executable, str(REPO/'tests/browser/language.py'), '--serve', directory],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            while True:
                line = process.stdout.readline()
                if line.startswith('{'):
                    settings = json.loads(line); break
                if not line: raise RuntimeError('Synthetic gateway fixture did not start.')
            errors, push = [], []
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel='chromium')  # The headless shell has no notifications.
                def context(width):
                    result = browser.new_context(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
                    def forward(route):
                        parsed = urlsplit(route.request.url)
                        if parsed.path.startswith('/api/push'):
                            push.append((route.request.method, parsed.path))
                        headers = {**route.request.all_headers(), 'Host': parsed.hostname,
                            'X-Forwarded-Proto': 'https', 'X-Real-IP': '192.0.2.1'}
                        response = route.fetch(url=settings['gateway']+parsed.path+('?' + parsed.query if parsed.query else ''),
                                               headers=headers, max_redirects=0)
                        route.fulfill(response=response)
                    result.route('https://*.language.test/**', forward)
                    return result
                owner = context(390)
                owner.grant_permissions(['notifications'], origin='https://sec.language.test')
                page = owner.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto('https://sec.language.test/login')
                page.locator('input[name=username]').fill('alice')
                page.locator('#password-password').fill('a1alice-temporary')
                with page.expect_response('**/api/auth/login') as signed:
                    page.locator('#account-form button[type=submit]').click()
                assert signed.value.status == 200, signed.value.json()
                expect(page).not_to_have_url('https://sec.language.test/login')
                expect(page.get_by_role('heading', name='Change password', exact=True)).to_be_visible()
                expect(page.locator('#site-patch-note')).to_be_visible()
                page.locator('#patch-note-dismiss').click()
                expect(page.locator('#site-patch-note')).to_be_hidden()
                page.locator('input[name=current]').fill('a1alice-temporary')
                expect(page.locator('input[name=current]')).to_have_value('a1alice-temporary')
                page.locator('input[name=replacement]').fill('a1alice-permanent')
                page.locator('input[name=repeat]').fill('a1alice-permanent')
                with page.expect_response('**/api/auth/password') as changed:
                    page.locator('#account-form button[type=submit]').click()
                assert changed.value.status == 200, changed.value.json()
                expect(page.locator('#chat-compose')).to_be_visible()

                def settings_panel():
                    if page.locator('#prefs-menu').get_attribute('open') is None:
                        page.locator('#prefs-menu > summary').click()
                    form = page.locator('#notification-form')
                    expect(form).to_be_visible()
                    return form
                form = settings_panel()
                for name in ('briefing', 'waiting', 'chat', 'events'):
                    expect(form.locator(f'input[name={name}]')).to_be_checked()
                expect(page.locator('#notification-lead')).to_have_value('15')
                expect(page.locator('#notification-status')).to_have_text('Notifications are off for this device.')
                expect(page.locator('#notification-device')).to_have_text('Turn on for this device')
                # The appearance controls still follow, unchanged.
                assert page.evaluate("document.querySelector('#notification-form').compareDocumentPosition(document.querySelector('#color-scheme-form')) & 4")
                form.scroll_into_view_if_needed()
                page.screenshot(path=str(artifacts/'notifications-390.png'), full_page=True)

                with page.expect_response('**/api/push/settings') as saved:
                    form.locator('input[name=chat]').uncheck()
                assert saved.value.status == 200
                expect(page.locator('#notification-feedback')).to_have_text('Notification settings saved.')
                with page.expect_response('**/api/push/settings') as saved:
                    page.locator('#notification-lead').select_option('30')
                assert saved.value.status == 200
                page.reload()
                form = settings_panel()
                expect(form.locator('input[name=chat]')).not_to_be_checked()
                expect(form.locator('input[name=events]')).to_be_checked()
                expect(page.locator('#notification-lead')).to_have_value('30')

                # This browser has no push service: turning on fails clearly and leaves nothing registered.
                page.locator('#notification-device').click()
                expect(page.locator('#notification-feedback')).to_have_text('Notifications could not be turned on for this device. Try again later.')
                expect(page.locator('#notification-device')).to_have_text('Turn on for this device')
                assert page.evaluate("navigator.serviceWorker.getRegistration('/').then(value => value === undefined)")
                assert ('POST', '/api/push/subscribe') not in push
                worker = page.evaluate("fetch('/sw.js').then(response => response.text())")
                assert "addEventListener('push'" in worker and "addEventListener('fetch'" not in worker

                page.locator('#website-language').select_option('zh-CN')
                expect(page.locator('#notification-form h3')).to_have_text('通知')
                page.reload()
                form = settings_panel()
                expect(page.locator('#notification-status')).to_have_text('这台设备上的通知已关闭。')
                page.screenshot(path=str(artifacts/'notifications-390-zh.png'), full_page=True)
                page.locator('#website-language').select_option('en')

                desktop = context(1440).new_page()
                desktop.on('pageerror', lambda error: errors.append(str(error)))
                desktop.goto('https://sec.language.test/login')
                desktop.locator('input[name=username]').fill('alice')
                desktop.locator('#password-password').fill('a1alice-permanent')
                desktop.locator('#account-form button[type=submit]').click()
                expect(desktop.locator('#chat-compose')).to_be_visible()
                desktop.locator('#prefs-menu > summary').click()
                expect(desktop.locator('#notification-form')).to_be_visible()
                expect(desktop.locator('#notification-form input[name=chat]')).not_to_be_checked()  # Shared across devices.
                expect(desktop.locator('#notification-status')).to_have_text('Notifications are off for this device.')  # Per device.
                expect(desktop.locator('#notification-device')).to_be_visible()
                desktop.screenshot(path=str(artifacts/'notifications-1440.png'))
                browser.close()
            assert errors == [], errors
            print(json.dumps({'modelCalls': 0, 'pushServiceContacted': False, 'settingsSavedAcrossReloadAndDevices': True,
                              'failedTurnOnLeavesNoWorker': True, 'deviceStateSeparate': True, 'workerHasNoFetchHandler': True, 'bilingual': True,
                              'widths': [390, 1440], 'pageErrors': 0}))
        finally:
            process.terminate(); process.wait(timeout=10)


if __name__ == '__main__':
    main()
