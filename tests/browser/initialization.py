"""Initialization starts with a localized button, then restores normal replies."""
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
    with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='gm-initialization-') as directory:
        root = Path(directory)
        preserved = root / 'preserved-record.txt'
        preserved.write_text('Preserved synthetic records')
        process = subprocess.Popen(
            [sys.executable, str(REPO / 'tests/test_briefing_chat.py'), '--serve-fixture', directory],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        address = process.stdout.readline().strip().removeprefix('Private live viewer: ')
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                for width in (1440, 390, 320):
                    for language, label, message in (
                        ('en', 'Start initialization', 'Start the initialization process with me.'),
                        ('zh-CN', '开始初始化', '请和我一起开始初始化流程。'),
                    ):
                        (root / 'website-language.json').write_text(json.dumps({'language': language}))
                        page = browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(address + '/chat?mode=initialize')
                        start = page.get_by_role('button', name=label, exact=True)
                        text = page.locator('#chat-text')
                        expect(start).to_be_visible()
                        expect(start).to_be_enabled()
                        expect(start.locator('.chat-send-label')).to_have_text(label)
                        expect(text).to_be_hidden()
                        expect(text).to_be_disabled()
                        expect(page.locator('#chat-attach')).to_be_hidden()
                        assert page.get_by_role('textbox').count() == 0
                        assert page.evaluate('document.activeElement.id !== "chat-text"')
                        assert start.bounding_box()['width'] == page.locator('.chat-input-row').bounding_box()['width']
                        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                        page.locator('#conversation').screenshot(path=str(artifacts / f'start-{width}-{language}.png'))

                        # Mode switches still preserve normal unsent drafts.
                        page.locator('[data-mode="secretary"]').click()
                        expect(text).to_be_visible()
                        text.fill('Keep this draft')
                        page.locator('[data-mode="initialize"]').click()
                        expect(text).to_be_hidden()
                        page.locator('[data-mode="secretary"]').click()
                        expect(text).to_have_value('Keep this draft')
                        page.locator('[data-mode="initialize"]').click()

                        # A rejected request leaves the visible button available for a retry.
                        page.route('**/api/chats', lambda route: route.fulfill(status=429, json={'error': 'Synthetic busy'}), times=1)
                        start.click()
                        expect(page.locator('#chat-error')).to_have_text('Synthetic busy')
                        expect(start).to_be_enabled()
                        expect(text).to_be_hidden()
                        with page.expect_request(lambda request: request.method == 'POST' and request.url.endswith('/api/chats')) as sent:
                            start.click()
                        assert sent.value.post_data_json['mode'] == 'initialize'
                        assert sent.value.post_data_json['text'] == message
                        expect(page.get_by_role('heading', name='Confirm your location')).to_be_visible()
                        expect(page.get_by_role('log')).to_contain_text(message)
                        expect(text).to_be_visible()
                        page.locator('#chat-questions input[type="radio"]').first.check()
                        page.locator('#chat-questions button[type="submit"]').click()
                        decline = page.get_by_role('button', name='Decline' if language == 'en' else '拒绝', exact=True)
                        expect(decline).to_be_visible()
                        decline.click()
                        expect(text).to_be_enabled()
                        expect(page.locator('#chat-attach')).to_be_visible()
                        text.fill('My follow-up')
                        with page.expect_request('**/api/chats/*/messages') as reply:
                            page.locator('#chat-send').click()
                        assert reply.value.post_data_json['text'] == 'My follow-up'
                        page.reload()
                        expect(text).to_be_visible()
                        expect(text).to_be_enabled()
                        assert not errors, errors
                        checks.append({'width': width, 'language': language, 'localizedMessage': True,
                                       'buttonReplacesInput': True, 'retry': True, 'repliesAndReload': True})
                        page.close()

                page = browser.new_page()
                page.goto(address + '/chat?mode=initialize')
                page.locator('#prefs-menu > summary').click()
                page.locator('#website-language').select_option('en')
                expect(page.locator('#chat-send')).to_have_text('Start initialization')
                page.locator('#website-language').select_option('zh-CN')
                expect(page.locator('#chat-send')).to_have_text('开始初始化')
                page.evaluate('chatConfig.connected = false; composeState()')
                expect(page.locator('#chat-send')).to_be_disabled()
                expect(page.locator('#chat-text')).to_be_hidden()
                page.close()
                browser.close()
            assert preserved.read_text() == 'Preserved synthetic records'
        finally:
            process.terminate()
            process.communicate(timeout=5)
    report = {'modelCalls': 0, 'checks': checks, 'liveLanguageSwitch': True, 'disconnectedButtonDisabled': True}
    (artifacts / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
