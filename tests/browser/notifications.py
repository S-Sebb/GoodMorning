"""Per-device notification settings and Account device controls through the real gateway with synthetic
accounts; no push service or model is contacted (one browser gets a stubbed push subscription)."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
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

                def menu(page, name):
                    if page.locator(f'#{name}-menu').get_attribute('open') is None:
                        page.locator(f'#{name}-menu > summary').click()
                    return page.locator(f'#{name}-menu')

                # Settings holds this device's appearance and notifications; Account holds what follows the owner.
                settings_menu = menu(page, 'prefs')
                form = page.locator('#notification-form')
                expect(form).to_be_visible()
                expect(page.locator('#notification-status')).to_have_text('Notifications are off for this device.')
                expect(page.locator('#notification-device')).to_have_text('Turn on for this device')
                expect(page.locator('#notification-choices')).to_be_hidden()  # Choices appear once this device is on.
                assert settings_menu.locator('#website-language').count() == 0
                expect(settings_menu.locator('#color-scheme-form')).to_be_visible()
                page.screenshot(path=str(artifacts/'settings-390.png'), full_page=True)

                # This browser has no push service: turning on fails clearly and leaves nothing registered.
                page.locator('#notification-device').click()
                expect(page.locator('#notification-feedback')).to_have_text('Notifications could not be turned on for this device. Try again later.')
                expect(page.locator('#notification-device')).to_have_text('Turn on for this device')
                assert page.evaluate("navigator.serviceWorker.getRegistration('/').then(value => value === undefined)")
                assert ('POST', '/api/push/subscribe') not in push
                worker = page.evaluate("fetch('/sw.js').then(response => response.text())")
                assert "addEventListener('push'" in worker and "addEventListener('fetch'" not in worker

                account = menu(page, 'account')
                assert account.locator('#color-scheme-form').count() == 0
                for part in ('#language-form', '#app-link-form', '#sign-out'):
                    expect(account.locator(part)).to_be_visible()
                expect(account.locator('#notification-devices')).to_be_hidden()  # No device gets notifications yet.
                code = account.locator('#app-link-code')
                code.press_sequentially('abcd')
                expect(code).to_have_value('ABCD-')  # The dash follows the first four.
                code.press('Backspace')
                expect(code).to_have_value('ABCD')
                code.fill('')
                page.evaluate("""() => { const input = document.querySelector('#app-link-code'); const data = new DataTransfer();
                    data.setData('text/plain', ' abcd 2345\\n'); input.focus();
                    input.dispatchEvent(new ClipboardEvent('paste', {clipboardData: data, bubbles: true, cancelable: true})); }""")
                if code.input_value() == '':
                    code.press_sequentially(' abcd 2345')  # Headless Chromium ignores synthetic pastes; typing takes the same path.
                expect(code).to_have_value('ABCD-2345')
                page.screenshot(path=str(artifacts/'account-390.png'), full_page=True)

                # The app's "Link in GoodMorning" opens a page with the code to confirm.
                page.goto('https://sec.language.test/chat?link=wxyz2345')
                expect(page.locator('#account-menu')).to_have_attribute('open', '')
                expect(page.locator('#app-link-code')).to_have_value('WXYZ-2345')
                expect(page.locator('#app-link-feedback')).to_have_text('Check that this code matches the app, then tap Link phone.')
                assert '?link=' not in page.url

                account = menu(page, 'account')
                account.locator('#website-language').select_option('zh-CN')
                expect(page.locator('#notification-form h3')).to_have_text('通知')
                page.reload()
                menu(page, 'prefs')
                expect(page.locator('#notification-status')).to_have_text('这台设备上的通知已关闭。')
                page.screenshot(path=str(artifacts/'settings-390-zh.png'), full_page=True)
                menu(page, 'account').locator('#website-language').select_option('en')

                # A second browser with a (stubbed) push subscription turns on and keeps its own choices.
                key = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
                    serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
                p256dh = base64.urlsafe_b64encode(key).rstrip(b'=').decode()
                desktop_context = context(1440)
                desktop_context.grant_permissions(['notifications'], origin='https://sec.language.test')
                desktop_context.add_init_script("""(() => {
                    const subscription = {endpoint: 'https://fcm.googleapis.com/fcm/send/browser-test',
                        toJSON() { return {endpoint: this.endpoint, keys: {p256dh: '%s', auth: 'MDEyMzQ1Njc4OWFiY2RlZg'}}; },
                        async unsubscribe() { localStorage.removeItem('subscribed'); return true; }};
                    PushManager.prototype.subscribe = async () => { localStorage.setItem('subscribed', '1'); return subscription; };
                    PushManager.prototype.getSubscription = async () => localStorage.getItem('subscribed') ? subscription : null;
                })();""" % p256dh)
                desktop = desktop_context.new_page()
                desktop.on('pageerror', lambda error: errors.append(str(error)))
                desktop.goto('https://sec.language.test/login')
                desktop.locator('input[name=username]').fill('alice')
                desktop.locator('#password-password').fill('a1alice-permanent')
                desktop.locator('#account-form button[type=submit]').click()
                expect(desktop.locator('#chat-compose')).to_be_visible()
                menu(desktop, 'prefs')
                with desktop.expect_response('**/api/push/subscribe') as subscribed:
                    desktop.locator('#notification-device').click()
                assert subscribed.value.status == 200, subscribed.value.json()
                expect(desktop.locator('#notification-status')).to_have_text('Notifications are on for this device.')
                expect(desktop.locator('#notification-choices')).to_be_visible()
                for name in ('briefing', 'waiting', 'chat', 'events', 'gm', 'gn'):
                    expect(desktop.locator(f'#notification-form input[name={name}]')).to_be_checked()
                expect(desktop.locator('#notification-lead')).to_have_value('15')
                expect(desktop.locator('#notification-form input[name=gm_time]')).to_have_value('07:00')
                expect(desktop.locator('#notification-form input[name=gn_time]')).to_have_value('21:00')
                expect(desktop.locator('#notification-choices > .notification-note')).to_have_text('These choices apply to this device only.')
                desktop.locator('#notification-choices').screenshot(path=str(artifacts/'reminders-1440.png'))
                with desktop.expect_response('**/api/push/settings') as saved:
                    desktop.locator('#notification-form input[name=chat]').uncheck()
                assert saved.value.status == 200
                with desktop.expect_response('**/api/push/settings') as saved:
                    desktop.locator('#notification-lead').select_option('30')
                assert saved.value.status == 200
                # A reminder turned off keeps its time; another time saves as soon as it is complete.
                with desktop.expect_response('**/api/push/settings') as saved:
                    desktop.locator('#notification-form input[name=gm]').uncheck()
                assert saved.value.status == 200
                expect(desktop.locator('#notification-form input[name=gm_time]')).to_be_disabled()
                with desktop.expect_response('**/api/push/settings') as saved:
                    desktop.locator('#notification-form input[name=gn_time]').fill('22:30')
                assert saved.value.status == 200 and saved.value.json()['settings']['gn_time'] == '22:30'
                desktop.reload()
                menu(desktop, 'prefs')
                expect(desktop.locator('#notification-form input[name=chat]')).not_to_be_checked()
                expect(desktop.locator('#notification-lead')).to_have_value('30')
                expect(desktop.locator('#notification-form input[name=gm]')).not_to_be_checked()
                expect(desktop.locator('#notification-form input[name=gm_time]')).to_have_value('07:00')
                expect(desktop.locator('#notification-form input[name=gm_time]')).to_be_disabled()
                expect(desktop.locator('#notification-form input[name=gn_time]')).to_have_value('22:30')
                # Saved choices filled in after loading are not unsent text: the update button refreshes without asking.
                dialogs = []
                desktop.on('dialog', lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
                with desktop.expect_event('domcontentloaded'):
                    desktop.evaluate("document.querySelector('#update-refresh').click()")
                assert dialogs == [], dialogs
                devices = menu(desktop, 'account').locator('#notification-device-list li')
                expect(devices).to_have_count(1)
                expect(devices.first).to_contain_text('Chrome on Linux (this device)')
                desktop.screenshot(path=str(artifacts/'account-1440.png'))

                # The first browser is still off, sees the other device in Account and turns it off from there.
                page.reload()
                menu(page, 'prefs')
                expect(page.locator('#notification-status')).to_have_text('Notifications are off for this device.')
                account = menu(page, 'account')
                expect(account.locator('#notification-device-list li')).to_have_count(1)
                expect(account.locator('#notification-device-list li').first).to_contain_text('Chrome on Linux')
                with page.expect_response('**/api/push/unsubscribe') as removed:
                    account.locator('#notification-device-list li button').click()
                assert removed.value.status == 200
                expect(account.locator('#notification-devices')).to_be_hidden()
                desktop.reload()
                menu(desktop, 'prefs')
                expect(desktop.locator('#notification-status')).to_have_text('Notifications are off for this device.')
                browser.close()
            assert errors == [], errors
            print(json.dumps({'modelCalls': 0, 'pushServiceContacted': False, 'choicesPerDevice': True, 'briefingReminderTimes': True, 'accountTurnsOtherDevicesOff': True,
                              'failedTurnOnLeavesNoWorker': True, 'linkCodeFormatted': True, 'linkCodePrefilled': True,
                              'workerHasNoFetchHandler': True, 'bilingual': True, 'widths': [390, 1440], 'pageErrors': 0}))
        finally:
            process.terminate(); process.wait(timeout=10)


if __name__ == '__main__':
    main()
