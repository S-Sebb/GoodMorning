"""Secretary switches edition colours in account time without losing page state."""
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[2]


def main():
    artifacts = Path(sys.argv[1])
    artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    checks = []
    with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='gm-chat-theme-') as directory:
        root = Path(directory)
        (root / 'profile.md').write_text('city: Shanghai\ntimezone: Asia/Shanghai\nnews_country: CN\nsecretary_language: English\n')
        profile = (root / 'profile.md').read_bytes()
        process = subprocess.Popen([sys.executable, str(REPO / 'tests/test_briefing_chat.py'), '--serve-fixture', directory],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        address = process.stdout.readline().strip().removeprefix('Private live viewer: ')
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                for width in (390, 1440):
                    page = browser.new_page(viewport={'width': width, 'height': 1000},
                                            timezone_id='America/Los_Angeles', reduced_motion='reduce')
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.clock.install(time=datetime.fromisoformat('2026-10-10T21:00:00+00:00'))
                    page.goto(address + '/chat')
                    page.clock.set_system_time(datetime.fromisoformat('2026-10-10T21:59:59+00:00'))
                    page.evaluate("window.dispatchEvent(new Event('focus'))")
                    expect(page.locator('html')).to_have_attribute('data-edition', 'gn')
                    page.locator('#chat-text').fill('Keep this unsent draft across theme changes.')
                    page.locator('[data-avatar-toggle]').click()
                    url = page.url
                    page.clock.run_for(1100)
                    expect(page.locator('html')).to_have_attribute('data-edition', 'gm')
                    expect(page.locator('#chat-text')).to_have_value('Keep this unsent draft across theme changes.')
                    expect(page.locator('.avatar-menu')).to_be_visible()
                    page.keyboard.press('Escape')
                    page.screenshot(path=str(artifacts / f'secretary-day-{width}.png'), full_page=True)

                    page.clock.set_system_time(datetime.fromisoformat('2026-10-11T09:59:59+00:00'))
                    page.evaluate("window.dispatchEvent(new Event('focus'))")
                    expect(page.locator('html')).to_have_attribute('data-edition', 'gm')
                    page.clock.run_for(1100)
                    expect(page.locator('html')).to_have_attribute('data-edition', 'gn')
                    expect(page.locator('#chat-text')).to_have_value('Keep this unsent draft across theme changes.')
                    page.screenshot(path=str(artifacts / f'secretary-night-{width}.png'), full_page=True)

                    # The browser's local hour is night, but this account's local hour is 13:00.
                    page.clock.set_system_time(datetime.fromisoformat('2026-10-11T05:00:00+00:00'))
                    page.evaluate("window.dispatchEvent(new Event('focus'))")
                    expect(page.locator('html')).to_have_attribute('data-edition', 'gm')
                    assert page.url == url
                    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                    assert not errors, errors
                    checks.append({'width': width, 'accountTimezone': 'Asia/Shanghai', 'browserTimezone': 'America/Los_Angeles',
                                   'sixAndEighteenBoundaries': True, 'draftPreserved': True, 'reloads': 0, 'pageErrors': 0})
                    page.close()
                browser.close()
            assert (root / 'profile.md').read_bytes() == profile
            assert not (root / 'browser-chats/chats.json').exists()
        finally:
            process.terminate()
            process.communicate(timeout=5)
    report = {'modelCalls': 0, 'checks': checks, 'profileUnchanged': True}
    (artifacts / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
