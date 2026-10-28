"""History designs and tab-local continuity with synthetic data and no model calls."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright, expect
from chat_markdown import contrast

REPO = Path(__file__).resolve().parents[2]
CHAT = 'a' * 32
OTHER = 'b' * 32
TITLES = [
    ('secretary', 'A calmer plan for the week'),
    ('eureka', 'A little reading corner for the team'),
    ('todo', 'Prepare the project handover'),
    ('secretary', 'Making room for a longer, more thoughtful conversation about next month’s priorities'),
    ('eureka', '把零散的灵感整理成一个可以慢慢实现的小计划'),
    ('todo', 'Book a quiet afternoon'),
]


def mock_chats(page):
    control = {'state': 'idle', 'listing_error': False, 'status_error': False, 'forms': [], 'empty': False, 'missing': False}
    def listing(route):
        if control['listing_error']:
            return route.fulfill(status=503, json={'error': 'Synthetic history outage'})
        route.fulfill(json={'defaultMode': 'secretary', 'connected': True, 'chats': [] if control['empty'] else [
            {'id': CHAT if i == 0 else OTHER if i == 1 else format(i, '032x'),
             'mode': mode, 'title': title} for i, (mode, title) in enumerate(TITLES)]})
    def status(route):
        assert route.request.method == 'GET', 'Navigation must not dispatch or replay agent work'
        if control['missing']:
            return route.fulfill(status=404, json={'error': 'Unknown conversation'})
        if control['status_error']:
            return route.fulfill(status=503, json={'error': 'Synthetic connection outage'})
        route.fulfill(json={'chat': CHAT, 'mode': 'secretary', 'state': control['state'], 'language': 'en',
            'label': 'Ready for your reply', 'forms': control['forms'], 'permissions': [], 'messages': [
                {'id': 'user-one', 'role': 'user', 'text': 'Help me make a little room in the week for focused work.'},
                {'id': 'assistant-one', 'role': 'assistant', 'text': 'Let’s keep the week spacious.\n\n- **One priority each morning.** Leave the first hour clear.\n- **A little breathing room.** Keep Wednesday afternoon free.\n- **A gentle Friday review.** Notice what worked before planning more.\n\nWhich day would you like to start with?'}]})
    page.route('**/api/chats', listing)
    page.route('**/api/chats/**', status)
    return control


def settled(page):
    expect(page.locator('#chat-messages')).to_contain_text('Let’s keep the week spacious.')
    expect(page.locator('#chat-send')).to_be_enabled()


def hide(page, hidden):
    page.evaluate('''hidden => {
      Object.defineProperty(document, 'hidden', {configurable: true, value: hidden});
      document.dispatchEvent(new Event('visibilitychange'));
    }''', hidden)


def elapsed_away(page, milliseconds):
    # Age only the saved absence, not browser timers or agent work.
    page.evaluate('''milliseconds => {
      const key = Object.keys(sessionStorage).find(key => key.startsWith('goodmorning.chat.workspace.'));
      const saved = JSON.parse(sessionStorage.getItem(key));
      saved.away = Date.now() - milliseconds;
      sessionStorage.setItem(key, JSON.stringify(saved));
      if (typeof workspace !== 'undefined') workspace.away = saved.away;
    }''', milliseconds)


def check_continuity(browser, address):
    context = browser.new_context(viewport={'width': 1440, 'height': 900})
    page = context.new_page()
    errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
    control = mock_chats(page)
    page.goto(address + '/chat?id=' + CHAT); settled(page)
    # Real website pages and their Secretary navigation restore the selected ID.
    for path in ('/gm', '/gn', '/schedule'):
        page.goto(address + path)
        page.locator('.edition-switch a[href="/chat"]').click()
        settled(page); expect(page).to_have_url(address + '/chat?id=' + CHAT)
    page.reload(); settled(page)
    # Time spent reading the page is not absence.
    page.evaluate('returnToSecretary()')
    expect(page).to_have_url(address + '/chat?id=' + CHAT)
    # Below 15 minutes away restores; at least 15 minutes opens a fresh draft.
    page.goto(address + '/schedule'); elapsed_away(page, 14 * 60 * 1000)
    page.locator('.edition-switch a[href="/chat"]').click(); settled(page)
    expect(page).to_have_url(address + '/chat?id=' + CHAT)
    page.goto(address + '/schedule'); elapsed_away(page, 15 * 60 * 1000)
    page.locator('.edition-switch a[href="/chat"]').click()
    expect(page.locator('#chat-resume')).to_be_visible()
    expect(page).to_have_url(address + '/chat')
    page.locator('#chat-resume').click(); settled(page)
    # Hidden browser tabs follow the same absence rule, but busy/waiting states stay open.
    for state in ('running', 'waiting', 'queued', 'uncertain', 'unavailable'):
        control['state'] = state
        hide(page, True); elapsed_away(page, 16 * 60 * 1000); hide(page, False)
        expect(page).to_have_url(address + '/chat?id=' + CHAT)
        expect(page.locator('#conversation')).to_have_attribute('aria-busy', 'false')
    control['state'] = 'idle'
    page.evaluate('pollChat()'); settled(page)
    # Unsent private input is kept in memory, never serialized.
    page.locator('#chat-text').fill('PRIVATE synthetic draft')
    hide(page, True); elapsed_away(page, 16 * 60 * 1000); hide(page, False)
    expect(page.locator('#chat-text')).to_have_value('PRIVATE synthetic draft')
    expect(page).to_have_url(address + '/chat?id=' + CHAT)
    assert 'PRIVATE' not in page.evaluate('JSON.stringify(sessionStorage)')
    page.once('dialog', lambda dialog: dialog.dismiss())
    page.locator('.edition-switch a[href="/schedule"]').click(no_wait_after=True)
    expect(page).to_have_url(address + '/chat?id=' + CHAT)
    page.locator('#chat-text').fill('')
    # A question's preselected answers are not a draft; changing them is.
    control['forms'] = [{'id': 'pick', 'title': 'Which day?', 'fields': [
        {'key': 'day', 'title': 'Day', 'type': 'string', 'default': 'tue',
         'options': [{'value': 'mon', 'label': 'Monday'}, {'value': 'tue', 'label': 'Tuesday'}]},
        {'key': 'remind', 'title': 'Remind me', 'type': 'boolean', 'default': True},
        {'key': 'note', 'title': 'Note', 'type': 'string', 'default': 'Morning'}]}]
    page.evaluate('pollChat()')
    expect(page.get_by_label('Tuesday')).to_be_checked()
    assert not page.evaluate('hasUnsentInput()')
    page.get_by_label('Monday').check()
    assert page.evaluate('hasUnsentInput()')
    page.get_by_label('Tuesday').check()
    page.get_by_role('textbox', name='Note', exact=True).fill('Evening')
    assert page.evaluate('hasUnsentInput()')
    control['forms'] = []
    page.evaluate('pollChat()'); expect(page.locator('#chat-questions .agent-form')).to_have_count(0)
    page.get_by_role('button', name='New conversation', exact=True).click()
    page.goto(address + '/schedule'); page.goto(address + '/chat')
    expect(page.locator('#chat-empty')).to_be_visible()
    expect(page).to_have_url(address + '/chat')
    # Explicit links win over the workspace; independent tabs start fresh.
    page.goto(address + '/chat?id=' + OTHER); settled(page)
    page.goto(address + '/chat?mode=eureka')
    expect(page.locator('#chat-topic-mode')).to_have_text('Secretary')
    expect(page.locator('#chat-empty')).to_be_visible()
    second = context.new_page(); mock_chats(second); second.goto(address + '/chat')
    expect(second.locator('#chat-empty')).to_be_visible()
    second.close()
    # Direct history links and Back/Forward retain their explicit destinations.
    page.goto(address + '/chat?id=' + CHAT); settled(page)
    page.locator(f'#chat-history a[href="/chat?id={OTHER}"]').click()
    expect(page).to_have_url(address + '/chat?id=' + OTHER)
    page.go_back(); expect(page).to_have_url(address + '/chat?id=' + CHAT)
    page.go_forward(); expect(page).to_have_url(address + '/chat?id=' + OTHER)
    # Transient status and history failures must not authorize a reset or destroy the chat.
    control['status_error'] = True
    hide(page, True); elapsed_away(page, 16 * 60 * 1000); hide(page, False)
    expect(page.locator('#conversation')).to_have_attribute('aria-busy', 'false')
    expect(page).to_have_url(address + '/chat?id=' + OTHER)
    control['status_error'] = False
    control['listing_error'] = True
    page.evaluate('historyList().catch(() => {})')
    expect(page.locator('#history-retry')).to_be_visible()
    expect(page.locator('#chat-history a')).to_have_count(len(TITLES))
    control['listing_error'] = False
    page.locator('#history-retry').click(); expect(page.locator('#history-retry')).to_be_hidden()
    control['missing'] = True
    page.goto(address + '/chat?id=' + CHAT)
    expect(page.locator('#chat-error')).to_contain_text('no longer available')
    expect(page).to_have_url(address + '/chat')
    control['missing'] = False
    control['empty'] = True
    page.evaluate('historyList().catch(() => {})')
    expect(page.locator('#history-notice')).to_have_text('Your conversations will appear here.')
    expect(page.locator('#chat-history a')).to_have_count(0)
    expect(page.locator('#chat-history')).to_be_hidden()
    control['empty'] = False
    page.evaluate("sessionStorage.setItem(workspaceKey, JSON.stringify({chat: '<invalid>', away: 1}))")
    page.goto(address + '/chat')
    expect(page.locator('#chat-empty')).to_be_visible()
    # A changed login namespace cannot restore old references, even in the same tab.
    page.route('**/chat', lambda route: rewrite_scope(route))
    page.goto(address + '/chat'); expect(page.locator('#chat-empty')).to_be_visible()
    assert not errors, errors
    context.close()
    return {'navigation': 3, 'idleAwayBoundary': '15 minutes', 'protectedStates': 5,
            'unsentWarning': True, 'independentTabs': True, 'loginScope': True,
            'explicitLinksAndHistory': True, 'outagePreservesChat': True, 'pageErrors': errors}


def rewrite_scope(route):
    response = route.fetch()
    import re
    body = re.sub(r'(&quot;workspaceScope&quot;:\s*&quot;)[a-f0-9]{64}', r'\g<1>' + 'f' * 64, response.text())
    route.fulfill(response=response, body=body)


def check_layouts(browser, address, artifacts):
    checks = []
    for width, height in ((1440, 900), (768, 900), (390, 844), (320, 740), (1440, 600)):
        page = browser.new_page(viewport={'width': width, 'height': height}, reduced_motion='reduce')
        errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
        mock_chats(page)
        page.goto(address + '/chat?id=' + CHAT); settled(page)
        page.evaluate('document.fonts.ready')
        expect(page.locator('#chat-send')).to_be_in_viewport(ratio=1)
        assert page.evaluate('scrollY') == 0
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        expect(page.locator('#conversation-history summary')).to_have_count(0)
        expect(page.locator('#new-conversation svg')).to_have_count(1)
        expect(page.locator('.scroll-rail-label')).to_have_count(0)
        rows = page.locator('#chat-history a').evaluate_all('''links => links.map(link => {
          const title = link.querySelector('.history-title').getBoundingClientRect();
          const meta = link.querySelector('.history-meta').getBoundingClientRect();
          const box = link.getBoundingClientRect();
          return meta.top >= title.bottom && meta.bottom <= box.bottom - 6;
        })''')
        assert all(rows), 'History titles or subtitles overlap their row borders'
        for edition, scheme in (('gm', 'classic'), ('gm', 'warm'), ('gn', 'classic'), ('gn', 'parchment')):
            page.evaluate('''([edition, scheme]) => {
              clearTimeout(themeTimer); document.documentElement.dataset.edition = edition;
              document.documentElement.dataset[edition === 'gm' ? 'dayScheme' : 'nightScheme'] = scheme;
            }''', [edition, scheme])
            colors = page.locator('#chat-history a').first.evaluate('''node => ({
              title: getComputedStyle(node).color, subtitle: getComputedStyle(node.querySelector('small')).color,
              background: getComputedStyle(node).backgroundColor, size: getComputedStyle(node).fontSize,
              height: node.getBoundingClientRect().height
            })''')
            assert contrast(colors['title'], colors['background']) >= 4.5, colors
            assert contrast(colors['subtitle'], colors['background']) >= 4.5, colors
            button = page.locator('#new-conversation').evaluate('node => ({ink: getComputedStyle(node).color, paper: getComputedStyle(node).backgroundColor})')
            assert contrast(button['ink'], button['paper']) >= 4.5, button
            assert float(colors['size'].replace('px', '')) >= 15 and colors['height'] >= 44
        assert not errors, errors
        checks.append({'width': width, 'height': height, 'sendVisibleWithoutScroll': True, 'palettes': 4})
        page.close()
    # Storage can be disabled independently of the always-open history UI.
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    page.add_init_script("Object.defineProperty(window, 'sessionStorage', {get() { throw new Error('Disabled storage'); }});")
    mock_chats(page); page.goto(address + '/chat?id=' + CHAT); settled(page)
    expect(page.locator('#chat-send')).to_be_in_viewport(ratio=1)
    page.close()
    return checks


def previews(browser, address, artifacts):
    for label, width, height in (('desktop', 1440, 1000), ('phone', 390, 844)):
        page = browser.new_page(viewport={'width': width, 'height': height}, reduced_motion='reduce', has_touch=width<=700, is_mobile=width<=700)
        mock_chats(page); page.goto(address + '/chat?id=' + CHAT); settled(page)
        page.evaluate('document.fonts.ready')
        page.evaluate("clearTimeout(themeTimer); document.documentElement.dataset.edition='gm'")
        expect(page.locator('#chat-send')).to_be_in_viewport(ratio=1)
        page.screenshot(path=str(artifacts / f'inset-{label}.png'), full_page=True)
        if label == 'phone':
            response=page.request.post(address + '/api/language', data={'language': 'zh-CN'}, headers={'X-Briefing-CSRF': page.evaluate('chatConfig.csrf'), 'Origin': address})
            assert response.ok, response.text()
            page.reload(); settled(page)
            expect(page.locator('#history-heading')).to_have_text('历史对话')
            page.screenshot(path=str(artifacts / 'inset-phone-zh.png'), full_page=True)
            response=page.request.post(address + '/api/language', data={'language': 'en'}, headers={'X-Briefing-CSRF': page.evaluate('chatConfig.csrf'), 'Origin': address})
            assert response.ok, response.text()
        if label == 'desktop':
            page.evaluate("clearTimeout(themeTimer); document.documentElement.dataset.edition='gn'")
            page.screenshot(path=str(artifacts / 'inset-desktop-night.png'), full_page=True)
        page.close()


def main():
    artifacts = Path(sys.argv[1]); artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='gm-history-') as directory:
        # This suite mocks ready conversations; the initial server-rendered page
        # must describe the same ready account before async history arrives.
        (Path(directory)/'profile.md').write_text('secretary_language: English\ncity: London\ntimezone: Europe/London\nnews_country: GB\n')
        server = subprocess.Popen([sys.executable, str(REPO / 'tests/test_briefing_chat.py'), '--serve-fixture', directory], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            address = server.stdout.readline().strip().removeprefix('Private live viewer: ')
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                report = {'continuity': check_continuity(browser, address), 'layouts': check_layouts(browser, address, artifacts), 'modelCalls': 0}
                previews(browser, address, artifacts)
                browser.close()
        finally:
            server.terminate(); server.communicate(timeout=5)
    (artifacts / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__': main()
