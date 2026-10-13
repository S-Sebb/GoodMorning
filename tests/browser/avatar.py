"""Shared briefing avatars on isolated synthetic records; no model calls."""
import json
import io
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import expect, sync_playwright
from PIL import Image

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'src'))
from goodmorning.briefings.briefing_day import briefing_day
from goodmorning.briefings.briefing_document import encode


def check_avatar(page, selected, label):
    figure = page.locator('.briefing-avatar')
    expect(figure).to_have_attribute('data-avatar', selected)
    expect(figure).to_be_visible()
    expect(figure.locator('[data-avatar-toggle]')).to_be_enabled()
    assert figure.get_by_role('link').count() == 0
    image = figure.locator('.avatar-image')
    assert image.evaluate('node => node.complete && node.naturalWidth > 0')
    assert image.get_attribute('src').startswith('/assets/')
    assert page.locator('.celestial-art').count() == 1
    kind = page.locator('html').get_attribute('data-edition')
    assert page.locator('#sun-light' if kind == 'gm' else '#moon-light').count() == 1
    assert page.locator('.secretary-panel, .briefing-tools').count() == 0
    card = page.locator('.briefing-section').first
    assert card.evaluate('node => getComputedStyle(node).backgroundColor') != 'rgba(0, 0, 0, 0)'
    assert float(card.evaluate('node => parseFloat(getComputedStyle(node).borderTopLeftRadius)')) > 0
    letter = page.locator('.letter-copy').bounding_box()
    portrait = image.bounding_box()
    eyebrow = page.locator('.letter-copy > .eyebrow').bounding_box()
    assert abs(portrait['y'] - eyebrow['y']) < 1, (portrait, eyebrow)
    assert abs(portrait['height'] - letter['height']) < 1, (portrait, letter)
    expect(page.locator('.orbit')).to_be_visible()
    if page.viewport_size['width'] <= 700:
        assert page.locator('.briefing-section').first.bounding_box()['width'] >= page.viewport_size['width'] - 33
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')


def open_picker(page):
    if not page.locator('.avatar-menu').is_visible():
        page.locator('[data-avatar-toggle]').click()
    expect(page.locator('.avatar-menu')).to_be_visible()


def check_picker(page, address, artifacts):
    page.goto(address + '/chat')
    if page.locator('#prefs-menu').get_attribute('open') is None:
        page.locator('#prefs-menu > summary').click()
    page.locator('#website-language').select_option('en')
    expect(page.locator('html')).to_have_attribute('lang', 'en')
    for path in ('/gm.html', '/gn.html', '/chat'):
        page.goto(address + path)
        if page.viewport_size['width'] <= 700:
            for link in page.locator('.edition-link').all():
                bounds = link.bounding_box()
                text = link.locator('bdi').bounding_box()
                assert bounds['height'] >= 44
                icon_height=link.evaluate("node => parseFloat(getComputedStyle(node, '::before').height)")
                assert icon_height >= 20
                if link.evaluate('node => getComputedStyle(node).flexDirection')=='column':
                    assert abs((bounds['x']+bounds['width']/2)-(text['x']+text['width']/2)) < 2
                    assert text['y'] >= bounds['y']+icon_height
                    assert text['y']+text['height'] <= bounds['y']+bounds['height']
                else:
                    assert abs((bounds['y']+bounds['height']/2)-(text['y']+text['height']/2)) < 2
        open_picker(page)
        toggle = page.locator('[data-avatar-toggle]')
        expect(toggle).to_have_css('background-color', 'rgba(0, 0, 0, 0)')
        expect(toggle).to_have_css('box-shadow', 'none')
        expect(toggle).to_have_css('border-top-width', '0px')
        expect(toggle).to_have_css('color', 'rgb(53, 118, 91)')
        assert page.locator('.avatar-menu-heading, [data-avatar-close]').count() == 0
        assert page.locator('.avatar-menu').evaluate("node => getComputedStyle(node).backgroundColor") == 'rgba(0, 0, 0, 0)'
        assert page.locator('.avatar-menu').evaluate("node => getComputedStyle(node).padding") == '0px'
        assert page.locator('.avatar-menu').evaluate("node => getComputedStyle(node).boxShadow") == 'none'
        expect(page.locator('.avatar-feedback')).to_have_css('clip', 'rect(0px, 0px, 0px, 0px)')
        expect(page.get_by_role('button', name='Upload your own avatar')).to_be_visible()
        expect(page.locator('[data-avatar-choice]')).to_have_count(4)
        expect(page.locator('[data-avatar-toggle]')).to_have_attribute('aria-expanded', 'true')
        assert page.locator('.avatar-previews').evaluate('node => node.clientWidth') >= 68
        assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
        page.locator('[data-avatar-choice="f1"]').click()
        expect(page.locator('.avatar-feedback')).to_have_text('Avatar 1 of 4')
        page.locator('[data-avatar-next]').click()
        expect(page.locator('.avatar-feedback')).to_have_text('Avatar 2 of 4')
        expect(page.locator('[data-avatar-choice="f2"]')).to_have_attribute('aria-selected', 'true')
        page.locator('[data-avatar-choice="m2"]').click()
        expect(page.locator('.avatar-feedback')).to_have_text('Avatar 4 of 4')
        page.wait_for_function("""() => {
            const strip = document.querySelector('.avatar-previews').getBoundingClientRect();
            const selected = document.querySelector('.avatar-previews [aria-selected="true"]').getBoundingClientRect();
            return selected.left >= strip.left - 1 && selected.right <= strip.right + 1;
        }""")
        page.locator('[data-avatar-choice="m2"]').focus()
        page.keyboard.press('ArrowRight')
        expect(page.locator('.avatar-feedback')).to_have_text('Avatar 1 of 4')
        expect(page.locator('[data-avatar-choice="f1"]')).to_be_focused()
        page.keyboard.press('End')
        expect(page.locator('.avatar-feedback')).to_have_text('Avatar 4 of 4')
        page.keyboard.press('Escape')
        expect(page.locator('.avatar-menu')).to_be_hidden()
        expect(page.locator('[data-avatar-toggle]')).to_be_focused()
        open_picker(page)
        page.screenshot(path=str(artifacts / ('picker-' + path.strip('/').replace('.html', '') + '-' + str(page.viewport_size['width']) + '.png')))
        page.locator('header.masthead').click(position={'x': 4, 'y': 4})
        expect(page.locator('.avatar-menu')).to_be_hidden()

    # Selection stays responsive while one save is pending; the last click wins.
    page.goto(address + '/chat')
    open_picker(page)
    page.locator('[data-avatar-choice="f1"]').click()
    expect(page.locator('.avatar-feedback')).to_have_text('Avatar 1 of 4')
    pending = []
    held = False
    def pause(route):
        nonlocal held
        if route.request.method == 'POST' and not held:
            held = True
            pending.append(route)
        else:
            route.continue_()
    page.route('**/api/avatar', pause)
    with page.expect_request(lambda request: request.method == 'POST' and request.url.endswith('/api/avatar')):
        page.locator('[data-avatar-choice="f2"]').click()
    page.locator('[data-avatar-next]').click()
    page.locator('[data-avatar-next]').click()
    expect(page.locator('.avatar-display')).to_have_attribute('data-avatar', 'm2')
    assert page.evaluate("document.dispatchEvent(new Event('website:before-refresh', {cancelable: true}))") is False
    pending.pop().continue_()
    expect(page.locator('.avatar-feedback')).to_have_text('Avatar 4 of 4')
    page.unroute('**/api/avatar', pause)
    page.reload()
    expect(page.locator('.avatar-display')).to_have_attribute('data-avatar', 'm2')

    open_picker(page)
    def reject(route):
        if route.request.method == 'POST':
            route.fulfill(status=500, json={'error': 'Synthetic avatar failure'})
        else:
            route.continue_()
    page.route('**/api/avatar', reject)
    page.locator('[data-avatar-choice="f1"]').click()
    expect(page.locator('.avatar-feedback')).to_have_text('Avatar could not be saved. Try again.')
    expect(page.locator('.avatar-display')).to_have_attribute('data-avatar', 'm2')
    page.unroute('**/api/avatar', reject)
    page.goto(address + '/gm.html')
    expect(page.locator('.avatar-display')).to_have_attribute('data-avatar', 'm2')
    assert page.evaluate('localStorage.length === 0 && sessionStorage.length === 0')


def check_motion(browser, address):
    page = browser.new_page(viewport={'width': 1440, 'height': 900}, reduced_motion='no-preference')
    page.goto(address + '/chat')
    open_picker(page)
    expect(page.locator('.avatar-menu')).to_have_css('animation-name', 'avatar-menu-enter')
    page.set_viewport_size({'width': 390, 'height': 900})
    # The existing mobile picker is an inline carousel, not an animated popup.
    expect(page.locator('.avatar-menu')).to_have_css('animation-name', 'none')
    page.evaluate("""window.avatarFrames = [];
        const image = document.querySelector('.avatar-image');
        const observer = new MutationObserver(() => {
            const sample = () => {
                avatarFrames.push(Number(getComputedStyle(image).opacity));
                if (image.getAnimations().length) requestAnimationFrame(sample);
            };
            requestAnimationFrame(sample);
        });
        observer.observe(image, {attributes: true, attributeFilter: ['src']});""")
    current = page.locator('.avatar-display').get_attribute('data-avatar')
    next_avatar = 'm2' if current != 'm2' else 'f1'
    page.locator(f'[data-avatar-choice="{next_avatar}"]').click()
    page.wait_for_function('() => avatarFrames.some(opacity => opacity > 0.4 && opacity < 1)')
    page.wait_for_function("() => document.querySelector('.avatar-display').getAttribute('aria-busy') === 'false'")
    page.close()


def check_layout_alignment(browser, address, artifacts):
    results = []
    for width in (320, 390, 768, 1024, 1440, 1920):
        page = browser.new_page(viewport={'width': width, 'height': 1000}, reduced_motion='reduce')
        bounds = {}
        navigation = {}
        for path, selector in (('/gm.html', '.briefing-section'), ('/gn.html', '.briefing-section'), ('/chat', '.conversation-panel')):
            page.goto(address + path)
            box = page.locator(selector).first.bounding_box()
            if path == '/chat':
                sidebar = page.locator('.conversation-sidebar').bounding_box()
                bounds[path] = (sidebar['x'], box['x'] + box['width'])
                if width > 700:
                    assert box['x'] > sidebar['x'] + sidebar['width'], (width, sidebar, box)
                    assert abs(box['y'] - sidebar['y']) < 1, (width, sidebar, box)
                else:
                    assert box['y'] >= sidebar['y'] + sidebar['height'], (width, sidebar, box)
                    assert abs(box['x'] - sidebar['x']) < 1
            else:
                bounds[path] = (box['x'], box['x'] + box['width'])
            navigation[path] = page.locator('.edition-switch').bounding_box()
            # Compare document layout, not a viewport-relative position after
            # the browser has scrolled to the focused composer.
            navigation[path]['y'] += page.evaluate('scrollY')
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            if path == '/chat' and width in (390, 1440):
                page.screenshot(path=str(artifacts / f'aligned-secretary-{width}.png'), full_page=True)
        for path in ('/gn.html', '/chat'):
            assert all(abs(left - right) < 1 for left, right in zip(bounds['/gm.html'], bounds[path])), (width, bounds)
        if width <= 700:
            for path in ('/gn.html', '/chat'):
                for key in ('x', 'y', 'width', 'height'):
                    assert abs(navigation['/gm.html'][key] - navigation[path][key]) < 1, (width, navigation)
        results.append({'width': width, 'left': round(bounds['/chat'][0]), 'right': round(bounds['/chat'][1]),
                        'briefingAndChatFrameEdgesMatch': True, 'desktopSidebarPreserved': width > 700})
        page.close()
    return results


def main():
    artifacts = Path(sys.argv[1])
    artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    results = []
    with tempfile.TemporaryDirectory(dir='/tmp/opencode', prefix='gm-avatar-browser-') as directory:
        root = Path(directory)
        (root / 'profile.md').write_text('secretary_language: English\ntimezone: Europe/London\ncity: London, GB\nnews_country: GB\n')
        (root / 'daily').mkdir()
        day = briefing_day('Europe/London')
        document = encode({'v': 1, 'lang': 'en', 'greeting': 'A little room to breathe.',
                           'opening': 'Your priorities, prepared by your secretary.',
                           'sections': [['notes', [['p', 'Keep this saved briefing unchanged.']]]]})
        process = subprocess.Popen([sys.executable, str(REPO / 'tests/test_briefing_server.py'), '--serve-fixture', directory],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        address = process.stdout.readline().strip().removeprefix('Private live viewer: ')
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                alignment_checks = check_layout_alignment(browser, address, artifacts)
                check_motion(browser, address)
                (root / 'website-avatar.json').write_text('{"avatar":"f1"}\n')
                for width in (1440, 768, 390, 320):
                    page = browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    if width == 1440:
                        for kind in ('gm', 'gn'):
                            page.goto(address + f'/{kind}.html')
                            check_avatar(page, 'f1', 'Your secretary')
                            expect(page.locator('#generate')).to_be_visible()
                            page.screenshot(path=str(artifacts / f'avatar-preview-{kind}.png'), full_page=True)
                            page.screenshot(path=str(artifacts / f'layout-preview-{kind}.png'))
                            (root / 'daily' / f'{day}.{kind}.json').write_text(document)
                    check_picker(page, address, artifacts)
                    for language, label in (('en', 'Your secretary'), ('zh-CN', '你的秘书')):
                        page.goto(address + '/chat')
                        if page.locator('#prefs-menu').get_attribute('open') is None:
                            page.locator('#prefs-menu > summary').click()
                        page.locator('#website-language').select_option(language)
                        expect(page.locator('html')).to_have_attribute('lang', language)
                        for selected in ('f1', 'f2', 'm1', 'm2'):
                            page.goto(address + '/chat')
                            open_picker(page)
                            page.locator(f'[data-avatar-choice="{selected}"]').click()
                            expect(page.locator('.avatar-feedback')).not_to_have_text('Saving avatar…' if language == 'en' else '正在保存形象…')
                            expect(page.locator('.avatar-display')).to_have_attribute('aria-busy', 'false')
                            expect(page.locator('.desk-figure')).to_have_attribute('data-avatar', selected)
                            for kind in ('gm', 'gn'):
                                page.goto(address + f'/{kind}.html')
                                check_avatar(page, selected, label)
                                expect(page.get_by_role('article')).to_contain_text('Keep this saved briefing unchanged.')
                                if selected == 'm2':
                                    page.screenshot(path=str(artifacts / f'avatar-{kind}-{width}-{language}.png'), full_page=True)
                                page.goto(address + f'/d/{day}/{kind}.html')
                                check_avatar(page, selected, label)
                    assert not errors, errors
                    results.append({'width': width, 'languages': ['en', 'zh-CN'], 'avatars': 4,
                                    'editions': ['gm', 'gn'], 'archive': True, 'overflow': False, 'pageErrors': 0})
                    page.close()
                page = browser.new_page(java_script_enabled=False, viewport={'width': 390, 'height': 844}, reduced_motion='reduce')
                page.goto(address + '/gm.html')
                expect(page.locator('.avatar-display')).to_have_attribute('data-avatar', 'm2')
                expect(page.locator('[data-avatar-toggle]')).to_be_disabled()
                assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                page.close()
                # Already-open pages discover the new custom choice and replacements.
                observer = browser.new_page()
                observer.goto(address + '/gm.html')
                uploader = browser.new_page()
                uploader.goto(address + '/chat')
                for color in ('purple', 'orange'):
                    uploader.bring_to_front()
                    open_picker(uploader)
                    image = io.BytesIO()
                    Image.new('RGB', (120, 160), color).save(image, format='PNG')
                    with uploader.expect_response('**/api/avatar/upload') as uploaded:
                        uploader.locator('[data-avatar-file]').set_input_files({
                            'name': 'avatar.png', 'mimeType': 'image/png', 'buffer': image.getvalue()})
                    custom_source = uploaded.value.json()['avatars'][-1]['src']
                    expect(uploader.locator('.avatar-display')).to_have_attribute('aria-busy', 'false')
                    observer.bring_to_front()
                    # Headless Chromium does not reliably emit window focus on tab activation.
                    observer.evaluate("window.dispatchEvent(new Event('focus'))")
                    expect(observer.locator('.avatar-display')).to_have_attribute('data-avatar', 'custom')
                    expect(observer.locator('.avatar-image')).to_have_attribute('src', custom_source)
                    expect(observer.locator('[data-avatar-choice]')).to_have_count(5)
                observer.close()
                uploader.close()
                for width in (1440, 390, 320):
                    page = browser.new_page(viewport={'width': width, 'height': 900}, reduced_motion='reduce')
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(address + '/chat')
                    open_picker(page)
                    image = io.BytesIO()
                    Image.new('RGB', (120, 160), 'teal').save(image, format='PNG')
                    with page.expect_response('**/api/avatar/upload') as response:
                        page.locator('[data-avatar-file]').set_input_files({
                            'name': 'my-secretary.png', 'mimeType': 'image/png', 'buffer': image.getvalue()})
                    assert response.value.status == 201
                    custom_source = response.value.json()['avatars'][-1]['src']
                    expect(page.locator('.avatar-display')).to_have_attribute('data-avatar', 'custom')
                    expect(page.locator('[data-avatar-choice]')).to_have_count(5)
                    expect(page.locator('.avatar-display')).to_have_attribute('aria-busy', 'false')
                    open_picker(page)
                    page.screenshot(path=str(artifacts / f'custom-avatar-{width}.png'))
                    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                    for path in ('/gm.html', '/gn.html', f'/d/{day}/gm.html', f'/d/{day}/gn.html'):
                        page.goto(address + path)
                        expect(page.locator('.avatar-display')).to_have_attribute('data-avatar', 'custom')
                        expect(page.locator('.avatar-image')).to_have_attribute('src', custom_source)
                        assert page.locator('.avatar-image').evaluate('node => node.complete && node.naturalWidth > 0')
                    open_picker(page)
                    page.locator('[data-avatar-choice="f1"]').click()
                    expect(page.locator('.avatar-display')).to_have_attribute('aria-busy', 'false')
                    page.locator('[data-avatar-choice="custom"]').click()
                    expect(page.locator('.avatar-display')).to_have_attribute('aria-busy', 'false')
                    with page.expect_response('**/api/avatar/upload') as rejected:
                        page.locator('[data-avatar-file]').set_input_files({
                            'name': 'invalid.png', 'mimeType': 'image/png', 'buffer': b'not an image'})
                    assert rejected.value.status == 400
                    expect(page.locator('.avatar-feedback')).to_have_class('avatar-feedback is-error')
                    expect(page.locator('.avatar-display')).to_have_attribute('data-avatar', 'custom')
                    assert not errors, errors
                    results.append({'width': width, 'customUpload': True, 'defaultSwitch': True,
                                    'invalidImagePreservedAvatar': True, 'pageErrors': 0})
                    page.close()
                browser.close()
            for kind in ('gm', 'gn'):
                assert (root / 'daily' / f'{day}.{kind}.json').read_text() == document
            assert not (root / 'browser-jobs' / 'jobs.json').exists()
        finally:
            process.terminate()
            process.communicate(timeout=5)
    report = {'modelCalls': 0, 'savedContentUnchanged': True, 'noJavaScript': 'pass', 'checks': results,
              'alignment': alignment_checks}
    (artifacts / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
