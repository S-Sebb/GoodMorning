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
                        page.goto(address + ('/chat?mode=todo' if width == 320 else '/chat?mode=initialize'))
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
                        expect(page.get_by_role('radio')).to_have_count(1)
                        expect(page.locator('[data-mode="initialize"]')).to_have_attribute('aria-checked', 'true')
                        page.locator('#mode-help').click()
                        expect(page.locator('[data-mode-guide="initialize"]')).to_be_visible()
                        expect(page.locator('[data-mode-guide="secretary"]')).to_be_hidden()
                        page.locator('#mode-help').click()
                        page.screenshot(path=str(artifacts / f'new-user-{width}-{language}.png'), full_page=True)

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
                # A language switch refreshes history, which restores the server's connection state.
                with page.expect_response('**/api/chats'):
                    page.locator('#website-language').select_option('zh-CN')
                expect(page.locator('#chat-send')).to_have_text('开始初始化')
                page.evaluate('chatConfig.connected = false; composeState()')
                expect(page.locator('#chat-send')).to_be_disabled()
                expect(page.locator('#chat-text')).to_be_hidden()
                page.close()

                # Completion changes the options without interrupting the setup conversation.
                (root / 'website-language.json').write_text(json.dumps({'language': 'en'}))
                page = browser.new_page(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
                page.goto(address + '/chat')
                page.get_by_role('button', name='Start initialization', exact=True).click()
                page.locator('#chat-questions input[type="radio"]').first.check()
                page.locator('#chat-questions button[type="submit"]').click()
                page.get_by_role('button', name='Allow once', exact=True).click()
                expect(page.get_by_role('radio')).to_have_count(3)
                assert page.locator('[data-mode]').evaluate_all('(buttons) => buttons.map(button => button.dataset.mode)') == ['secretary', 'todo', 'eureka']
                expect(page.get_by_role('log')).to_contain_text('Synthetic setup saved')
                expect(page.locator('#chat-text')).to_be_enabled()
                setup_url = page.url
                page.locator('#new-conversation').click()
                expect(page.locator('[data-mode="secretary"]')).to_have_attribute('aria-checked', 'true')
                page.locator('#chat-text').fill('Keep my draft')
                page.locator('[data-mode="todo"]').click()
                page.locator('[data-mode="secretary"]').click()
                expect(page.locator('#chat-text')).to_have_value('Keep my draft')
                page.locator('[data-mode="secretary"]').press('ArrowRight')
                expect(page.locator('[data-mode="todo"]')).to_be_focused()
                page.locator('[data-mode="todo"]').press('End')
                expect(page.locator('[data-mode="eureka"]')).to_be_focused()
                page.goto(setup_url)
                expect(page.get_by_role('log')).to_contain_text('Synthetic setup saved')
                expect(page.get_by_role('radio')).to_have_count(3)
                expect(page.locator('#chat-text')).to_be_enabled()
                page.close()

                for width in (1440, 390, 320):
                    for language in ('en', 'zh-CN'):
                        (root / 'website-language.json').write_text(json.dumps({'language': language}))
                        page = browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
                        page.goto(address + '/chat?mode=initialize')
                        expect(page.get_by_role('radio')).to_have_count(3)
                        expect(page.locator('[data-mode="secretary"]')).to_have_attribute('aria-checked', 'true')
                        expect(page.locator('#chat-text')).to_be_visible()
                        page.locator('#mode-help').click()
                        expect(page.locator('[data-mode-guide="initialize"]')).to_be_hidden()
                        expect(page.locator('[data-mode-guide="secretary"]')).to_be_visible()
                        page.locator('#mode-help').click()
                        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                        widths = page.locator('[data-mode]').evaluate_all('(buttons) => buttons.map(button => button.getBoundingClientRect().width)')
                        assert max(widths) - min(widths) < 1
                        page.screenshot(path=str(artifacts / f'ready-user-{width}-{language}.png'), full_page=True)
                        page.close()
                browser.close()
            assert preserved.read_text() == 'Preserved synthetic records'
        finally:
            process.terminate()
            process.communicate(timeout=5)
    report = {'modelCalls': 0, 'checks': checks, 'liveLanguageSwitch': True, 'disconnectedButtonDisabled': True,
              'readyUserOptions': ['secretary', 'todo', 'eureka'], 'liveSetupTransition': True,
              'oldSetupConversationPreserved': True, 'unavailableModeFallback': True, 'draftsAndKeyboard': True}
    (artifacts / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
