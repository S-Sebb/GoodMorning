"""Patch-note discovery/history, account dismissals and safe updates; no model calls."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from playwright.sync_api import sync_playwright, expect

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO/'src')); sys.path.insert(0, str(REPO/'tests'))
from goodmorning.briefings.briefing_day import briefing_day
from goodmorning.web.release import release_info
from test_briefing_web import GM

NOTE_EN = 'Synthetic patch note for the staged website update.'
NOTE_ZH = '模拟网站更新补丁说明。'
NOTE = {'version': '0.20.0', 'date': '2026-10-12', 'author': 'Synthetic deployer',
        'title_en': 'Synthetic release', 'title_zh': '模拟版本', 'en': 'Fixed:\n- ' + NOTE_EN, 'zh': '修复:\n- ' + NOTE_ZH,
        'changes': [{'category': 'Fixed', 'en': [NOTE_EN], 'zh': [NOTE_ZH]}], 'commits': []}


def check_actions(page):
    assert page.locator('.patch-footer').evaluate('''footer => {
        const style = getComputedStyle(footer), box = footer.getBoundingClientRect();
        const buttons = [...footer.querySelectorAll('button')].filter(button => !button.hidden);
        const last = buttons.at(-1).getBoundingClientRect();
        return Math.abs(last.right - (box.right - parseFloat(style.paddingRight))) < 1
            && Math.abs(last.bottom - (box.bottom - parseFloat(style.paddingBottom))) < 1
            && buttons.every(button => {
                const rect = button.getBoundingClientRect();
                return rect.left >= box.left && rect.right <= box.right;
            });
    }'''), 'Popup actions must stay at the bottom right'
    expect(page.locator('#patch-note-dismiss')).to_be_in_viewport()
    if page.locator('#update-refresh').is_visible():
        expect(page.locator('#update-refresh')).to_be_in_viewport()
        assert page.locator('#update-refresh').bounding_box()['x'] > page.locator('#patch-note-dismiss').bounding_box()['x']


def main():
    artifacts = Path(sys.argv[1]); artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    cases = []
    current = release_info()
    first = next(note for note in current['notes'] if note['version'] == '0.0.0')
    zh = json.loads((REPO/'assets/web/translations.json').read_text(encoding='utf-8'))
    NOTE['version'] = '0.' + str(int(current['release'].split('.')[1]) + 1) + '.0'
    with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='gm-update-browser-') as directory:
        root = Path(directory); (root/'daily').mkdir()
        (root/'profile.md').write_text('city: London\ntimezone: Europe/London\nnews_country: GB\nsecretary_language: English\n')
        day = briefing_day('Europe/London')
        for kind in ('gm', 'gn'): (root/'daily'/(day+'.'+kind+'.json')).write_text(GM)
        process = subprocess.Popen([sys.executable, str(REPO/'tests/test_briefing_chat.py'), '--serve-fixture', '--unseen-release', directory],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        address = process.stdout.readline().strip().removeprefix('Private live viewer: ')
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                # Compare the old script with the fix on an otherwise identical fresh page.
                baseline = browser.new_page()
                old_script = subprocess.check_output(['git', 'show', 'f1f79d1:assets/web/update.js'], cwd=REPO, text=True)
                baseline.route('**/update.js', lambda route: route.fulfill(body=old_script, content_type='text/javascript'))
                with baseline.expect_response('**/api/release'):
                    baseline.goto(address+'/chat')
                expect(baseline.locator('#site-patch-note')).to_be_hidden()
                baseline.close()

                for path in ('/chat', '/gm', '/gn'):
                    for width in (320, 390, 1440):
                        (root/'website-language.json').write_text('{"language":"en"}')
                        context = browser.new_context(viewport={'width': width, 'height': 700}, reduced_motion='reduce')
                        page = context.new_page(); page.clock.install(); errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        state = {'payload': current, 'seen': None, 'offline': False}

                        def release(route):
                            if state['offline']: route.abort(); return
                            route.fulfill(json=state['payload'], headers={'Cache-Control': 'no-store'})

                        def seen(route):
                            if route.request.method == 'POST':
                                state['seen'] = route.request.post_data_json['version']
                            route.fulfill(json={'version': state['seen'], 'enabled': True}, headers={'Cache-Control': 'no-store'})

                        page.route('**/api/release', release)
                        page.route('**/api/release/seen', seen)
                        page.goto(address+path)
                        modal = page.get_by_role('dialog', name='Patch notes', exact=True)
                        expect(modal).to_be_visible()  # New user, no Update-button dependency.
                        expect(page.locator('#patch-note-version')).to_have_text('v' + current['release'])
                        expect(page.locator('#site-update-toggle')).to_have_attribute('data-state', 'current')
                        expect(page.locator('#update-refresh')).to_be_hidden()
                        check_actions(page)
                        expected_categories = [group['category'] for group in current['notes'][0]['changes']]
                        expect(page.locator('#patch-note-text h4')).to_have_text(expected_categories)
                        expect(page.locator('#patch-note-text li')).to_have_count(sum(len(group['en']) for group in current['notes'][0]['changes']))
                        assert page.locator('#patch-note-versions button').count() == len(current['notes'])
                        assert page.locator('.patch-footer').evaluate(
                            'node => Math.abs(node.getBoundingClientRect().width - node.closest("dialog").clientWidth) < 2')
                        if width < 500:
                            page.set_viewport_size({'width': width, 'height': 380})
                            expect(page.locator('#patch-note-dismiss')).to_be_in_viewport()
                            check_actions(page)
                            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                            position = page.locator('.patch-content').evaluate('node => { node.scrollTop = 80; return node.scrollTop; }')
                            page.clock.run_for(61000)
                            assert page.locator('.patch-content').evaluate('node => node.scrollTop') == position
                            page.set_viewport_size({'width': width, 'height': 700})
                            page.locator('.patch-content').evaluate('node => { node.scrollTop = 0; }')
                        page.screenshot(path=str(artifacts/(path.strip('/').replace('.html', '')+'-current-'+str(width)+'.png')))
                        page.locator('[data-version="0.0.0"]').click()
                        expect(page.locator('#patch-note-title')).to_have_text(first['title_en'])
                        expect(page.locator('#patch-note-source')).to_contain_text(first['commits'][0])
                        expect(page.locator('#patch-note-text h4')).to_have_text([group['category'] for group in first['changes']])
                        expect(page.locator('#patch-note-text li')).to_have_count(sum(len(group['en']) for group in first['changes']))
                        page.clock.run_for(61000)
                        expect(page.locator('[data-version="0.0.0"]')).to_be_focused()
                        expect(page.locator('#patch-note-title')).to_have_text(first['title_en'])
                        page.evaluate("applyWebsiteLanguage('zh-CN')")
                        expect(page.locator('#patch-note-title')).to_have_text(first['title_zh'])
                        expect(page.locator('#patch-note-text h4')).to_have_text([zh[group['category']] for group in first['changes']])
                        expect(page.locator('#patch-note-text li').first).to_have_text(first['changes'][0]['zh'][0])
                        check_actions(page)
                        page.get_by_role('button', name='关闭', exact=True).click()
                        expect(modal).to_be_hidden()
                        assert state['seen'] == current['release']
                        page.reload()
                        expect(page.locator('#site-update-toggle')).to_be_visible()
                        expect(page.locator('#site-patch-note')).to_be_hidden()  # Ordinary refresh, already dismissed.
                        if page.locator('#prefs-menu').get_attribute('open') is None:
                            page.locator('#prefs-menu > summary').click()
                        page.locator('#website-language').select_option('en')
                        expect(page.locator('html')).to_have_attribute('lang', 'en')
                        if path == '/chat': page.locator('#chat-text').fill('Preserve this unsent draft.')
                        state['offline'] = True; page.clock.run_for(61000)
                        expect(page.locator('#site-patch-note')).to_be_hidden()
                        state['offline'] = False
                        state['payload'] = {'version': 'f'*64, 'release': NOTE['version'], 'note': NOTE, 'notes': [NOTE, *current['notes']]}
                        page.clock.run_for(61000)
                        expect(page.locator('#site-patch-note')).to_be_visible()
                        expect(page.locator('#patch-note-text h4')).to_have_text('Fixed')
                        expect(page.locator('#patch-note-text li')).to_have_text(NOTE_EN)
                        expect(page.locator('#site-update-toggle')).to_have_attribute('data-state', 'available')
                        expect(page.locator('#update-refresh')).to_be_visible()
                        check_actions(page)
                        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                        if path == '/chat':
                            expect(page.locator('#chat-text')).to_have_value('Preserve this unsent draft.')
                            page.once('dialog', lambda dialog: dialog.dismiss())
                            page.locator('#update-refresh').click()
                            expect(page.locator('#chat-text')).to_have_value('Preserve this unsent draft.')
                        page.get_by_role('button', name='Dismiss', exact=True).click()
                        expect(page.locator('#site-patch-note')).to_be_hidden()
                        page.clock.run_for(61000)
                        expect(page.locator('#site-patch-note')).to_be_hidden()
                        page.locator('#site-update-toggle').click()
                        expect(page.locator('#site-patch-note')).to_be_visible()
                        page.evaluate("applyWebsiteLanguage('zh-CN')")
                        expect(page.locator('#patch-note-text h4')).to_have_text('修复')
                        expect(page.locator('#patch-note-text li')).to_have_text(NOTE_ZH)
                        expect(page.locator('#site-patch-note')).to_contain_text('网站有新版本可用')
                        check_actions(page)
                        page.screenshot(path=str(artifacts/(path.strip('/').replace('.html', '')+'-'+str(width)+'.png')))

                        def new_document(route):
                            response = route.fetch()
                            source = re.sub(r'(id="site-release"[^>]*data-version=")[a-f0-9]{64}',
                                            r'\g<1>'+'f'*64, response.text())
                            route.fulfill(response=response, body=source)

                        page.route('**'+path, new_document)
                        if path == '/chat': page.once('dialog', lambda dialog: dialog.accept())
                        with page.expect_event('domcontentloaded'):
                            page.locator('#update-refresh').click()
                        expect(page.locator('#site-release')).to_have_attribute('data-version', 'f'*64)
                        expect(page.locator('#site-update-toggle')).to_have_attribute('data-state', 'current')
                        expect(page.locator('#site-patch-note')).to_be_hidden()  # Once per account/version, not twice.
                        page.locator('#site-update-toggle').click()
                        expect(page.locator('#patch-note-text')).to_contain_text(NOTE_EN)
                        expect(page.locator('#update-refresh')).to_be_hidden()
                        page.keyboard.press('Escape')
                        expect(page.locator('#site-patch-note')).to_be_hidden()
                        expect(page.locator('#site-update-toggle')).to_be_focused()
                        # Only the chat's tab-scoped workspace reference is stored, never update state or drafts.
                        stored = page.evaluate('[localStorage.length, Object.entries(sessionStorage)]')
                        assert stored[0] == 0 and all(key.startswith('goodmorning.chat.workspace.') and 'Preserve' not in value
                                                      for key, value in stored[1]), stored
                        assert not errors, errors
                        cases.append({'path': path, 'width': width, 'languages': ['en', 'zh-CN'], 'historyEntries': len(current['notes']),
                                      'firstVisit': True, 'arrowAfterDismiss': True, 'checkmarkAfterUpdate': True, 'draftSafety': True})
                        context.close()

                # Real persistence, not a network mock: another browser shares this local account.
                page = browser.new_page(); page.clock.install(); page.goto(address+'/chat')
                expect(page.locator('#site-patch-note')).to_be_visible()
                page.locator('#patch-note-dismiss').click()
                expect(page.locator('#site-patch-note')).to_be_hidden()
                assert json.loads((root/'release-seen.json').read_text())['version'] == current['release']
                page.close()
                other = browser.new_context(); page = other.new_page(); page.goto(address+'/gn')
                expect(page.locator('#site-update-toggle')).to_be_visible()
                expect(page.locator('#site-patch-note')).to_be_hidden()
                other.close()

                # A rollback does not undo a dismissal recorded by a newer deployment.
                (root/'release-seen.json').write_text(json.dumps({'version': NOTE['version']}))
                page = browser.new_page(); page.goto(address+'/chat')
                expect(page.locator('#site-update-toggle')).to_be_visible()
                expect(page.locator('#site-patch-note')).to_be_hidden()
                page.close()

                # Returning users who missed a deployment see notes after a manual refresh.
                (root/'release-seen.json').write_text('{"version":"0.18.3"}')
                page = browser.new_page(); page.clock.install(); page.goto(address+'/chat')
                expect(page.locator('#site-patch-note')).to_be_visible()
                page.locator('#patch-note-dismiss').click()
                expect(page.locator('#site-patch-note')).to_be_hidden()

                # Pending messages block updates even from the new dialog.
                held = []
                page.route('**/api/chats', lambda route: held.append(route) if route.request.method == 'POST' else route.continue_())
                page.locator('#chat-text').fill('Synthetic pending request')
                with page.expect_request(lambda request: request.method == 'POST' and request.url.endswith('/api/chats')):
                    page.locator('#chat-send').click()
                page.route('**/api/release', lambda route: route.fulfill(json=state['payload']))
                page.clock.run_for(61000)
                expect(page.locator('#site-patch-note')).to_be_visible()
                page.locator('#update-refresh').click()
                expect(page.locator('#update-feedback')).to_contain_text('finish sending')
                check_actions(page)
                expect(page.locator('#chat-text')).to_have_value('Synthetic pending request')
                assert len(held) == 1
                held[0].fulfill(status=400, json={'error': 'Synthetic rejected request; no dispatch.'})
                page.close(); browser.close()
            result = {'modelCalls': 0, 'baselineFirstVisitPopup': False, 'fixedFirstVisitPopup': True, 'cases': cases,
                      'manualRefreshAfterMissedRelease': True, 'crossDeviceDismissal': True, 'rollbackPreservesDismissal': True, 'pendingMutationBlocksRefresh': True,
                      'privateBrowserStorage': 'chat workspace reference only'}
            (artifacts/'result.json').write_text(json.dumps(result, indent=2)); print(json.dumps(result))
        finally:
            process.terminate(); process.communicate(timeout=5)


if __name__ == '__main__': main()
