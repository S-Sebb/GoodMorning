"""Whole-site palette switching through the real gateway and synthetic accounts."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect

REPO = Path(__file__).resolve().parents[2]


def main():
    artifacts = Path(sys.argv[1]); artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='gm-schemes-') as directory:
        process = subprocess.Popen([sys.executable, str(REPO/'tests/browser/language.py'), '--serve', directory],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            while True:
                line = process.stdout.readline()
                if line.startswith('{'):
                    settings = json.loads(line); break
                if not line: raise RuntimeError('Synthetic palette fixture did not start.')
            runtime = Path(settings['runtimes']['alice'])
            sys.path.insert(0, str(REPO/'src'))
            from goodmorning.briefings.briefing_document import encode
            # Only this isolated fixture gets editorial sample content for visual review.
            sample = {'v': 1, 'lang': 'en', 'greeting': 'A little room for today.',
                      'opening': 'A fresh start, a clear plan, and one thing at a time.',
                      'sections': [['notes', [['p', 'Start slowly. There is room to do good work today.'],
                                             ['p', 'Take a moment to settle in, then give your best attention to what matters.']]],
                                   ['today', [['tasks', [['open', 'Make space for focused work', 'Choose one meaningful task and protect a quiet hour.'],
                                                        ['open', 'Step outside', 'A short walk and a change of light can make a difference.']]]]]]}
            for path in (runtime/'daily').glob('*.json'):
                path.write_text(encode(sample))
            preserved = {path: hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in [runtime/'profile.md', *sorted((runtime/'daily').glob('*.json'))]}
            errors = []
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(ignore_default_args=['--hide-scrollbars'])
                def context(width=1440):
                    result = browser.new_context(viewport={'width': width, 'height': 1000}, reduced_motion='reduce')
                    def forward(route):
                        parsed = urlsplit(route.request.url)
                        headers = {**route.request.all_headers(), 'Host': parsed.hostname,
                            'X-Forwarded-Proto': 'https', 'X-Real-IP': '192.0.2.1'}
                        response = route.fetch(url=settings['gateway']+parsed.path+('?' + parsed.query if parsed.query else ''),
                                               headers=headers, max_redirects=0)
                        route.fulfill(response=response)
                    result.route('https://*.language.test/**', forward)
                    return result
                def page_in(context):
                    page = context.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.clock.set_system_time(datetime.fromisoformat('2026-10-12T10:00:00+00:00'))
                    return page
                def prefs(page):
                    if page.locator('#prefs-menu').get_attribute('open') is None:
                        page.locator('#prefs-menu > summary').click()
                def login(page, host, name, password):
                    page.goto('https://'+host+'.language.test/login')
                    page.locator('input[name=username]').fill(name)
                    page.locator('#password-password').fill(password)
                    with page.expect_response('**/api/auth/login') as changed:
                        page.locator('#account-form button[type=submit]').click()
                    assert changed.value.status == 200, changed.value.json()
                    expect(page).not_to_have_url('https://'+host+'.language.test/login')
                def permanent(page, name):
                    expect(page.get_by_role('heading', name='Change password', exact=True)).to_be_visible()
                    expect(page.locator('#site-patch-note')).to_be_visible()
                    page.locator('#patch-note-dismiss').click()
                    expect(page.locator('#site-patch-note')).to_be_hidden()
                    page.locator('input[name=current]').fill('a1'+name+'-temporary')
                    expect(page.locator('input[name=current]')).to_have_value('a1'+name+'-temporary')
                    page.locator('input[name=replacement]').fill('a1'+name+'-permanent')
                    page.locator('input[name=repeat]').fill('a1'+name+'-permanent')
                    with page.expect_response('**/api/auth/password') as changed:
                        page.locator('#account-form button[type=submit]').click()
                    assert changed.value.status == 200, changed.value.json()
                    expect(page.locator('#chat-compose')).to_be_visible()
                def choose(page, value, theme='day'):
                    prefs(page)
                    expect(page.locator('#day-color-scheme option')).to_have_count(4)
                    expect(page.locator('#night-color-scheme option')).to_have_count(2)
                    with page.expect_response('**/api/color-schemes') as response:
                        page.locator('#'+theme+'-color-scheme').select_option(value)
                    assert response.value.status == 200
                    expect(page.locator('html')).to_have_attribute('data-'+theme+'-scheme', value)
                    expect(page.locator('#'+theme+'-color-scheme')).to_be_enabled()
                def background(page):
                    return page.locator('body').evaluate('node => getComputedStyle(node).backgroundColor')
                def stars(page):
                    return page.locator('body').evaluate('node => getComputedStyle(node).backgroundImage')

                owner = context(); chat = page_in(owner)
                login(chat, 'sec', 'alice', 'a1alice-temporary'); permanent(chat, 'alice')
                expect(chat.locator('html')).to_have_attribute('data-edition', 'gm')
                expect(chat.locator('html')).to_have_attribute('data-night-scheme', 'starry')
                choose(chat, 'classic', 'night')
                chat.locator('#chat-text').fill('Keep this private, unsent draft.')
                original_url = chat.url
                choose(chat, 'warm')
                expect(chat.locator('#chat-text')).to_have_value('Keep this private, unsent draft.')
                assert chat.url == original_url and background(chat) == 'rgb(246, 238, 227)'
                expect(chat.locator('.conversation-panel')).to_have_css('background-color', 'rgb(255, 251, 245)')
                expect(chat.locator('.toolbar-row .menu-panel').first).to_have_css('background-color', 'rgb(255, 251, 245)')
                chat.locator('#prefs-menu > summary').click()
                # This known, synthetic activity exercises the floating desk palette,
                # without creating a real work reservation or model request.
                chat.route('**/api/activity', lambda route: route.fulfill(json={'activity': [
                    {'mode': 'secretary', 'state': 'working', 'url': 'https://sec.language.test/chat?id='+'a'*32}]}))
                chat.evaluate('window.dispatchEvent(new Event("focus"))')
                expect(chat.locator('#account-activity')).to_be_visible()
                expect(chat.locator('#activity-window')).to_have_css('background-color', 'rgb(255, 251, 245)')
                chat.screenshot(path=str(artifacts/'warm-chat-full.png'), full_page=True)
                prefs(chat); chat.screenshot(path=str(artifacts/'scheme-settings.png'), full_page=True)
                layout = chat.evaluate("""() => {
                    const box = id => document.getElementById(id).getBoundingClientRect();
                    const language = box('website-language'), model = box('website-model');
                    const day = box('day-color-scheme'), night = box('night-color-scheme');
                    return {aligned: language.left === model.left && language.width === model.width,
                        paired: day.top === night.top && day.width === night.width};
                }""")
                assert layout == {'aligned': True, 'paired': True}, layout
                chat.get_by_role('button', name='Close settings', exact=True).click()
                expect(chat.locator('#prefs-menu')).not_to_have_attribute('open')
                prefs(chat); chat.keyboard.press('Escape')
                expect(chat.locator('#prefs-menu')).not_to_have_attribute('open')

                morning = page_in(owner); login(morning, 'gm', 'alice', 'a1alice-permanent')
                expect(morning.locator('html')).to_have_attribute('data-day-scheme', 'warm')
                assert background(morning) == background(chat)
                expect(morning.locator('.briefing-section').first).to_have_css('background-color', 'rgb(255, 251, 245)')
                morning.screenshot(path=str(artifacts/'warm-morning-full.png'), full_page=True)
                day_results = []
                for scheme, surface, translation in (
                        ('morning-sky', 'rgb(255, 253, 247)', '晨空'),
                        ('first-light', 'rgb(255, 250, 245)', '曙光')):
                    choose(morning, scheme)
                    morning.get_by_role('button', name='Close settings', exact=True).click()
                    scene = morning.evaluate("name => fetch('/' + name + '.svg').then(r => ({status: r.status, type: r.headers.get('content-type')}))", scheme)
                    assert scene['status'] == 200 and scene['type'].startswith('image/svg+xml')
                    if scheme == 'morning-sky':
                        clouds = morning.evaluate("fetch('/morning-clouds.webp').then(r => ({status: r.status, type: r.headers.get('content-type')}))")
                        assert clouds['status'] == 200 and clouds['type'].startswith('image/webp')
                    assert scheme + '.svg' in stars(morning) and '#' not in stars(morning)
                    expect(morning.locator('.briefing-section').first).to_have_css('background-color', surface)
                    morning.reload()
                    expect(morning.locator('html')).to_have_attribute('data-day-scheme', scheme)
                    morning.screenshot(path=str(artifacts/(scheme+'-full-page.png')), full_page=True, animations='disabled')
                    # Extend only the synthetic DOM, not saved records, to inspect several repeat lengths.
                    morning.evaluate('''() => {
                        const source = document.querySelector('.briefing-section');
                        for (let index = 1; index <= 12; index++) {
                            const section = source.cloneNode(true);
                            section.removeAttribute('id');
                            section.querySelectorAll('[id]').forEach(node => node.removeAttribute('id'));
                            section.querySelector('h2').textContent = 'A quiet moment · ' + index;
                            document.querySelector('main').append(section);
                        }
                    }''')
                    morning.screenshot(path=str(artifacts/(scheme+'-long-full-page.png')), full_page=True, animations='disabled')
                    morning.locator('footer').first.scroll_into_view_if_needed()
                    morning.screenshot(path=str(artifacts/(scheme+'-long-bottom.png')), animations='disabled')
                    morning.set_viewport_size({'width': 390, 'height': 1000})
                    morning.screenshot(path=str(artifacts/(scheme+'-long-mobile-full-page.png')), full_page=True, animations='disabled')
                    morning.set_viewport_size({'width': 1440, 'height': 1000})
                    morning.reload()
                    for width in (768, 390, 320):
                        morning.set_viewport_size({'width': width, 'height': 1000})
                        assert not morning.evaluate('document.documentElement.scrollWidth > innerWidth')
                        morning.screenshot(path=str(artifacts/(scheme+f'-{width}-full-page.png')), full_page=True, animations='disabled')
                    morning.set_viewport_size({'width': 1440, 'height': 1000})
                    morning.locator('footer').first.scroll_into_view_if_needed()
                    morning.screenshot(path=str(artifacts/(scheme+'-scrolled.png')), animations='disabled')
                    morning.evaluate('window.scrollTo(0, 0)')
                    morning.emulate_media(reduced_motion='no-preference')
                    if scheme == 'morning-sky':
                        assert '#drift' in stars(morning)
                    else:
                        assert '#' not in stars(morning)
                    morning.emulate_media(reduced_motion='reduce')
                    assert '#' not in stars(morning)
                    morning.emulate_media(media='print')
                    assert stars(morning) == 'none'
                    morning.emulate_media(media='screen')
                    chat.bring_to_front(); chat.evaluate('window.dispatchEvent(new Event("focus"))')
                    expect(chat.locator('html')).to_have_attribute('data-day-scheme', scheme)
                    expect(chat.locator('#chat-text')).to_have_value('Keep this private, unsent draft.')
                    expect(chat.locator('.conversation-panel')).to_have_css('background-color', surface)
                    chat.screenshot(path=str(artifacts/(scheme+'-chat.png')), animations='disabled')
                    chat.goto('https://sec.language.test/password')
                    expect(chat.locator('.account-card')).to_have_css('background-color', surface)
                    assert scheme + '.svg' in stars(chat)
                    prefs(chat); chat.locator('#website-language').select_option('zh-CN')
                    expect(chat.locator(f'#day-color-scheme option[value={scheme}]')).to_have_text(translation)
                    chat.locator('#website-language').select_option('en')
                    chat.goto('https://sec.language.test/chat')
                    chat.locator('#chat-text').fill('Keep this private, unsent draft.')
                    day_results.append(scheme)
                choose(morning, 'warm')
                morning.get_by_role('button', name='Close settings', exact=True).click()
                chat.bring_to_front(); chat.evaluate('window.dispatchEvent(new Event("focus"))')
                expect(chat.locator('html')).to_have_attribute('data-day-scheme', 'warm')
                evening = page_in(owner); login(evening, 'gn', 'alice', 'a1alice-permanent')
                expect(evening.locator('html')).to_have_attribute('data-night-scheme', 'classic')
                assert background(evening) == 'rgb(17, 28, 42)'
                evening.screenshot(path=str(artifacts/'classic-night-full.png'), full_page=True)
                choose(evening, 'starry', 'night')
                sky = evening.evaluate("fetch('/starry-sky.svg').then(response => ({status: response.status, type: response.headers.get('content-type')}))")
                assert sky['status'] == 200 and sky['type'].startswith('image/svg+xml')
                assert background(evening) == 'rgb(8, 15, 32)' and 'radial-gradient' in stars(evening)
                assert 'starry-sky.svg' in stars(evening)
                expect(evening.locator('body')).to_have_css('background-repeat', 'no-repeat, no-repeat')
                expect(evening.locator('.briefing-section').first).to_have_css('background-color', 'rgb(17, 28, 50)')
                evening.locator('#prefs-menu > summary').click()
                evening.screenshot(path=str(artifacts/'starry-night-full.png'), full_page=True)
                evening.screenshot(path=str(artifacts/'starry-night-viewport.png'))
                evening.locator('footer').first.scroll_into_view_if_needed()
                evening.screenshot(path=str(artifacts/'starry-night-scrolled.png'))
                evening.evaluate('window.scrollTo(0, 0)')
                evening.reload()
                expect(evening.locator('html')).to_have_attribute('data-night-scheme', 'starry')
                assert background(evening) == 'rgb(8, 15, 32)'
                for width in (390, 320):
                    evening.set_viewport_size({'width': width, 'height': 1000})
                    assert not evening.evaluate('document.documentElement.scrollWidth > innerWidth')
                    evening.screenshot(path=str(artifacts/f'starry-night-{width}.png'), full_page=True)
                    evening.screenshot(path=str(artifacts/f'starry-night-{width}-viewport.png'))
                evening.set_viewport_size({'width': 1440, 'height': 1000})
                choose(evening, 'classic', 'night')
                assert background(evening) == 'rgb(17, 28, 42)' and stars(evening) == 'none'
                choose(evening, 'starry', 'night')
                choose(evening, 'classic')
                assert background(evening) == 'rgb(8, 15, 32)'
                chat.bring_to_front(); chat.evaluate('window.dispatchEvent(new Event("focus"))')
                expect(chat.locator('html')).to_have_attribute('data-day-scheme', 'classic')
                expect(chat.locator('html')).to_have_attribute('data-night-scheme', 'starry')
                assert stars(chat) == 'none'
                expect(chat.locator('#chat-text')).to_have_value('Keep this private, unsent draft.')
                chat.locator('#prefs-menu > summary').click() if chat.locator('#prefs-menu').get_attribute('open') else None
                chat.screenshot(path=str(artifacts/'classic-chat-full.png'), full_page=True)
                choose(chat, 'warm')
                chat.reload(); expect(chat.locator('html')).to_have_attribute('data-day-scheme', 'warm')
                chat.locator('#chat-text').fill('Keep this private, unsent draft.')
                chat.clock.set_system_time(datetime.fromisoformat('2026-10-12T18:00:00+00:00'))
                chat.evaluate('window.dispatchEvent(new Event("focus"))')
                expect(chat.locator('html')).to_have_attribute('data-edition', 'gn')
                assert background(chat) == 'rgb(8, 15, 32)' and 'radial-gradient' in stars(chat)
                expect(chat.locator('.conversation-panel')).to_have_css('background-color', 'rgb(17, 28, 50)')
                expect(chat.locator('#chat-text')).to_have_value('Keep this private, unsent draft.')
                choose(chat, 'classic', 'night')
                assert background(chat) == 'rgb(17, 28, 42)' and stars(chat) == 'none'
                expect(chat.locator('#chat-text')).to_have_value('Keep this private, unsent draft.')
                choose(chat, 'starry', 'night')
                expect(chat.locator('#chat-text')).to_have_value('Keep this private, unsent draft.')
                chat.locator('#prefs-menu > summary').click()
                chat.screenshot(path=str(artifacts/'starry-chat-full.png'), full_page=True)
                expect(chat.locator('#day-color-scheme')).to_have_value('warm')
                chat.clock.set_system_time(datetime.fromisoformat('2026-10-12T10:00:00+00:00'))
                chat.evaluate('window.dispatchEvent(new Event("focus"))')
                expect(chat.locator('html')).to_have_attribute('data-edition', 'gm')
                assert background(chat) == 'rgb(246, 238, 227)'
                assert stars(chat) == 'none'

                chat.goto('https://sec.language.test/password')
                expect(chat.locator('.account-card')).to_have_css('background-color', 'rgb(255, 251, 245)')
                assert background(chat) == 'rgb(246, 238, 227)'
                prefs(chat); chat.locator('#website-language').select_option('zh-CN')
                expect(chat.locator('#day-color-scheme option[value=warm]')).to_have_text('暖色')
                expect(chat.locator('#night-color-scheme option[value=starry]')).to_have_text('星空')
                expect(chat.locator('label[for=night-color-scheme]')).to_have_text('夜间配色')
                chat.locator('#website-language').select_option('en')
                chat.goto('https://sec.language.test/chat')
                chat.locator('#chat-text').fill('A synthetic conversation for avatar checks.')
                chat.get_by_role('button', name='Start conversation', exact=True).click()
                expect(chat.locator('.reply-portrait')).to_have_count(1)
                expect(chat.get_by_role('button', name='Send reply', exact=True)).to_be_enabled()
                sys.path.insert(0, str(REPO/'tests'))
                from test_custom_avatar import portrait
                chat.locator('[data-avatar-file]').set_input_files({'name': 'synthetic-avatar.png', 'mimeType': 'image/png',
                    'buffer': portrait(color='#d1b28f', size=(300, 300))})
                expect(chat.locator('.avatar-display')).to_have_attribute('data-avatar', 'custom')
                expect(chat.locator('.reply-portrait')).to_have_attribute('data-chat-avatar', 'custom')
                expect(chat.locator('.reply-portrait img')).to_have_css('object-fit', 'cover')
                choose(chat, 'classic'); choose(chat, 'warm')
                expect(chat.locator('.reply-portrait')).to_have_attribute('data-chat-avatar', 'custom')
                for width in (1440, 768, 390, 320):
                    chat.set_viewport_size({'width': width, 'height': 1000})
                    prefs(chat)
                    assert not chat.evaluate('document.documentElement.scrollWidth > innerWidth')
                    bounds = chat.locator('#prefs-menu > .menu-panel').bounding_box()
                    assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= width, bounds
                    if width in (390, 320):chat.screenshot(path=str(artifacts/f'warm-site-{width}.png'), full_page=True)
                    chat.locator('#prefs-menu > summary').click()

                other = context(390); bob = page_in(other)
                login(bob, 'sec', 'bob', 'a1bob-temporary'); permanent(bob, 'bob')
                expect(bob.locator('html')).to_have_attribute('data-day-scheme', 'classic')
                assert bob.evaluate("fetch('/api/color-schemes').then(response => response.json())") == {'day': 'classic', 'night': 'starry'}
                assert not errors, errors
                browser.close()
            assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in preserved.items())
            report = {'modelCalls': 0, 'wholeSitePalette': True, 'classicNightUnchanged': True, 'starryNight': True,
                       'atmosphericDayThemes': day_results, 'dayReducedMotion': True, 'dayPrintClean': True,
                      'clockThemeIndependent': True, 'refreshAndCrossHost': True, 'draftPreserved': True,
                      'savedRecordsUnchanged': True, 'accountIsolation': True, 'bilingual': True,
                      'customAvatarsPreserved': True,
                      'settingsLayoutAligned': True, 'settingsDismissible': True,
                      'widths': [1440, 768, 390, 320], 'pageErrors': 0}
            (artifacts/'result.json').write_text(json.dumps(report, indent=2))
            print(json.dumps(report))
        finally:
            process.terminate(); process.communicate(timeout=5)


if __name__ == '__main__':
    main()
