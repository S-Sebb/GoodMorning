"""Cross-host/tab reminders through a synthetic gateway; never a real model."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO/'tests'))
sys.path.insert(0, str(REPO/'tests/browser'))


def fixture(root):
    import test_briefing_chat
    from language import fixture as language_fixture
    original = test_briefing_chat.MockChamber
    class ActivityChamber(original):
        def stage(self):
            return (root/'activity-state').read_text() if (root/'activity-state').exists() else 'waiting'

        def pending(self, session):
            return super().pending(session) if self.stage() == 'waiting' else ([], [])

        def control(self, action, **body):
            if action == 'session.status':
                return {'sessionStatus': {'type': 'idle' if self.stage() == 'idle' else 'busy'}}
            return super().control(action, **body)

        def request(self, path, body=None):
            if path == '/api/openchamber/control':
                return {'sessionStatus': {'type': 'idle' if self.stage() == 'idle' else 'busy'}}
            return super().request(path, body)
    test_briefing_chat.MockChamber = ActivityChamber
    language_fixture(root)


def run(artifacts):
    from playwright.sync_api import sync_playwright, expect
    artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='gm-activity-') as directory:
        root = Path(directory)
        process = subprocess.Popen([sys.executable, __file__, '--serve', directory], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            while True:
                line = process.stdout.readline()
                if line.startswith('{'):
                    settings = json.loads(line); break
                if not line:
                    raise RuntimeError('Synthetic fixture failed: '+process.stderr.read()[-1500:])
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                def context(width=1440):
                    result = browser.new_context(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
                    def forward(route):
                        parsed = urlsplit(route.request.url)
                        headers = {**route.request.all_headers(), 'Host': parsed.hostname, 'X-Forwarded-Proto': 'https', 'X-Real-IP': '192.0.2.1'}
                        response = route.fetch(url=settings['gateway']+parsed.path+('?' + parsed.query if parsed.query else ''), headers=headers, max_redirects=0)
                        route.fulfill(response=response)
                    result.route('https://*.language.test/**', forward)
                    return result
                def login(page, host, name, password):
                    page.goto('https://'+host+'.language.test/login')
                    page.locator('input[name=username]').fill(name)
                    page.locator('#password-password').fill(password)
                    with page.expect_navigation(wait_until='load'):
                        page.locator('#account-form button[type=submit]').click()
                    expect(page).not_to_have_url('https://'+host+'.language.test/login')
                def permanent(page, name):
                    expect(page.get_by_role('heading', name='Change password', exact=True)).to_be_visible()
                    page.locator('#patch-note-dismiss').click()
                    expect(page.locator('#site-patch-note')).to_be_hidden()
                    page.locator('input[name=current]').fill('a1'+name+'-temporary')
                    page.locator('input[name=replacement]').fill('a1'+name+'-permanent')
                    page.locator('input[name=repeat]').fill('a1'+name+'-permanent')
                    with page.expect_response('**/api/auth/password') as changed:
                        page.locator('#account-form button[type=submit]').click()
                    assert changed.value.status == 200
                    expect(page.locator('#chat-compose')).to_be_visible()
                errors = []
                owner = context()
                source = owner.new_page(); source.on('pageerror', lambda error: errors.append(str(error)))
                login(source, 'sec', 'alice', 'a1alice-temporary'); permanent(source, 'alice')
                source.get_by_role('radio', name='Initialize', exact=True).click()
                source.get_by_role('button', name='Start initialization', exact=True).click()
                expect(source.get_by_role('heading', name='Confirm your location')).to_be_visible()
                original_url = source.url
                pages = []
                for host in ('gm', 'gn'):
                    page = owner.new_page(); page.on('pageerror', lambda error: errors.append(str(error)))
                    login(page, host, 'alice', 'a1alice-permanent'); pages.append(page)
                extra = owner.new_page(); extra.goto('https://sec.language.test/chat'); pages.append(extra)
                source.close()  # The original tab closes with a real pending form.
                for page in pages:
                    page.bring_to_front(); page.evaluate('window.dispatchEvent(new Event("focus"))')
                    expect(page.locator('#account-activity')).to_be_visible()
                    expect(page.locator('#account-activity')).to_contain_text('Your secretary needs your answer')
                    expect(page.locator('#account-activity a')).to_have_attribute('href', original_url)
                    expect(page.locator('#account-activity a')).to_have_attribute('target', '_blank')
                    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                other = context(390); bob = other.new_page()
                login(bob, 'sec', 'bob', 'a1bob-temporary'); permanent(bob, 'bob')
                expect(bob.locator('#account-activity')).to_be_hidden()
                assert bob.evaluate("fetch('/api/activity').then(response => response.json())") == {'activity': []}
                page = pages[-1]
                for width in (1440, 390, 320):
                    page.set_viewport_size({'width': width, 'height': 900})
                    if page.locator('#prefs-menu').get_attribute('open') is None:
                        page.locator('#prefs-menu > summary').click()
                    page.locator('#website-language').select_option('zh-CN')
                    expect(page.locator('#account-activity')).to_contain_text('秘书需要你的回答')
                    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                    page.locator('#account-activity').screenshot(path=str(artifacts/f'waiting-{width}-zh-CN.png'))
                    page.locator('#website-language').select_option('en')
                    expect(page.locator('#account-activity')).to_contain_text('Your secretary needs your answer')
                page.route('**/api/activity', lambda route: route.fulfill(status=503, json={'error': 'Synthetic outage'}), times=1)
                page.evaluate('window.dispatchEvent(new Event("focus"))')
                expect(page.locator('#account-activity')).to_contain_text('Activity status is unavailable')
                expect(page.locator('#account-activity a')).to_have_attribute('href', original_url)
                (root/'activity-state').write_text('working')
                for page in pages:
                    page.bring_to_front(); page.evaluate('window.dispatchEvent(new Event("focus"))')
                    expect(page.locator('#account-activity')).to_contain_text('Your secretary is working')
                (root/'activity-state').write_text('idle')
                for page in pages:
                    page.bring_to_front(); page.evaluate('window.dispatchEvent(new Event("focus"))')
                    expect(page.locator('#account-activity')).to_be_hidden()
                    assert page.evaluate('localStorage.length === 0 && sessionStorage.length === 0')
                assert not errors, errors
                browser.close()
            print(json.dumps({'modelCalls': 0, 'subdomains': 3, 'observerTabs': 3, 'closedOriginalTab': True,
                'waitingWorkingIdle': True, 'ownerIsolation': True, 'outageKeepsLink': True,
                'widths': [1440, 390, 320], 'languages': ['en', 'zh-CN'], 'pageErrors': 0}))
        finally:
            process.terminate(); process.communicate(timeout=5)


if __name__ == '__main__':
    if '--serve' in sys.argv: fixture(Path(sys.argv[-1]))
    else: run(Path(sys.argv[1]))
