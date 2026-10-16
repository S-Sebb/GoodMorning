"""Synthetic change cards, question forms, palette contrast and one-shot motion."""
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from playwright.sync_api import expect, sync_playwright
from chat_markdown import contrast

REPO = Path(__file__).resolve().parents[2]


def action(identifier, operation, target, text):
    return {'id': identifier, 'role': 'assistant', 'kind': 'action', 'text': text,
            'action': {'operation': operation, 'target': target}}


def main():
    artifacts = Path(sys.argv[1])
    artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    checks = []
    with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='gm-chat-actions-') as directory:
        process = subprocess.Popen([sys.executable, str(REPO / 'tests/test_briefing_chat.py'), '--serve-fixture', directory],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        address = process.stdout.readline().strip().removeprefix('Private live viewer: ')
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                for width in (1440, 390, 320):
                    page = browser.new_page(viewport={'width': width, 'height': 1100}, reduced_motion='reduce')
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.clock.set_system_time(datetime.fromisoformat('2026-10-13T10:00:00+00:00'))
                    status = {'mode': 'secretary', 'state': 'idle', 'label': 'Ready for your reply', 'language': 'en',
                              'forms': [], 'permissions': [], 'messages': [
                        {'id': 'reply', 'role': 'assistant', 'text': 'A little room for your plans.'},
                        {'id': 'question', 'role': 'assistant', 'kind': 'question', 'text': 'Which afternoon works for you?'},
                        {'id': 'answer', 'role': 'user', 'kind': 'answer', 'text': 'Thursday, after lunch.'},
                        action('add', 'added', 'event', 'Tea with Sam · Thursday, 14:00'),
                        action('edit', 'updated', 'task', 'Prepare the final slides'),
                        action('cancel', 'cancelled', 'event', 'Friday check-in'),
                        action('done', 'completed', 'task', 'Pick up the library books'),
                        action('approve', 'approved', 'event', 'Team lunch'),
                        action('decline', 'declined', 'event', 'Duplicate invitation'),
                        action('idea', 'added', 'idea', 'A tiny garden on the balcony'),
                        action('draft', 'added', 'draft', 'Weekend walk · time to confirm'),
                        action('unsafe', 'updated', 'record', '<img src=x onerror="window.executed=true">')
                    ]}
                    page.route('**/api/chats/*', lambda route: route.fulfill(json=status))
                    page.goto(address + '/chat?id=' + 'f' * 32)
                    expect(page.locator('[data-special="action"]')).to_have_count(9)
                    expect(page.locator('.chat-special-icon svg')).to_have_count(11)
                    expect(page.locator('[data-message="unsafe"] .message-text img')).to_have_count(0)
                    assert page.evaluate('window.executed !== true')
                    assert page.locator('.message-enter').count() == 0
                    for edition, scheme in (('gm', 'classic'), ('gm', 'warm'), ('gn', 'classic'), ('gn', 'starry'),
                                            ('gn', 'city-lights'), ('gn', 'midnight-violet')):
                        for language in ('en', 'zh-CN'):
                            page.evaluate('''([edition, scheme, language]) => {
                                document.documentElement.dataset.edition = edition;
                                document.documentElement.dataset[edition === 'gm' ? 'dayScheme' : 'nightScheme'] = scheme;
                                applyWebsiteLanguage(language);
                            }''', [edition, scheme, language])
                            expect(page.locator('[data-message="add"] .chat-special-label')).to_have_text(
                                'Event added' if language == 'en' else '已添加事项')
                            ratios = page.locator('#chat-messages [data-special]').evaluate_all('''nodes => nodes.flatMap(node => {
                                const background = getComputedStyle(node).backgroundColor;
                                return ['.message-text', '.chat-special-label'].map(selector => ({
                                    foreground: getComputedStyle(node.querySelector(selector)).color, background,
                                    selector, id: node.dataset.message}));
                            })''')
                            minimum = min(contrast(entry['foreground'], entry['background']) for entry in ratios)
                            assert minimum >= 4.5, (edition, scheme, width, language, minimum,
                                min(ratios, key=lambda entry: contrast(entry['foreground'], entry['background'])))
                            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                            assert page.locator('#chat-messages [data-special]').evaluate_all('''nodes => nodes.every(node =>
                                node.scrollWidth <= node.clientWidth + 1)''')
                            checks.append({'width': width, 'edition': edition, 'scheme': scheme, 'language': language,
                                           'minimumTextContrast': round(minimum, 2)})
                        if width in (1440, 390):
                            page.evaluate("applyWebsiteLanguage('en'); document.querySelector('#chat-scroll').scrollTop = 0")
                            page.screenshot(path=str(artifacts / f'actions-{edition}-{scheme}-{width}.png'), full_page=True)
                    # Keep typed answers when an unrelated permission arrives. Both get a clear badge.
                    status['forms'] = [{'id': 'when', 'title': 'Make a little space', 'fields': [
                        {'key': 'day', 'title': 'What day suits you?', 'type': 'string', 'required': True}]}]
                    status['state'] = 'waiting'
                    page.evaluate('pollChat()')
                    answer = page.get_by_role('textbox', name='What day suits you?')
                    expect(answer).to_be_visible()
                    answer.fill('Thursday afternoon')
                    status['permissions'] = [{'id': 'permission', 'action': 'Save the confirmed event', 'resources': ['Synthetic event only']}]
                    page.evaluate('pollChat()')
                    expect(page.locator('[data-special="permission"]')).to_be_visible()
                    expect(answer).to_have_value('Thursday afternoon')
                    expect(page.locator('.message-enter')).to_have_count(0)
                    assert not errors, errors
                    page.close()

                page = browser.new_page(viewport={'width': 1440, 'height': 1100})
                status = {'mode': 'secretary', 'state': 'idle', 'label': 'Ready for your reply', 'language': 'en',
                          'forms': [], 'permissions': [], 'messages': []}
                page.route('**/api/chats/*', lambda route: route.fulfill(json=status))
                page.goto(address + '/chat?id=' + 'e' * 32)
                expect(page.locator('#chat-status')).to_contain_text('Ready for your reply')
                status['messages'].append(action('new', 'added', 'task', 'Prepare slides'))
                page.evaluate('pollChat()')
                card = page.locator('[data-message="new"]')
                expect(card).to_have_class(re.compile('message-enter'))
                assert card.evaluate('node => node.getAnimations({subtree:true}).every(animation => animation.effect.getTiming().iterations === 1)')
                expect(card).not_to_have_class(re.compile('message-enter'))
                page.evaluate('pollChat()')
                expect(card).not_to_have_class(re.compile('message-enter'))
                # Reload and reduced motion must never replay the entrance.
                page.reload()
                expect(card).to_be_visible()
                expect(card).not_to_have_class(re.compile('message-enter'))
                status['state'] = 'waiting'
                status['forms'] = [{'id': 'new-question', 'title': 'A quick check', 'fields': [
                    {'key': 'day', 'title': 'Which day?', 'type': 'string'}]}]
                page.evaluate('pollChat()')
                question = page.locator('#chat-questions [data-special="question"]')
                expect(question).to_have_class(re.compile('message-enter'))
                expect(question).not_to_have_class(re.compile('message-enter'))
                page.evaluate('pollChat()')
                expect(question).not_to_have_class(re.compile('message-enter'))
                page.emulate_media(reduced_motion='reduce')
                status['messages'].append(action('reduced', 'updated', 'event', 'Tea at 15:00'))
                page.evaluate('pollChat()')
                expect(page.locator('[data-message="reduced"]')).to_be_visible()
                expect(page.locator('.message-enter')).to_have_count(0)
                # UI labels change locally even if the transcript connection fails.
                page.route('**/api/chats/*', lambda route: route.abort())
                page.evaluate("applyWebsiteLanguage('zh-CN')")
                expect(card.locator('.chat-special-label')).to_have_text('已添加待办')
                expect(question.locator('.chat-special-label')).to_have_text('想问问你')
                browser.close()
        finally:
            process.terminate()
            process.communicate(timeout=5)
    report = {'modelCalls': 0, 'paletteChecks': checks, 'motion': 'once, never on reload or reduced motion',
              'privateToolOutput': 'not requested', 'pendingDraftPreserved': True}
    (artifacts / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
