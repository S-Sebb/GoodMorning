"""Rendered mode switch and conversation flow using an isolated synthetic agent."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright, expect


def check_motion(browser, address, artifacts):
    checks = []
    for width, motion in ((1440, 'no-preference'), (390, 'no-preference'), (390, 'reduce')):
        page = browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion=motion)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        pending = []
        queue = []
        messages = [{'id': 'user-1', 'role': 'user', 'text': 'Plan a calm day'}]
        status = {'mode': 'secretary', 'state': 'running', 'language': 'en', 'label': 'Your secretary is working',
                  'messages': messages, 'forms': [], 'permissions': []}
        page.route('**/api/chats', lambda route: pending.append(route) if route.request.method == 'POST'
                   else route.fulfill(json={'defaultMode': 'secretary', 'connected': True, 'chats': []}))
        page.route('**/api/chats/*', lambda route: route.fulfill(json=status))
        page.route('**/api/queue', lambda route: route.fulfill(json={'queue': queue, 'depth': len(queue)}))
        page.add_init_script("""window.messageEntrances = 0; window.messageFrames = [];
            document.addEventListener('animationstart', event => {
                if (event.animationName !== 'chat-message-enter' || !event.target.matches('.chat-message')) return;
                window.messageEntrances++;
                const frames = []; window.messageFrames.push(frames);
                const sample = () => {
                    frames.push(Number(getComputedStyle(event.target).opacity));
                    if (event.target.getAnimations().length) requestAnimationFrame(sample);
                };
                requestAnimationFrame(sample);
            });""")
        page.goto(address + '/chat?mode=secretary')
        expect(page.get_by_role('button', name='Start conversation', exact=True)).to_be_enabled()
        page.get_by_label('Your message', exact=True).fill('Plan a calm day')
        with page.expect_request(lambda request: request.method == 'POST' and request.url.endswith('/api/chats')):
            page.get_by_role('button', name='Start conversation', exact=True).click()
        expect(page.locator('#chat-status')).to_have_text('Sending your message')
        expect(page.locator('.chat-activity-dots')).to_be_visible()
        assert page.locator('.chat-activity-dots').get_attribute('aria-hidden') == 'true'
        dot_animation = page.locator('.chat-activity-dots span').first.evaluate(
            "node => getComputedStyle(node).animationName")
        assert dot_animation == ('none' if motion == 'reduce' else 'chat-activity')
        pending.pop().fulfill(json={'accepted': True})
        expect(page.locator('#chat-status')).to_have_text('Your secretary is working')
        expect(page.get_by_role('log')).to_contain_text('Plan a calm day')
        page.screenshot(path=str(artifacts / f'chat-working-{width}-{motion}.png'), full_page=True)
        messages.append({'id': 'assistant-1', 'role': 'assistant', 'text': 'Let’s leave room to breathe.\nOne priority at a time.'})
        status.update(state='idle', label='Ready for your reply')
        page.evaluate('pollChat()')
        expect(page.get_by_role('log')).to_contain_text('One priority at a time.')
        expect(page.locator('.chat-activity-dots')).to_be_hidden()
        expect(page.get_by_role('button', name='Send reply', exact=True)).to_be_enabled()
        page.evaluate("""async () => {
            await Promise.all([...document.querySelectorAll('.chat-message')].flatMap(
                node => node.getAnimations().map(animation => animation.finished)));
        }""")
        entrances = page.evaluate('window.messageEntrances')
        assert entrances == (0 if motion == 'reduce' else 2), entrances
        frames = page.evaluate('window.messageFrames')
        if motion != 'reduce':
            assert all(any(0 < opacity < 1 for opacity in samples) for samples in frames), frames
        assert page.locator('.message-enter').count() == 0
        page.evaluate("messageSignature = ''; pollChat()")
        assert page.evaluate('window.messageEntrances') == entrances
        assert page.locator('.chat-message').count() == 2
        page.reload()
        expect(page.get_by_role('log')).to_contain_text('One priority at a time.')
        assert page.locator('.message-enter').count() == 0
        assert page.evaluate('window.messageEntrances') == 0

        # Queued requests stay quiet, then show activity when the queue releases them.
        page.get_by_role('button', name='New conversation', exact=True).click()
        page.get_by_label('Your message', exact=True).fill('A queued request')
        with page.expect_request(lambda request: request.method == 'POST' and request.url.endswith('/api/chats')):
            page.get_by_role('button', name='Start conversation', exact=True).click()
        queued_id = pending[0].request.post_data_json['id']
        queue.append({'work': 'chat', 'chat': queued_id, 'position': 1})
        pending.pop().fulfill(json={'queued': True, 'position': 1, 'depth': 1})
        expect(page.locator('#chat-status')).to_contain_text('You are #1 in line')
        expect(page.locator('.chat-activity-dots')).to_be_hidden()
        queue.clear()
        status.update(state='running', label='Your secretary is working')
        page.evaluate('pollQueue()')
        expect(page.locator('#chat-status')).to_have_text('Your secretary is working')
        expect(page.locator('.chat-activity-dots')).to_be_visible()
        page.get_by_role('button', name='New conversation', exact=True).click()
        expect(page.locator('#chat-status')).to_be_empty()

        # A rejected send stops activity and preserves the unsent draft.
        page.get_by_label('Your message', exact=True).fill('Keep this draft')
        with page.expect_request(lambda request: request.method == 'POST' and request.url.endswith('/api/chats')):
            page.get_by_role('button', name='Start conversation', exact=True).click()
        pending.pop().fulfill(status=400, json={'error': 'Synthetic rejection'})
        expect(page.get_by_role('alert')).to_have_text('Synthetic rejection')
        expect(page.locator('.chat-activity-dots')).to_be_hidden()
        expect(page.get_by_label('Your message', exact=True)).to_have_value('Keep this draft')
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        assert not errors, errors
        checks.append({'width': width, 'motion': motion, 'messageEntrances': entrances,
                       'sampledAnimationFrames': [len(samples) for samples in frames],
                       'immediateFeedback': True, 'queueRelease': True, 'historyReplay': False, 'pageErrors': 0})
        page.close()
    return checks


def main():
    artifacts = Path(sys.argv[1]); artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    results = []
    with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='gm-chat-browser-') as directory:
        root = Path(directory)
        (root / 'preserved-record.txt').write_text('Preserved synthetic evidence')
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve().parents[1] / 'test_briefing_chat.py'),
                                    '--serve-fixture', directory], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        address = process.stdout.readline().strip().removeprefix('Private live viewer: ')
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                motion_checks = check_motion(browser, address, artifacts)
                for width in (1440, 768, 390, 320):
                    page = browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
                    errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
                    if width == 1440:
                        for kind in ('gm','gn'):
                            page.goto(address + '/' + kind + '.html')
                            expect(page.get_by_role('link',name='Initialize my secretary')).to_be_visible()
                            expect(page.locator('#generate')).to_have_count(0)
                            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                            page.screenshot(path=str(artifacts/(kind+'-initialize-button-desktop.png')),full_page=True)
                        page.get_by_role('link',name='Initialize my secretary').click()
                        expect(page.get_by_role('radio',name='Initialize',exact=True)).to_have_attribute('aria-checked','true')
                        assert not list((root/'browser-chats').glob('*.context.json'))
                    page.goto(address + '/chat')
                    modes = page.get_by_role('radiogroup', name='Secretary mode')
                    expect(modes.get_by_role('radio')).to_have_count(4)
                    initial = 'Initialize' if width == 1440 else 'Secretary'
                    expect(modes.get_by_role('radio', name=initial, exact=True)).to_have_attribute('aria-checked', 'true')
                    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                    if width == 1440:
                        page.screenshot(path=str(artifacts / 'initialization-desktop.png'), full_page=True)
                        page.get_by_role('button', name='Start initialization', exact=True).click()
                        expect(page.get_by_role('heading', name='Confirm your location')).to_be_visible()
                        page.get_by_placeholder('Or write your own answer').fill('London, please')
                        with page.expect_response('**/api/chats/*'):
                            page.evaluate('pollChat()')
                        expect(page.get_by_placeholder('Or write your own answer')).to_have_value('London, please')
                        page.reload()
                        expect(page.get_by_role('heading', name='Confirm your location')).to_be_visible()
                        page.get_by_text('London', exact=True).click()
                        page.get_by_role('button', name='Send answer', exact=True).click()
                        expect(page.get_by_role('heading', name='Permission needed')).to_be_visible()
                        page.get_by_role('button', name='Allow once', exact=True).click()
                        expect(page.get_by_role('button', name='Send reply', exact=True)).to_be_enabled()
                        expect(page.get_by_role('log')).to_contain_text('Synthetic setup saved')
                        page.get_by_role('button', name='New conversation', exact=True).click()
                        expect(modes.get_by_role('radio', name='Secretary', exact=True)).to_have_attribute('aria-checked', 'true')
                    # Mode switch changes only the draft, not the saved conversation.
                    modes.get_by_role('radio', name='To-do', exact=True).click()
                    page.get_by_label('Your message', exact=True).fill('Capture a synthetic task')
                    modes.get_by_role('radio', name='Eureka', exact=True).click()
                    page.get_by_label('Your message', exact=True).fill('Capture a synthetic idea')
                    modes.get_by_role('radio', name='To-do', exact=True).click()
                    expect(page.get_by_label('Your message', exact=True)).to_have_value('Capture a synthetic task')
                    page.get_by_role('button', name='Save to-do', exact=True).click()
                    expect(page.get_by_role('log')).to_contain_text('Synthetic reply')
                    assert page.get_by_role('log').locator('img').count() == 0
                    expect(page.get_by_role('button', name='Send reply', exact=True)).to_be_enabled()
                    chat_url = page.url
                    page.reload()
                    expect(modes.get_by_role('radio', name='To-do', exact=True)).to_have_attribute('aria-checked', 'true')
                    expect(page.get_by_role('log')).to_contain_text('Capture a synthetic task')
                    page.get_by_label('Your message', exact=True).fill('A synthetic clarification')
                    page.get_by_role('button', name='Send reply', exact=True).click()
                    expect(page.get_by_role('log')).to_contain_text('A synthetic clarification')
                    assert page.url == chat_url
                    page.screenshot(path=str(artifacts / ('conversation-' + str(width) + '.png')), full_page=True)
                    if width == 1440:
                        # A stale status response must not strand the newly selected conversation.
                        paused = []
                        page.route('**/api/chats/*', lambda route: paused.append(route), times=1)
                        with page.expect_request('**/api/chats/*'):
                            page.evaluate('void pollChat()')
                        modes.get_by_role('radio', name='Eureka', exact=True).click()
                        page.get_by_label('Your message', exact=True).fill('Synthetic idea while a status request is pending')
                        with page.expect_response('**/api/chats'):
                            page.get_by_role('button', name='Save idea', exact=True).click()
                        assert len(paused) == 1
                        paused[0].continue_()
                        expect(page.get_by_role('log')).to_contain_text('Synthetic idea while a status request is pending')
                    page.get_by_role('button', name='New conversation', exact=True).click()
                    expect(modes.get_by_role('radio', name='Secretary', exact=True)).to_have_attribute('aria-checked', 'true')
                    page.goto(address + '/chat?mode=initialize')
                    expect(modes.get_by_role('radio',name='Initialize',exact=True)).to_have_attribute('aria-checked','true')
                    page.goto(address + '/gm.html')
                    expect(page.locator('#generate')).to_be_visible()
                    expect(page.locator('#initialize')).to_have_count(0)
                    page.goto(address + '/chat')
                    modes.get_by_role('radio', name='Secretary', exact=True).focus()
                    page.keyboard.press('ArrowRight')
                    expect(modes.get_by_role('radio', name='To-do', exact=True)).to_be_focused()
                    page.get_by_text('Previous conversations', exact=True).click()
                    expect(page.locator('#chat-history a').first).to_be_visible()
                    assert page.evaluate('localStorage.length === 0 && sessionStorage.length === 0')
                    assert not errors, errors
                    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                    results.append({'width': width, 'overflow': False, 'pageErrors': 0, 'refresh': 'same conversation',
                                    'modeSwitch': 'pass', 'keyboard': 'pass', 'privateBrowserStorage': 'unused'})
                    page.close()
                browser.close()
            assert (root / 'preserved-record.txt').read_text() == 'Preserved synthetic evidence'
        finally:
            process.terminate(); process.communicate(timeout=5)
    report = {'modelCalls': 0, 'agent': 'synthetic', 'setup': 'mock saved, default changed', 'checks': results,
              'motion': motion_checks}
    (artifacts / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
