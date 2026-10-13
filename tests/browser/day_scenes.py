"""Rendered scene contrast, actual background motion, and static reduced motion."""
from functools import lru_cache
from io import BytesIO
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright, expect

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'src'))
from goodmorning.security.briefing_gateway import POLICY
from goodmorning.web.briefing_resources import Resources


@lru_cache(maxsize=65536)
def luminance(rgb):
    values = [value / 255 for value in rgb]
    return sum(weight * (value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4)
               for weight, value in zip((.2126, .7152, .0722), values))


def contrast(first, second):
    low, high = sorted((luminance(first), luminance(second)))
    return (high + .05) / (low + .05)


def sample_frame(page):
    # Deliberately sample real background animation, which DOM animation APIs cannot seek.
    page.evaluate('''() => new Promise(resolve => {
        const start = performance.now();
        function frame(now) {
            if (now - start >= 750) resolve();
            else requestAnimationFrame(frame);
        }
        requestAnimationFrame(frame);
    })''')
    return Image.open(BytesIO(page.screenshot())).convert('RGB')


def main():
    artifacts = Path(sys.argv[1]); artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    schemes = ('morning-sky', 'first-light')
    resources = Resources(REPO / 'assets/web')
    errors, results = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(reduced_motion='reduce')
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)

        def serve(route):
            path = urlsplit(route.request.url).path
            scheme = path.strip('/')
            resource = resources.paths.get(path)
            assert scheme in schemes or resource is not None, path
            markup = resources.rewrite(f'<html data-edition="gm" data-day-scheme="{scheme}">'
                '<head><link rel="stylesheet" href="/briefing.css"><link rel="stylesheet" href="/color-schemes.css"></head><body></body></html>')
            route.fulfill(body=resource.data if resource else markup,
                content_type=resource.mime if resource else 'text/html',
                headers={'Content-Security-Policy': POLICY})

        page.route('https://day.test/**', serve)
        for scheme in schemes:
            for width in (1920, 1440, 390, 320):
                page.set_viewport_size({'width': width, 'height': 1000})
                page.emulate_media(reduced_motion='reduce')
                page.goto('https://day.test/' + scheme)
                expect(page.locator('body')).to_have_css('background-repeat',
                    'no-repeat, no-repeat, repeat-y, repeat-y' if scheme == 'morning-sky' else 'no-repeat, repeat-y')
                expect(page.locator('body')).to_have_css('background-attachment',
                    'scroll, scroll, scroll, scroll' if scheme == 'morning-sky' else 'scroll, scroll')
                static = Image.open(BytesIO(page.screenshot(path=str(artifacts / f'{scheme}-{width}.png')))).convert('RGB')
                colors = static.getcolors(static.width * static.height)
                tokens = page.evaluate('''() => {
                    const style = getComputedStyle(document.documentElement);
                    return Object.fromEntries(['ink', 'muted', 'accent', 'surface', 'wash', 'your-bubble'].map(
                        key => [key, style.getPropertyValue('--' + key).trim()]));
                }''')
                rgb = {key: tuple(int(value[index:index+2], 16) for index in (1, 3, 5))
                       for key, value in tokens.items()}
                ratios = {key: min(contrast(rgb[key], pixel) for _, pixel in colors)
                          for key in ('ink', 'muted', 'accent')}
                for key, ratio in ratios.items():
                    assert ratio >= 4.5, (scheme, width, key, ratio)
                    for paper in ('surface', 'wash', 'your-bubble'):
                        assert contrast(rgb[key], rgb[paper]) >= 4.5, (scheme, key, paper)
                assert ImageChops.difference(static, sample_frame(page)).getbbox() is None
                layout = page.locator('body').bounding_box()
                page.emulate_media(reduced_motion='no-preference')
                frames = [sample_frame(page) for _ in range(3)]
                moving = any(ImageChops.difference(frames[0], frame).getbbox() for frame in frames[1:])
                assert moving == (scheme != 'first-light'), (scheme, width, moving)
                assert page.locator('body').bounding_box() == layout
                page.emulate_media(reduced_motion='reduce')
                assert ImageChops.difference(static, sample_frame(page)).getbbox() is None
                page.evaluate('document.body.style.minHeight = "12000px"')
                for depth in (2000, 4200, 8000, 11000):
                    page.evaluate('y => window.scrollTo(0, y)', depth)
                    lower = Image.open(BytesIO(page.screenshot(
                        path=str(artifacts / f'{scheme}-{width}-depth-{depth}.png')))).convert('RGB')
                    lower_colors = lower.getcolors(lower.width * lower.height)
                    assert len(lower_colors) > 20, (scheme, width, depth, 'Solid fallback background')
                    for key in ('ink', 'muted', 'accent'):
                        ratio = min(contrast(rgb[key], pixel) for _, pixel in lower_colors)
                        assert ratio >= 4.5, (scheme, width, depth, key, ratio)
                    assert ImageChops.difference(lower, sample_frame(page)).getbbox() is None
                scale = max(width, 1600) / 1600
                units = (1000, 2000, 3000, 5000, 9000) if scheme == 'morning-sky' else (1800, 3600, 5400, 9000)
                seams = [round(seam * scale) for seam in units]
                for seam in seams:
                    page.evaluate('y => window.scrollTo(0, y - 50)', seam)
                    image = Image.open(BytesIO(page.screenshot())).convert('RGB')
                    delta = ImageChops.difference(image.crop((0, 49, width, 50)), image.crop((0, 50, width, 51)))
                    assert max(high for low, high in delta.getextrema()) <= 32, (scheme, width, seam, 'Visible seam')
                page.evaluate('document.body.style.minHeight = ""; window.scrollTo(0, 0)')
                assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                results.append({'scheme': scheme, 'width': width,
                                'minimumSceneContrast': {key: round(ratio, 2) for key, ratio in ratios.items()},
                                'motion': moving, 'reducedMotionStatic': True,
                                'continuedAt': [2000, 4200, 8000, 11000], 'seamsChecked': list(seams)})
        assert not errors, errors
        browser.close()
    report = {'scenes': results, 'pageErrors': 0}
    (artifacts / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
