"""About me through the real gateway with synthetic accounts: the Account menu entry, in-place edits saved to
the profile, switches, chat-only fields, the secretary's memory note, both languages, phone and desktop, and another
account's isolation."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO/'src'))
from goodmorning.records import memory
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
            runtime = profile.parent
            memory.change(runtime, 0, note={'life': 'You have a dog, Mochi, and head home early to walk him.',
                                            'likes': 'You’d rather not have meetings before 10.',
                                            'lately': 'Training for the Shanghai marathon in March.'})
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
                expect(phone.get_by_role('heading', name='Mochi’s notes about you', exact=True)).to_be_visible()
                expect(phone.locator('[data-countries]')).to_have_text('United Kingdom and Japan')
                expect(phone.locator('[data-field="anime_updates"] .about-details')).to_contain_text('Your watching list and 2 more shows')
                assert 'alicewatches' not in phone.locator('main').inner_text()
                no_overflow(phone)

                # Simple fields save in place; the profile keeps every other line.
                before = profile.read_text()
                row = phone.locator('[data-field="user_name"]')
                row.get_by_role('button', name='Edit').click()
                row.get_by_role('textbox', name='What Mochi calls you').fill('Ally')
                row.get_by_role('button', name='Save').click()
                expect(row.locator('.about-feedback')).to_have_text('Saved! Mochi will remember this.')
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

                # The memory note is edited part by part in place; a text area keeps line breaks.
                memories = phone.locator('#about-memory')
                expect(memories.locator('[data-field^="memory:"] .about-value')).to_have_text(
                    ['You have a dog, Mochi, and head home early to walk him.', 'You’d rather not have meetings before 10.',
                     'Training for the Shanghai marathon in March.'])
                row = memories.locator('[data-field="memory:life"]')
                row.get_by_role('button', name='Edit').click()
                row.get_by_role('textbox').fill('You have two dogs, Mochi and Bean.\nYou walk them after work.')
                row.get_by_role('textbox').press('Enter')  # A new line, not a save.
                row.get_by_role('button', name='Save').click()
                expect(row.locator('.about-value')).to_have_text('You have two dogs, Mochi and Bean.\nYou walk them after work.')
                lately = memories.locator('[data-field="memory:lately"]')
                lately.get_by_role('button', name='Edit').click()
                lately.get_by_role('textbox').fill('')
                lately.get_by_role('button', name='Save').click()
                expect(lately.locator('.about-empty')).to_have_text('Nothing yet')
                assert memory.load(runtime)['note']['lately'] == ''
                switch = phone.get_by_role('switch', name='Remember things about me')
                switch.click()
                expect(switch).to_have_attribute('aria-checked', 'false')
                assert not memory.load(runtime)['enabled']
                switch.click()
                expect(switch).to_have_attribute('aria-checked', 'true')
                no_overflow(phone)
                memories.screenshot(path=str(artifacts/'memory-390.png'))
                # Public holidays are picked from the listed regions; the UK, Australia and Canada by nation, state or province.
                row = phone.locator('[data-field="holiday_countries"]')
                row.get_by_role('button', name='Edit').click()
                expect(row.get_by_role('group', name='Public holidays')).to_be_visible()
                row.get_by_role('checkbox', name='China').check()
                row.locator('fieldset', has_text='United Kingdom').get_by_role('checkbox', name='Scotland').check()
                no_overflow(phone)
                phone.screenshot(path=str(artifacts/'holidays-picker-390.png'), full_page=True)
                row.get_by_role('button', name='Save').click()
                expect(row.locator('.about-value')).to_have_text('China, United Kingdom — Scotland')
                assert 'holiday_countries: "CN, GB-SCT"' in profile.read_text()
                row.get_by_role('button', name='Edit').click()
                expect(row.get_by_role('checkbox', name='Scotland')).to_be_checked()
                row.get_by_role('button', name='Cancel').click()
                expect(row.locator('.about-value')).to_have_text('China, United Kingdom — Scotland')

                # A birthday is a month and day from two lists; 29 February is there, 31 April is not.
                row = phone.locator('[data-field="birthday"]')
                row.get_by_role('button', name='Edit').click()
                row.get_by_role('combobox', name='Month').select_option('04')
                expect(row.get_by_role('combobox', name='Day').locator('option')).to_have_count(31)  # 30 days and the empty choice.
                row.get_by_role('combobox', name='Month').select_option('02')
                row.get_by_role('combobox', name='Day').select_option('29')
                no_overflow(phone)
                phone.screenshot(path=str(artifacts/'birthday-picker-390.png'), full_page=True)
                row.get_by_role('button', name='Save').click()
                expect(row.locator('.about-value')).to_have_text('February 29')
                assert 'birthday: "02-29"' in profile.read_text()

                # Ask Mochi to change this opens the quick chat with an unsent starter line.
                phone.locator('#about-day .about-chat').first.click()
                expect(phone.locator('#quick-chat-text')).to_have_value('I’d like to change my city.')
                phone.locator('#quick-chat-text').fill('')
                phone.locator('#quick-chat-minimize').click()

                # The website language switch translates the page and country names in place.
                phone.locator('#account-menu > summary').click()
                phone.locator('#website-language').select_option('zh-CN')
                expect(phone.locator('html')).to_have_attribute('lang', 'zh-CN')
                expect(phone.get_by_role('heading', name='Mochi记得的你', exact=True)).to_be_visible()
                expect(phone.locator('[data-countries]')).to_have_text('英国和日本')
                expect(phone.locator('[data-holidays]')).to_have_text('中国、英国 — 苏格兰')
                expect(phone.locator('[data-birthday]')).to_have_text('2月29日')
                phone.locator('#account-menu > summary').click()
                phone.reload()
                expect(phone.locator('.about-greeting')).to_contain_text('嗨，Ally！')
                no_overflow(phone)
                phone.screenshot(path=str(artifacts/'about-390-zh.png'), full_page=True)

                desktop = context(1440).new_page()
                desktop.on('pageerror', lambda error: errors.append(str(error)))
                sign_in(desktop, 'bob')
                desktop.goto('https://sec.language.test/about-me')
                main_text = desktop.locator('main').inner_text()
                assert 'Ally' not in main_text and 'Mochi' not in main_text and 'marathon' not in main_text, main_text
                expect(desktop.locator('main')).to_have_attribute('data-readonly', '')
                expect(desktop.locator('.about-greeting')).to_contain_text('I don’t know much about you yet')
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
                # A new secretary name reloads the page so every line uses it.
                row = alice.locator('[data-field="secretary_name"]')
                row.locator('.about-edit').click()
                row.get_by_role('textbox').fill('Pip')
                row.get_by_role('textbox').press('Enter')
                expect(alice.get_by_role('heading', name='Pip记得的你', exact=True)).to_be_visible()
                expect(alice.locator('.about-chat').first).to_contain_text('让Pip来改')
                alice.wait_for_load_state('networkidle')
                alice.locator('#about-memory').screenshot(path=str(artifacts/'memory-1440-zh.png'))
                alice.once('dialog', lambda dialog: dialog.dismiss())
                alice.get_by_role('button', name='全部忘记').click()
                expect(alice.locator('#about-memory [data-field="memory:likes"] .about-value')).to_have_count(1)
                alice.once('dialog', lambda dialog: dialog.accept())
                alice.get_by_role('button', name='全部忘记').click()
                expect(alice.locator('#about-memory [data-field^="memory:"] .about-empty')).to_have_text(['还没写'] * 3)
                expect(alice.locator('#about-memory [data-field="forget"] .about-empty')).to_have_text('还没写。和Pip多聊聊，这份记忆就会慢慢长起来。')
                expect(alice.get_by_role('button', name='全部忘记')).to_be_hidden()
                assert not any(memory.load(runtime)['note'].values())
                assert 'Mochi' not in (runtime/'memory.json').read_text()
                assert not errors, errors
                browser.close()
            report = {'ok': True, 'artifacts': str(artifacts)}
            (artifacts/'result.json').write_text(json.dumps(report, indent=2)); print(json.dumps(report))
        finally:
            process.terminate(); process.communicate(timeout=5)


if __name__ == '__main__':
    main()
