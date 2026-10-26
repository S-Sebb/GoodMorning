"""About me through the real gateway with synthetic accounts: the Account menu entry, in-place edits saved to
the profile, switches, chat-only fields, both languages, phone and desktop, and another account's isolation."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect

REPO = Path(__file__).resolve().parents[2]
EXTRA = '''secretary_name: "Mochi"
user_name: ""
work_days: "Monday to Friday"
news_additional_countries: "JP"
anime_updates: "true"
anime_source: "anilist"
anime_account: "alicewatches"
anime_titles: "1, 2"
'''


def main():
    artifacts = Path(sys.argv[1]); artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='gm-about-') as directory:
        process = subprocess.Popen([sys.executable, str(REPO/'tests/browser/language.py'), '--serve', directory],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            while True:
                line = process.stdout.readline()
                if line.startswith('{'):
                    settings = json.loads(line); break
                if not line: raise RuntimeError('Synthetic gateway fixture did not start.')
            profile = Path(settings['runtimes']['alice'])/'profile.md'
            profile.write_text(profile.read_text() + EXTRA)
            errors = []
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                def context(width):
                    result = browser.new_context(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
                    def forward(route):
                        parsed = urlsplit(route.request.url)
                        headers = {**route.request.all_headers(), 'Host': parsed.hostname, 'X-Forwarded-Proto': 'https', 'X-Real-IP': '192.0.2.1'}
                        response = route.fetch(url=settings['gateway']+parsed.path+('?' + parsed.query if parsed.query else ''),
                                               headers=headers, max_redirects=0)
                        route.fulfill(response=response)
                    result.route('https://*.language.test/**', forward)
                    return result

                def sign_in(page, name):
                    page.goto('https://sec.language.test/login')
                    page.locator('input[name=username]').fill(name)
                    page.locator('#password-password').fill('a1' + name + '-temporary')
                    with page.expect_response('**/api/auth/login') as signed:
                        page.locator('#account-form button[type=submit]').click()
                    assert signed.value.status == 200, signed.value.json()
                    expect(page.get_by_role('heading', name='Change password', exact=True)).to_be_visible()
                    expect(page.locator('#site-patch-note')).to_be_visible()
                    page.locator('#patch-note-dismiss').click()
                    page.wait_for_load_state('networkidle')
                    for field, value in (('current', 'temporary'), ('replacement', 'permanent'), ('repeat', 'permanent')):
                        page.locator(f'input[name={field}]').fill('a1' + name + '-' + value)
                        expect(page.locator(f'input[name={field}]')).to_have_value('a1' + name + '-' + value)
                    with page.expect_response('**/api/auth/password') as changed:
                        page.locator('#account-form button[type=submit]').click()
                    assert changed.value.status == 200, changed.value.json()
                    expect(page.locator('#chat-compose')).to_be_visible()

                def no_overflow(page):
                    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')

                phone = context(390).new_page()
                phone.on('pageerror', lambda error: errors.append(str(error)))
                sign_in(phone, 'alice')
                phone.locator('#account-menu > summary').click()
                link = phone.locator('#account-menu #about-me-link')
                expect(link).to_be_visible()
                phone.screenshot(path=str(artifacts/'account-390.png'))
                link.click()
                expect(phone).to_have_url('https://sec.language.test/about-me')
                expect(phone.get_by_role('heading', name='About me', exact=True)).to_be_visible()
                expect(phone.locator('[data-countries]')).to_have_text('United Kingdom and Japan')
                expect(phone.locator('[data-field="anime_updates"] .about-details')).to_contain_text('Your watching list and 2 more shows')
                assert 'alicewatches' not in phone.locator('main').inner_text()
                no_overflow(phone)

                # Simple fields save in place; the profile keeps every other line.
                before = profile.read_text()
                row = phone.locator('[data-field="user_name"]')
                row.get_by_role('button', name='Edit').click()
                row.get_by_role('textbox', name='What your secretary calls you').fill('Ally')
                row.get_by_role('button', name='Save').click()
                expect(row.locator('.about-feedback')).to_have_text('Saved. Your secretary will use this from now on.')
                expect(row.locator('.about-value')).to_have_text('Ally')
                assert profile.read_text() == before.replace('user_name: ""', 'user_name: "Ally"')
                row = phone.locator('[data-field="work_days"]')
                row.get_by_role('button', name='Edit').click()
                row.get_by_role('textbox').fill('Weekends')
                row.get_by_role('textbox').press('Escape')
                expect(row.locator('.about-value')).to_have_text('Monday to Friday')
                row = phone.locator('[data-field="secretary_name"]')
                row.get_by_role('button', name='Edit').click()
                phone.evaluate("() => { const input = document.querySelector('[data-field=secretary_name] input'); input.maxLength = 99; input.value = '!!!'; }")
                row.get_by_role('button', name='Save').click()
                expect(row.locator('.about-feedback')).to_have_text('Not saved. Include at least one letter or number.')
                row.get_by_role('button', name='Cancel').click()
                assert 'secretary_name: "Mochi"' in profile.read_text()

                # Switches turn a set-up extra off and on; never-set-up extras and checked fields have no switch or Edit.
                switch = phone.get_by_role('switch', name='New episodes')
                expect(switch).to_have_attribute('aria-checked', 'true')
                switch.click()
                expect(switch).to_have_attribute('aria-checked', 'false')
                assert 'anime_updates: "false"' in profile.read_text() and 'anime_titles: "1, 2"' in profile.read_text()
                switch.click()
                expect(switch).to_have_attribute('aria-checked', 'true')
                phone.get_by_role('switch', name='Weekly letter').click()
                expect(phone.get_by_role('switch', name='Weekly letter')).to_have_attribute('aria-checked', 'false')
                assert 'weekly_letter: "false"' in profile.read_text()
                expect(phone.get_by_role('switch', name='Stocks')).to_have_count(0)
                expect(phone.locator('#about-day .about-row').first.locator('.about-edit')).to_have_count(0)  # City changes in chat.
                phone.screenshot(path=str(artifacts/'about-390.png'), full_page=True)

                # Change in chat opens the quick chat with an unsent starter line.
                phone.locator('#about-day .about-chat').first.click()
                expect(phone.locator('#quick-chat-text')).to_have_value('I’d like to change my city.')
                phone.locator('#quick-chat-text').fill('')
                phone.locator('#quick-chat-minimize').click()

                # The website language switch translates the page and country names in place.
                phone.locator('#account-menu > summary').click()
                phone.locator('#website-language').select_option('zh-CN')
                expect(phone.locator('html')).to_have_attribute('lang', 'zh-CN')
                expect(phone.get_by_role('heading', name='关于我', exact=True)).to_be_visible()
                expect(phone.locator('[data-countries]')).to_have_text('英国和日本')
                phone.locator('#account-menu > summary').click()
                phone.reload()
                expect(phone.locator('.about-intro p')).to_have_text('秘书对你的了解都在这里。它会照这些安排你的每一天，写你的简报。')
                no_overflow(phone)
                phone.screenshot(path=str(artifacts/'about-390-zh.png'), full_page=True)

                desktop = context(1440).new_page()
                desktop.on('pageerror', lambda error: errors.append(str(error)))
                sign_in(desktop, 'bob')
                desktop.goto('https://sec.language.test/about-me')
                main_text = desktop.locator('main').inner_text()
                assert 'Ally' not in main_text and 'Mochi' not in main_text, main_text
                expect(desktop.locator('main')).to_have_attribute('data-readonly', '')
                expect(desktop.locator('.about-edit:visible, .about-switch:visible')).to_have_count(0)  # Bob has no profile yet.
                assert not (Path(settings['runtimes']['bob'])/'profile.md').exists()
                no_overflow(desktop)
                desktop.screenshot(path=str(artifacts/'about-1440-before-setup.png'), full_page=True)
                alice = context(1440).new_page()
                alice.on('pageerror', lambda error: errors.append(str(error)))
                alice.goto('https://sec.language.test/login')
                alice.locator('input[name=username]').fill('alice')
                alice.locator('#password-password').fill('a1alice-permanent')
                alice.locator('#account-form button[type=submit]').click()
                expect(alice.locator('#chat-compose')).to_be_visible()
                alice.goto('https://sec.language.test/about-me')
                expect(alice.locator('[data-field="user_name"] .about-value')).to_have_text('Ally')
                no_overflow(alice)
                alice.screenshot(path=str(artifacts/'about-1440-zh.png'), full_page=True)
                assert not errors, errors
                browser.close()
            report = {'ok': True, 'artifacts': str(artifacts)}
            (artifacts/'result.json').write_text(json.dumps(report, indent=2)); print(json.dumps(report))
        finally:
            process.terminate(); process.communicate(timeout=5)


if __name__ == '__main__':
    main()
