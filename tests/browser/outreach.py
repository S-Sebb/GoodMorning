"""Secretary-opened conversations: quick chat pill, chat list badge, bubble, reading and replying. Synthetic, no model calls."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

from playwright.sync_api import sync_playwright, expect

REPO = Path(__file__).resolve().parents[2]
READY = 'secretary_language: English\ncity: London\ntimezone: Europe/London\nnews_country: GB\nsecretary_name: Mira\n'
NOTE = {'en': 'Hi Yuki! I noticed passaging comes up every couple of days.\n\n- Want a **gentle reminder every two days**?\n- Or keep it as you go?\n\nJust tell me here 🌱',
        'zh-CN': 'Yuki～我发现传代差不多每两天就要做一次。\n\n- 要不要我**每两天提醒你一次**？\n- 还是想到再说？\n\n直接在这里回我就好 🌱'}


def watch(page):
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    return errors


def csrf(page):
    return page.evaluate("JSON.parse(document.querySelector('#language-config').dataset.config).csrf")


def language(page, address, selected):
    page.request.post(address + '/api/language', data={'language': selected}, headers={'X-Briefing-CSRF': csrf(page), 'Origin': address})


def outreach(page, address, text, title=None):
    chat = uuid.uuid4().hex
    response = page.request.post(address + '/api/admin/outreach', data=json.dumps({'id': chat, 'text': text, **({'title': title} if title else {})}),
                                 headers={'X-Briefing-CSRF': csrf(page), 'Origin': address, 'Content-Type': 'application/json'})
    assert response.status == 201, response.text()
    return chat


def check_quick_chat(browser, address, artifacts):
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    errors = watch(page)
    page.goto(address + '/gm.html')
    launcher = page.locator('#quick-chat-launcher')
    expect(launcher).to_contain_text('Ask Mira')
    chat = outreach(page, address, NOTE['en'])
    page.reload()
    expect(launcher).to_contain_text('New message from Mira')
    expect(launcher).to_have_class('has-note')
    expect(page.locator('#quick-chat-dot')).to_be_visible()
    expect(page.locator('#quick-chat-dot')).to_have_attribute('data-state', 'note')
    page.screenshot(path=str(artifacts / 'pill-note-1440-en.png'))
    launcher.click()
    bubble = page.locator('.quick-chat-message.outreach')
    expect(bubble).to_be_visible()
    expect(bubble.locator('.quick-chat-label')).to_have_text('Your secretary reached out')
    expect(bubble.locator('.quick-chat-footnote')).to_have_count(0)
    expect(bubble.locator('strong')).to_have_text('gentle reminder every two days')  # Markdown, not raw asterisks.
    expect(page.locator('#quick-chat-open')).to_have_attribute('href', '/chat?id=' + chat)
    page.evaluate("Promise.all(document.querySelector('#quick-chat-window').getAnimations().map(a => a.finished))")
    page.screenshot(path=str(artifacts / 'panel-note-1440-en.png'))
    # Reading it is remembered for the account, not just this tab.
    other = browser.new_page(viewport={'width': 390, 'height': 844}, has_touch=True)
    other.goto(address + '/gn.html')
    expect(other.locator('#quick-chat-launcher')).to_contain_text('Ask Mira')
    expect(other.locator('#quick-chat-dot')).to_be_hidden()
    other.close()
    # Replying hands over to the normal secretary in the same conversation.
    page.locator('#quick-chat-text').fill('Yes please, every two days')
    page.locator('#quick-chat-text').press('Enter')
    expect(page.locator('#quick-chat-messages')).to_contain_text('Synthetic reply')
    expect(page.locator('.quick-chat-message.outreach')).to_have_count(1)
    assert page.locator('.quick-chat-message').first.get_attribute('class').count('outreach') == 1
    assert not errors, errors
    page.close()
    return chat


def check_chat_page(browser, address, artifacts):
    page = browser.new_page(viewport={'width': 1440, 'height': 900})
    errors = watch(page)
    page.goto(address + '/chat')
    chat = outreach(page, address, NOTE['en'], title='About passaging')
    page.reload()
    entry = page.locator(f'#chat-history a[href="/chat?id={chat}"]')
    expect(entry).to_have_class('is-unread')
    expect(entry.locator('.history-new')).to_have_text('New')
    expect(entry.locator('.history-title')).to_have_text('About passaging')
    page.screenshot(path=str(artifacts / 'chat-list-new-1440-en.png'))
    entry.click()
    bubble = page.locator('.chat-message[data-special="outreach"]')
    expect(bubble).to_be_visible()
    expect(bubble.locator('.chat-special-label')).to_contain_text('Your secretary reached out')
    expect(bubble.locator('.message-footnote')).to_have_count(0)
    expect(bubble.locator('.message-author')).to_have_text('Mira')
    expect(bubble.locator('li')).to_have_count(2)
    expect(page.locator('#chat-text')).to_be_enabled()
    expect(entry.locator('.history-new')).to_have_count(0)
    expect(entry).not_to_have_class('is-unread')
    page.screenshot(path=str(artifacts / 'chat-note-1440-en.png'))
    assert not errors, errors
    page.close()


def check_layouts(browser, address, artifacts):
    results = []
    for width, height in ((1440, 900), (1024, 700), (390, 844), (320, 640)):
        for selected in ('en', 'zh-CN'):
            for edition in ('gm', 'gn'):
                page = browser.new_page(viewport={'width': width, 'height': height}, has_touch=width < 700)
                errors = watch(page)
                page.goto(address + f'/{edition}.html')
                language(page, address, selected)
                chat = outreach(page, address, NOTE[selected])
                page.reload()
                launcher = page.locator('#quick-chat-launcher')
                expect(launcher).to_contain_text('Mira有新消息' if selected == 'zh-CN' else 'New message from Mira')
                box = launcher.bounding_box()
                assert box['x'] >= 0 and box['x'] + box['width'] <= width and box['y'] + box['height'] <= height, box
                page.screenshot(path=str(artifacts / f'pill-{edition}-{width}-{selected}.png'))
                launcher.click()
                page.evaluate("Promise.all(document.querySelector('#quick-chat-window').getAnimations().map(a => a.finished))")
                expect(page.locator('.quick-chat-message.outreach .quick-chat-footnote')).to_have_count(0)
                panel = page.locator('#quick-chat-window').bounding_box()
                assert panel['x'] >= 0 and panel['x'] + panel['width'] <= width, panel
                page.screenshot(path=str(artifacts / f'panel-{edition}-{width}-{selected}.png'))
                page.goto(address + '/chat?id=' + chat)
                expect(page.locator('.chat-message[data-special="outreach"] .chat-special-label')).to_contain_text(
                    '你的秘书来找你啦' if selected == 'zh-CN' else 'Your secretary reached out')
                note = page.locator('.chat-message[data-special="outreach"]').bounding_box()
                assert note['x'] >= 0 and note['x'] + note['width'] <= width, note
                page.screenshot(path=str(artifacts / f'chat-{edition}-{width}-{selected}.png'), full_page=False)
                language(page, address, 'en')
                assert not errors, errors
                results.append(f'{edition}-{width}-{selected}')
                page.close()
    return results


def check_reduced_motion(browser, address):
    page = browser.new_page(reduced_motion='reduce')
    page.goto(address + '/gm.html')
    outreach(page, address, 'A quiet hello.')
    page.reload()
    dot = page.locator('#quick-chat-dot')
    expect(dot).to_have_attribute('data-state', 'note')
    assert dot.evaluate('node => getComputedStyle(node).animationName') == 'none'
    page.locator('#quick-chat-launcher').click()
    page.close()


def main():
    artifacts = Path(sys.argv[1]); artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir='/tmp/opencode' if Path('/tmp/opencode').is_dir() else None, prefix='gm-outreach-') as directory:
        runtime = Path(directory)
        (runtime / 'profile.md').write_text(READY)
        server = subprocess.Popen([sys.executable, str(REPO / 'tests/test_briefing_chat.py'), '--serve-fixture', directory],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            address = server.stdout.readline().strip().removeprefix('Private live viewer: ')
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                check_quick_chat(browser, address, artifacts)
                check_chat_page(browser, address, artifacts)
                report = {'layouts': check_layouts(browser, address, artifacts), 'modelCalls': 0}
                check_reduced_motion(browser, address)
                browser.close()
        finally:
            server.terminate(); server.communicate(timeout=5)
    (artifacts / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__': main()
