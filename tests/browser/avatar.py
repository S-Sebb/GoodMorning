"""Shared briefing avatars on isolated synthetic records; no model calls."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.sync_api import expect, sync_playwright

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'src'))
from goodmorning.briefings.briefing_day import briefing_day
from goodmorning.briefings.briefing_document import encode


def check_avatar(page, selected, label):
    figure = page.locator('.briefing-avatar')
    expect(figure).to_have_attribute('data-avatar', selected)
    expect(figure).to_be_visible()
    expect(figure.get_by_role('link')).to_have_attribute('href', '/chat')
    expect(figure).to_contain_text(label)
    image = figure.locator('img')
    assert image.evaluate('node => node.complete && node.naturalWidth > 0')
    assert image.get_attribute('src').startswith('/assets/')
    assert page.locator('.celestial-art').count() == 1
    kind = page.locator('html').get_attribute('data-edition')
    assert page.locator('#sun-light' if kind == 'gm' else '#moon-light').count() == 1
    assert image.bounding_box()['width'] == 64
    if page.viewport_size['width'] > 700:
        expect(page.locator('.orbit')).to_be_visible()
    assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')


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
                            (root / 'daily' / f'{day}.{kind}.json').write_text(document)
                    for language, label in (('en', 'Your secretary'), ('zh-CN', '你的秘书')):
                        page.goto(address + '/chat')
                        page.locator('#website-language').select_option(language)
                        expect(page.locator('html')).to_have_attribute('lang', language)
                        for selected in ('f1', 'f2', 'm1', 'm2'):
                            page.goto(address + '/chat')
                            while page.locator('.desk-figure').get_attribute('data-avatar') != selected:
                                current = page.locator('.desk-figure').get_attribute('data-avatar')
                                next_avatar = ('f1', 'f2', 'm1', 'm2')[(('f1', 'f2', 'm1', 'm2').index(current) + 1) % 4]
                                with page.expect_response('**/api/avatar'):
                                    page.locator('[data-avatar-next]').click()
                                expect(page.locator('.desk-figure')).to_have_attribute('data-avatar', next_avatar)
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
                check_avatar(page, 'm2', '你的秘书')
                page.locator('.briefing-avatar a').click()
                expect(page).to_have_url(address + '/chat')
                page.close()
                browser.close()
            for kind in ('gm', 'gn'):
                assert (root / 'daily' / f'{day}.{kind}.json').read_text() == document
            assert not (root / 'browser-jobs' / 'jobs.json').exists()
        finally:
            process.terminate()
            process.communicate(timeout=5)
    report = {'modelCalls': 0, 'savedContentUnchanged': True, 'noJavaScript': 'pass', 'checks': results}
    (artifacts / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
