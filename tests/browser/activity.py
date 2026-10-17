"""Single-host tab reminders through a synthetic gateway; never a real model."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO/'tests'))
sys.path.insert(0, str(REPO/'tests/browser'))


def fixture(root):
    import support
    from language import fixture as language_fixture
    original = support.MockChamber
    class ActivityChamber(original):
        def stage(self):
            return (root/'activity-state').read_text() if (root/'activity-state').exists() else 'waiting'

        def pending(self, session):
            return super().pending(session) if self.stage() == 'waiting' else ([], [])

        def control(self, action, **body):
            if action == 'session.status':
                return {'sessionStatus': {'type': 'idle' if self.stage() == 'idle' else 'busy'}}
            return super().control(action, **body)

        def request(self, path, body=None):
            if path == '/api/openchamber/control':
                return {'sessionStatus': {'type': 'idle' if self.stage() == 'idle' else 'busy'}}
            return super().request(path, body)
    support.MockChamber = ActivityChamber
    language_fixture(root, hosts={'gm.language.test': 'gm'})


def run(artifacts):
    from playwright.sync_api import sync_playwright, expect
    artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='gm-activity-') as directory:
        root = Path(directory)
        process = subprocess.Popen([sys.executable, __file__, '--serve', directory], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            while True:
                line = process.stdout.readline()
                if line.startswith('{'):
                    settings = json.loads(line); break
                if not line:
                    raise RuntimeError('Synthetic fixture failed: '+process.stderr.read()[-1500:])
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                def context(width=1440):
                    result = browser.new_context(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
                    def forward(route):
                        parsed = urlsplit(route.request.url)
                        headers = {**route.request.all_headers(), 'Host': parsed.hostname, 'X-Forwarded-Proto': 'https', 'X-Real-IP': '192.0.2.1'}
                        response = route.fetch(url=settings['gateway']+parsed.path+('?' + parsed.query if parsed.query else ''), headers=headers, max_redirects=0)
                        route.fulfill(response=response)
                    result.route('https://*.language.test/**', forward)
                    return result
                def login(page, host, name, password):
                    page.goto('https://'+host+'.language.test/login')
                    page.locator('input[name=username]').fill(name)
                    page.locator('#password-password').fill(password)
                    with page.expect_navigation(wait_until='load'):
                        page.locator('#account-form button[type=submit]').click()
                    expect(page).not_to_have_url('https://'+host+'.language.test/login')
                def permanent(page, name):
                    expect(page.get_by_role('heading', name='Change password', exact=True)).to_be_visible()
                    page.locator('#patch-note-dismiss').click()
                    expect(page.locator('#site-patch-note')).to_be_hidden()
                    page.locator('input[name=current]').fill('a1'+name+'-temporary')
                    page.locator('input[name=replacement]').fill('a1'+name+'-permanent')
                    page.locator('input[name=repeat]').fill('a1'+name+'-permanent')
                    with page.expect_navigation(wait_until='load'):
                        with page.expect_response('**/api/auth/password') as changed:
                            page.locator('#account-form button[type=submit]').click()
                    assert changed.value.status == 200
                    page.goto('https://gm.language.test/chat')
                    expect(page.locator('#chat-compose')).to_be_visible()
                errors = []
                def check_position(page):
                    width = page.viewport_size['width']
                    gutter = 16 if width <= 700 else 24
                    side = 'left' if urlsplit(page.url).path == '/chat' else 'right'
                    expect(page.locator('#account-activity')).to_have_css(side, f'{gutter}px')
                    visible = page.locator('#activity-window') if page.locator('#activity-window').is_visible() else page.locator('#activity-restore')
                    box = visible.bounding_box()
                    distance = box['x'] if side == 'left' else page.evaluate('document.documentElement.clientWidth') - box['x'] - box['width']
                    assert abs(distance - gutter) < 1, (side, width, box)
                    expect(visible).to_be_in_viewport()
                owner = context()
                source = owner.new_page(); source.on('pageerror', lambda error: errors.append(str(error)))
                # This scenario starts initialization, so begin with an incomplete synthetic profile.
                profile = Path(settings['runtimes']['alice'])/'profile.md'
                saved_profile = profile.read_text()
                profile.write_text('secretary_language: English\n')
                login(source, 'gm', 'alice', 'a1alice-temporary'); permanent(source, 'alice')
                expect(source.locator('#chat-topic-mode')).to_have_text('Initialize')
                started = time.monotonic()
                with source.expect_response('**/api/activity', timeout=1000):
                    source.get_by_role('button', name='Start initialization', exact=True).click()
                submit_refresh = round((time.monotonic()-started)*1000)
                expect(source.get_by_role('heading', name='Confirm your location')).to_be_visible()
                profile.write_text(saved_profile)
                original_url = source.url
                pages = []
                for kind in ('gm', 'gn'):
                    page = owner.new_page(); page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto('https://gm.language.test/'+kind+'.html'); pages.append(page)
                extra = owner.new_page(); extra.goto('https://gm.language.test/chat'); pages.append(extra)
                source.close()  # The original tab closes with a real pending form.
                for page in pages:
                    page.bring_to_front(); page.evaluate('window.dispatchEvent(new Event("focus"))')
                    expect(page.locator('#account-activity')).to_be_visible()
                    expect(page.locator('#account-activity')).to_contain_text('Your secretary needs your answer')
                    expect(page.locator('#account-activity a')).to_have_attribute('href', original_url)
                    assert page.locator('#account-activity a').get_attribute('target') is None
                    expect(page.locator('#account-activity')).to_have_css('position', 'fixed')
                    expect(page.locator('.activity-pencil')).to_have_css('animation-name', 'none')
                    for width in (1440, 390, 320):
                        page.set_viewport_size({'width': width, 'height': 900})
                        check_position(page)
                        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                        page.screenshot(path=str(artifacts/f'position-{urlsplit(page.url).path.strip("/")}-{width}.png'))
                    page.set_viewport_size({'width': 1440, 'height': 900})
                page = pages[0]
                page.evaluate("""() => {
                    const button = document.createElement('button');
                    button.id = 'fixture-corner-control';
                    button.className = 'back-to-top is-visible';
                    button.textContent = 'Top';
                    document.body.append(button);
                }""")
                # Activity stacks above the back-to-top control and the quick chat launcher.
                above = """selector => {
                    const panel = document.querySelector('#account-activity').getBoundingClientRect();
                    return [...document.querySelectorAll(selector)].filter(node => node.getClientRects().length)
                        .every(node => panel.bottom < node.getBoundingClientRect().top);
                }"""
                expect(page.locator('#quick-chat-launcher')).to_be_visible()
                page.wait_for_function(above, arg='#fixture-corner-control, #quick-chat-launcher')
                page.locator('#fixture-corner-control').evaluate('node => node.remove()')
                expect(page.locator('#account-activity')).to_have_css('bottom', '92px')
                assert page.evaluate(above, '#quick-chat-launcher')
                # Back to top joins the launcher's row; on wide screens it starts at the card's left edge.
                for night in pages[:2]:
                    night.bring_to_front()
                    for width in (1440, 390):
                        night.set_viewport_size({'width': width, 'height': 900})
                        night.evaluate("scrollTo({top: document.documentElement.scrollHeight, behavior: 'instant'})")
                        expect(night.locator('.back-to-top')).to_have_css('opacity', '1')
                        night.wait_for_timeout(400)
                        top, pill, card = (night.locator(selector).bounding_box() for selector in ('.back-to-top', '#quick-chat-launcher', '#activity-window'))
                        assert abs(top['y'] + top['height'] / 2 - pill['y'] - pill['height'] / 2) < 1, (top, pill)
                        assert top['x'] + top['width'] + 8 <= pill['x'], (top, pill)
                        assert card['y'] + card['height'] < top['y'], (top, card)
                        if width > 700: assert abs(top['x'] - card['x']) < 1, (top, card)
                        else: assert abs(pill['x'] - top['x'] - top['width'] - 10) < 1, (top, pill)
                        night.screenshot(path=str(artifacts/f'stack-{urlsplit(night.url).path.strip("/")}-{width}.png'))
                    night.set_viewport_size({'width': 1440, 'height': 900})
                    night.evaluate("scrollTo({top: 0, behavior: 'instant'})")
                page.bring_to_front()
                page = pages[-1]
                page.get_by_role('button', name='Minimize activity', exact=True).click()
                expect(page.locator('#activity-window')).to_be_hidden()
                expect(page.locator('#activity-restore')).to_be_focused()
                check_position(page)
                page.locator('#activity-restore').click()
                expect(page.locator('#activity-window')).to_be_visible()
                expect(page.get_by_role('button', name='Minimize activity', exact=True)).to_be_focused()
                check_position(page)
                phone = owner.new_page(); phone.set_viewport_size({'width': 390, 'height': 900})
                phone.goto('https://gm.language.test/chat')
                expect(phone.locator('#activity-restore')).to_be_visible()
                expect(phone.locator('#activity-window')).to_be_hidden()
                check_position(phone)
                phone.locator('#activity-restore').click()
                expect(phone.locator('#activity-window')).to_be_visible()
                check_position(phone)
                phone.close()
                other = context(390); bob = other.new_page()
                login(bob, 'gm', 'bob', 'a1bob-temporary'); permanent(bob, 'bob')
                expect(bob.locator('#account-activity')).to_be_hidden()
                assert bob.evaluate("fetch('/api/activity').then(response => response.json())") == {'activity': []}
                page = pages[-1]
                for width in (1440, 390, 320):
                    page.set_viewport_size({'width': width, 'height': 900})
                    if page.locator('#prefs-menu').get_attribute('open') is None:
                        page.locator('#prefs-menu > summary').click()
                    page.locator('#website-language').select_option('zh-CN')
                    expect(page.locator('#account-activity')).to_contain_text('秘书需要你的回答')
                    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                    page.locator('#account-activity').screenshot(path=str(artifacts/f'waiting-{width}-zh-CN.png'))
                    page.locator('#website-language').select_option('en')
                    expect(page.locator('#account-activity')).to_contain_text('Your secretary needs your answer')
                page.route('**/api/activity', lambda route: route.fulfill(status=503, json={'error': 'Synthetic outage'}), times=1)
                page.evaluate('window.dispatchEvent(new Event("focus"))')
                expect(page.locator('#account-activity')).to_contain_text('Activity status is unavailable')
                expect(page.locator('#account-activity a')).to_have_attribute('href', original_url)
                (root/'activity-state').write_text('working')
                for page in pages:
                    page.bring_to_front(); page.evaluate('window.dispatchEvent(new Event("focus"))')
                    expect(page.locator('#account-activity')).to_contain_text('Your secretary is working')
                page = pages[-1]
                page.set_viewport_size({'width': 1440, 'height': 900})
                page.emulate_media(reduced_motion='no-preference')
                expect(page.locator('.activity-pencil')).to_have_css('animation-name', 'activity-pencil-write')
                page.locator('#activity-window').screenshot(path=str(artifacts/'little-desk-working.png'))
                page.emulate_media(reduced_motion='reduce')
                expect(page.locator('.activity-pencil')).to_have_css('animation-name', 'none')
                # Observe real server changes without focus events or manual refreshes.
                page.bring_to_front()
                latency = {}
                (root/'activity-state').write_text('idle')
                started = time.monotonic()
                expect(page.locator('#account-activity')).to_be_hidden(timeout=2500)
                latency['finishMs'] = round((time.monotonic()-started)*1000)
                page.emulate_media(reduced_motion='no-preference')
                (root/'activity-state').write_text('waiting')
                started = time.monotonic()
                expect(page.locator('#account-activity')).to_be_visible(timeout=2500)
                latency['startMs'] = round((time.monotonic()-started)*1000)
                def pause_motion(selector, current_time):
                    page.wait_for_function('''selector => document.querySelector(selector).getAnimations()
                        .some(animation => animation.playState === 'running')''', arg=selector)
                    return page.locator(selector).evaluate('''(node, time) => {
                        const animation = node.getAnimations().find(item => item.playState === 'running');
                        animation.pause(); animation.currentTime = time;
                        return {opacity: Number(getComputedStyle(node).opacity), hidden: node.hidden, inert: node.inert};
                    }''', current_time)
                entering = pause_motion('#account-activity', 100)
                assert 0 < entering['opacity'] < 1 and not entering['hidden'], entering
                page.locator('#account-activity').evaluate('node => node.getAnimations().forEach(animation => animation.finish())')
                page.locator('#account-activity a').focus()
                page.evaluate('window.activityRow = document.querySelector(".activity-item")')
                (root/'activity-state').write_text('working')
                started = time.monotonic()
                expect(page.locator('.activity-item')).to_have_attribute('data-state', 'working', timeout=1500)
                latency['changeMs'] = round((time.monotonic()-started)*1000)
                changing = pause_motion('.activity-item', 100)
                assert 0 < changing['opacity'] < 1, changing
                assert page.evaluate('window.activityRow === document.querySelector(".activity-item")')
                expect(page.locator('#account-activity a')).to_be_focused()
                page.locator('.activity-item').evaluate('node => node.getAnimations().forEach(animation => animation.finish())')
                (root/'activity-state').write_text('idle')
                exiting = pause_motion('#account-activity', 100)
                assert 0 < exiting['opacity'] < 1 and not exiting['hidden'] and exiting['inert'], exiting
                # A new request during the exit must cancel that exit, not hide new work.
                (root/'activity-state').write_text('working')
                with page.expect_response('**/api/activity'):
                    page.evaluate('document.dispatchEvent(new Event("activity:refresh"))')
                expect(page.locator('#account-activity')).to_have_css('opacity', '1')
                assert page.locator('#account-activity').evaluate('node => !node.hidden && !node.inert')
                page.emulate_media(reduced_motion='reduce')
                # Multiple queued requests remain bounded and preserve every original link.
                queued = [{'mode': 'todo', 'state': 'queued', 'url': 'https://gm.language.test/chat?id='+format(index, '032x')}
                          for index in range(20)]
                page.route('**/api/activity', lambda route: route.fulfill(json={'activity': queued}))
                page.evaluate('window.dispatchEvent(new Event("focus"))')
                expect(page.locator('#account-activity a')).to_have_count(20)
                assert page.locator('#activity-items').evaluate('node => node.scrollHeight > node.clientHeight')
                assert page.locator('#activity-window').evaluate('node => node.getBoundingClientRect().top >= 0 && node.getBoundingClientRect().bottom <= innerHeight')
                for width in (390, 320):
                    page.set_viewport_size({'width': width, 'height': 900})
                    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                page.unroute('**/api/activity')
                (root/'activity-state').write_text('waiting')
                page.evaluate('window.dispatchEvent(new Event("focus"))')
                expect(page.locator('#account-activity a')).to_have_count(1)
                expect(page.locator('#account-activity a')).to_have_attribute('href', original_url)
                count = len(owner.pages)
                page.locator('#account-activity a').click()
                expect(page).to_have_url(original_url)
                expect(page.get_by_role('heading', name='Confirm your location')).to_be_visible()
                assert len(owner.pages) == count
                (root/'activity-state').write_text('idle')
                for page in pages:
                    page.bring_to_front(); page.evaluate('window.dispatchEvent(new Event("focus"))')
                    expect(page.locator('#account-activity')).to_be_hidden()
                    assert page.evaluate(r'''() => localStorage.length === 0 && Object.keys(sessionStorage).every(key => {
                        if (!/^goodmorning\.chat\.workspace\.[a-f0-9]{64}$/.test(key)) return false;
                        const value = JSON.parse(sessionStorage.getItem(key));
                        return Object.keys(value).sort().join(',') === 'away,chat,draft,resume'
                            && [value.chat, value.resume].every(id => id === null || /^[a-f0-9]{32}$/.test(id))
                            && (value.away === null || Number.isFinite(value.away)) && typeof value.draft === 'boolean';
                    })''')
                assert not errors, errors
                browser.close()
            print(json.dumps({'modelCalls': 0, 'subdomains': 1, 'observerTabs': 3, 'closedOriginalTab': True,
                'exactChatInCurrentTab': True, 'newTabsOpened': 0,
                'waitingWorkingIdle': True, 'ownerIsolation': True, 'outageKeepsLink': True,
                'floatingDesk': True, 'minimizeAndRestore': True, 'mobileStartsMinimized': True,
                'workingAnimation': True, 'reducedMotion': True, 'boundedQueue': 20,
                'submitRefreshMs': submit_refresh, 'automaticRefreshMs': latency,
                'enterChangeExitMotion': True, 'exitReversal': True,
                'stateChangesPreserveFocus': True,
                'chatBottomLeft': True, 'otherPagesBottomRight': True, 'backToTopCollisionAvoided': True,
                'widths': [1440, 390, 320], 'languages': ['en', 'zh-CN'], 'pageErrors': 0}))
        finally:
            process.terminate(); process.communicate(timeout=5)


if __name__ == '__main__':
    if '--serve' in sys.argv: fixture(Path(sys.argv[-1]))
    else: run(Path(sys.argv[1]))
