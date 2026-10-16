"""Floating quick chat on desk pages: shared tab conversation, layout and setup gating. Synthetic, no model calls."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright, expect

REPO = Path(__file__).resolve().parents[2]
READY = 'secretary_language: English\ncity: London\ntimezone: Europe/London\nnews_country: GB\nsecretary_name: Mira\n'
WAITING = 'c' * 32
REPLY = 'Synthetic reply. Your text stays text'


def watch(page):
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    return errors


def chat_id(page):
    return page.evaluate('''() => {
      const key = Object.keys(sessionStorage).find(key => key.startsWith('goodmorning.chat.workspace.'));
      return key && JSON.parse(sessionStorage.getItem(key)).chat;
    }''')


def age_absence(page, milliseconds):
    page.evaluate('''milliseconds => {
      const key = Object.keys(sessionStorage).find(key => key.startsWith('goodmorning.chat.workspace.'));
      const saved = JSON.parse(sessionStorage.getItem(key));
      saved.away = Date.now() - milliseconds;
      sessionStorage.setItem(key, JSON.stringify(saved));
    }''', milliseconds)


def send(page, text):
    page.locator('#quick-chat-text').fill(text)
    page.locator('#quick-chat-text').press('Enter')
    expect(page.locator('#quick-chat-messages')).to_contain_text(text)
    expect(page.locator('#quick-chat-messages')).to_contain_text(REPLY)
    expect(page.locator('#quick-chat-send')).to_be_disabled()


def check_flow(browser, address):
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    errors = watch(page)
    page.goto(address + '/chat')
    expect(page.locator('#quick-chat')).to_have_count(0)
    for path in ('/gm.html', '/gn.html', '/schedule'):
        page.goto(address + path)
        expect(page.locator('#quick-chat-launcher')).to_be_visible()
        expect(page.locator('#quick-chat-launcher')).to_contain_text('Ask Mira')
    # Start on Schedule; the reply renders as text, not markup.
    page.locator('#quick-chat-launcher').click()
    expect(page.locator('#quick-chat-window')).to_be_visible()
    expect(page.locator('#quick-chat-text')).to_be_focused()
    expect(page.locator('#quick-chat-empty')).to_be_visible()
    send(page, 'PRIVATE quick question about Thursday')
    assert page.locator('#quick-chat-messages img').count() == 0
    first = chat_id(page)
    assert first and 'PRIVATE' not in page.evaluate('JSON.stringify(sessionStorage)')
    # Another desk page in this tab reopens the same conversation.
    page.locator('.edition-switch a[href="/gm.html"]').click()
    expect(page.locator('#quick-chat-window')).to_be_visible()
    expect(page.locator('#quick-chat-messages')).to_contain_text('PRIVATE quick question about Thursday')
    expect(page.locator('#quick-chat-open')).to_have_attribute('href', '/chat?id=' + first)
    # The jump opens this exact conversation on the Secretary page.
    page.locator('#quick-chat-open').click()
    expect(page).to_have_url(address + '/chat?id=' + first)
    expect(page.locator('#chat-messages')).to_contain_text('PRIVATE quick question about Thursday')
    # A conversation chosen on the Secretary page follows to the quick chat.
    page.locator('#new-conversation').click()
    page.locator('#chat-text').fill('Secretary page plan for Friday')
    page.locator('#chat-text').press('Enter')
    expect(page.locator('#chat-messages')).to_contain_text(REPLY)
    second = page.evaluate('chat')
    page.locator('.edition-switch a[href="/schedule"]').click()
    expect(page.locator('#quick-chat-window')).to_be_visible()
    expect(page.locator('#quick-chat-messages')).to_contain_text('Secretary page plan for Friday')
    assert chat_id(page) == second != first
    # Minimize with Escape; focus returns and the closed state follows navigation.
    page.locator('#quick-chat-text').focus(); page.keyboard.press('Escape')
    expect(page.locator('#quick-chat-window')).to_be_hidden()
    expect(page.locator('#quick-chat-launcher')).to_be_focused()
    page.goto(address + '/gn.html')
    expect(page.locator('#quick-chat-launcher')).to_be_visible()
    expect(page.locator('#quick-chat-window')).to_be_hidden()
    # New conversation from the quick chat becomes the tab's current one.
    page.locator('#quick-chat-launcher').click()
    page.locator('#quick-chat-new').click()
    expect(page.locator('#quick-chat-empty')).to_be_visible()
    expect(page.locator('#quick-chat-open')).to_have_attribute('href', '/chat')
    send(page, 'A brand new quick thread')
    third = chat_id(page)
    assert third not in (first, second)
    # Settled conversations open fresh after 15 minutes away, with a way back.
    page.locator('#quick-chat-minimize').click()
    age_absence(page, 15 * 60 * 1000)
    page.goto(address + '/schedule')
    page.locator('#quick-chat-launcher').click()
    expect(page.locator('#quick-chat-resume')).to_be_visible()
    expect(page.locator('#quick-chat-empty')).to_be_visible()
    page.locator('#quick-chat-resume-link').click()
    expect(page.locator('#quick-chat-messages')).to_contain_text('A brand new quick thread')
    # A Secretary page restored from the back/forward cache follows the quick chat's choice.
    page.goto(address + '/chat?id=' + first)
    expect(page.locator('#chat-messages')).to_contain_text('PRIVATE quick question about Thursday')
    page.evaluate('''id => {
      const key = Object.keys(sessionStorage).find(key => key.startsWith('goodmorning.chat.workspace.'));
      sessionStorage.setItem(key, JSON.stringify({chat: id, resume: null, away: null, draft: false}));
      dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}));
    }''', third)
    expect(page).to_have_url(address + '/chat?id=' + third)
    expect(page.locator('#chat-messages')).to_contain_text('A brand new quick thread')
    # An unsent quick draft asks before leaving and is never stored.
    page.goto(address + '/schedule')
    expect(page.locator('#quick-chat-window')).to_be_visible()
    page.locator('#quick-chat-text').fill('PRIVATE unsent draft')
    page.once('dialog', lambda dialog: dialog.dismiss())
    page.locator('.edition-switch a[href="/gm.html"]').click(no_wait_after=True)
    expect(page).to_have_url(address + '/schedule')
    assert 'PRIVATE' not in page.evaluate('JSON.stringify(sessionStorage)')
    page.locator('#quick-chat-text').fill('')
    assert not errors, errors
    page.close()
    return {'conversations': 3, 'pages': ['/gm.html', '/gn.html', '/schedule']}


def check_waiting(browser, address, artifacts):
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    errors = watch(page)
    form = {'id': 'frm_quick', 'title': 'Which afternoon works?', 'fields': [{'key': 'day', 'title': 'Day', 'type': 'multiselect',
            'required': True, 'minItems': 1, 'maxItems': 1, 'options': [{'value': 'thu', 'label': 'Thursday'}, {'value': 'fri', 'label': 'Friday'}]}]}
    page.route(f'**/api/chats/{WAITING}**', lambda route: route.fulfill(json={'chat': WAITING, 'mode': 'todo', 'state': 'waiting',
        'language': 'en', 'label': 'Your secretary needs your answer', 'forms': [form], 'permissions': [],
        'messages': [{'id': 'm1', 'role': 'user', 'text': 'Book the dentist'},
                     {'id': 'm2', 'role': 'assistant', 'kind': 'action', 'action': {'target': 'task', 'operation': 'added'}, 'text': 'Dentist'}]}))
    page.goto(address + '/schedule')
    page.evaluate('''id => {
      const key = 'goodmorning.chat.workspace.' + JSON.parse(document.querySelector('#quick-chat').dataset.config).workspaceScope;
      sessionStorage.setItem(key, JSON.stringify({chat: id, resume: null, away: null, draft: false}));
    }''', WAITING)
    page.reload()
    expect(page.locator('#quick-chat-dot')).to_have_attribute('data-state', 'waiting')
    expect(page.locator('#quick-chat-launcher')).to_have_attribute('aria-label', 'Ask Mira · Your secretary needs your answer')
    page.locator('#quick-chat-launcher').click()
    expect(page.locator('#quick-chat-questions')).to_contain_text('Which afternoon works?')
    expect(page.locator('#quick-chat-messages')).to_contain_text('Task added')
    expect(page.locator('#quick-chat-mode')).to_contain_text('To-do')
    expect(page.locator('#quick-chat-text')).to_be_disabled()
    expect(page.locator('#quick-chat-dot')).to_be_hidden()
    for edition in ('gm', 'gn'):
        page.evaluate('edition => { document.documentElement.dataset.edition = edition; }', edition)
        page.locator('#quick-chat-window').screenshot(path=str(artifacts / f'quick-chat-waiting-{edition}.png'))
    assert not errors, errors
    page.close()


def check_layouts(browser, address, artifacts):
    results = []
    for width, height in ((1440, 900), (1024, 700), (390, 844), (320, 640)):
        for language in ('en', 'zh-CN'):
            page = browser.new_page(viewport={'width': width, 'height': height}, has_touch=width < 700)
            errors = watch(page)
            page.goto(address + '/gm.html')
            csrf = page.evaluate("JSON.parse(document.querySelector('#language-config').dataset.config).csrf")
            page.request.post(address + '/api/language', data={'language': language}, headers={'X-Briefing-CSRF': csrf, 'Origin': address})
            page.reload()
            launcher = page.locator('#quick-chat-launcher')
            expect(launcher).to_be_visible()
            if language == 'zh-CN':
                expect(page.locator('#quick-chat')).to_have_attribute('aria-label', '快捷对话')
                expect(launcher).to_have_attribute('aria-label', '问问Mira')
            if width < 700:
                # Reading down tucks the floating buttons away; a pause brings them back.
                page.mouse.wheel(0, 300)
                expect(page.locator('html.floaters-tucked')).to_have_count(1)
                expect(launcher).to_have_css('opacity', '0')
                expect(page.locator('html.floaters-tucked')).to_have_count(0)
                expect(launcher).to_have_css('opacity', '1')
                page.mouse.wheel(0, 300)
                expect(page.locator('html.floaters-tucked')).to_have_count(1)
                page.mouse.wheel(0, -200)  # Scrolling back up returns them before the pause.
                expect(page.locator('html.floaters-tucked')).to_have_count(0, timeout=600)
            page.mouse.wheel(0, 4000); page.wait_for_timeout(400)
            box = launcher.bounding_box()
            assert box['x'] >= 0 and box['x'] + box['width'] <= width and box['y'] + box['height'] <= height, box
            for other in ('.back-to-top.is-visible', '#mobile-sections'):
                if page.locator(other).count() and page.locator(other).first.is_visible():
                    near = page.locator(other).first.bounding_box()
                    overlap = not (near['x'] + near['width'] <= box['x'] or box['x'] + box['width'] <= near['x']
                                   or near['y'] + near['height'] <= box['y'] or box['y'] + box['height'] <= near['y'])
                    assert not overlap, (other, width, near, box)
            page.screenshot(path=str(artifacts / f'quick-chat-closed-{width}-{language}.png'))
            launcher.click()
            page.evaluate("Promise.all(document.querySelector('#quick-chat-window').getAnimations().map(a => a.finished))")
            panel = page.locator('#quick-chat-window').bounding_box()
            assert panel['x'] >= 0 and panel['x'] + panel['width'] <= width and panel['y'] >= 0 and panel['y'] + panel['height'] <= height, panel
            expect(page.locator('#quick-chat-compose')).to_be_in_viewport()
            page.screenshot(path=str(artifacts / f'quick-chat-open-{width}-{language}.png'))
            page.locator('#quick-chat-minimize').click()
            page.request.post(address + '/api/language', data={'language': 'en'}, headers={'X-Briefing-CSRF': csrf, 'Origin': address})
            assert not errors, errors
            results.append(f'{width}x{height}-{language}')
            page.close()
    return results


def check_setup_gate(browser, address, runtime):
    profile = runtime / 'profile.md'
    profile.write_text('secretary_language: English\n')
    page = browser.new_page()
    errors = watch(page)
    page.goto(address + '/schedule')
    page.wait_for_load_state('networkidle')
    expect(page.locator('#quick-chat')).to_be_hidden()
    assert not errors, errors
    page.close()
    profile.write_text(READY)


def main():
    artifacts = Path(sys.argv[1]); artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir='/tmp/opencode' if Path('/tmp/opencode').is_dir() else None, prefix='gm-quick-chat-') as directory:
        runtime = Path(directory)
        (runtime / 'profile.md').write_text(READY)
        server = subprocess.Popen([sys.executable, str(REPO / 'tests/test_briefing_chat.py'), '--serve-fixture', directory],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            address = server.stdout.readline().strip().removeprefix('Private live viewer: ')
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                report = {'flow': check_flow(browser, address), 'layouts': check_layouts(browser, address, artifacts), 'modelCalls': 0}
                check_waiting(browser, address, artifacts)
                check_setup_gate(browser, address, runtime)
                browser.close()
        finally:
            server.terminate(); server.communicate(timeout=5)
    (artifacts / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__': main()
