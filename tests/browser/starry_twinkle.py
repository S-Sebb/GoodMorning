"""Check real CSS-background animation, unchanged brightness and reduced motion."""
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


def main():
    artifacts = Path(sys.argv[1]); artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)
    resources = Resources(REPO / 'assets/web', types={
        'starry-sky.svg': 'image/svg+xml', 'color-schemes.css': 'text/css'})
    markup = resources.rewrite('<html data-edition="gn" data-night-scheme="starry">'
        '<head><link rel="stylesheet" href="/color-schemes.css"></head><body></body></html>')
    errors = []
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(reduced_motion='reduce')
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('console', lambda message: errors.append(message.text) if message.type == 'error' else None)

        def serve(route):
            path = urlsplit(route.request.url).path
            resource = resources.paths.get(path)
            assert path == '/' or resource is not None, path
            route.fulfill(body=resource.data if resource else markup,
                content_type=resource.mime if resource else 'text/html',
                headers={'Content-Security-Policy': POLICY})

        page.route('https://starry.test/**', serve)
        for width in (1440, 390, 320):
            page.set_viewport_size({'width': width, 'height': 1000})
            page.emulate_media(reduced_motion='reduce')
            page.goto('https://starry.test/')
            background = page.locator('body')
            expect(background).to_have_css('background-attachment', 'fixed, fixed')
            expect(background).to_have_css('background-position', '50% 0%, 50% 0%')
            expect(background).to_have_css('background-size', 'cover, cover')
            expect(background).to_have_css('background-repeat', 'no-repeat, no-repeat')
            baseline = Image.open(BytesIO(page.screenshot(path=str(artifacts / f'static-{width}.png')))).convert('RGB')
            layout = background.bounding_box()
            page.emulate_media(reduced_motion='no-preference')
            expect(background).to_have_css('background-image',
                f'url("https://starry.test{resources.urls["starry-sky.svg"]}#twinkle"), '
                'radial-gradient(at 65% 12%, rgba(36, 56, 91, 0.4), rgba(0, 0, 0, 0) 65%)')
            frames = []
            for _ in range(6):
                # Sample animation frames rather than assuming a particular start phase.
                page.evaluate('''() => new Promise(resolve => {
                    const start = performance.now();
                    function frame(now) {
                        if (now - start >= 250) resolve();
                        else requestAnimationFrame(frame);
                    }
                    requestAnimationFrame(frame);
                })''')
                frame = Image.open(BytesIO(page.screenshot())).convert('RGB')
                # Animated SVG compositing can round a color channel up by one level.
                brighter = ImageChops.subtract(frame, baseline)
                assert max(high for low, high in brighter.getextrema()) <= 1, 'Stars became brighter or moved.'
                frames.append(frame)
            assert any(ImageChops.difference(frames[0], frame).getbbox() for frame in frames[1:]), 'Stars did not blink.'
            dimming = max(high for frame in frames
                for low, high in ImageChops.subtract(baseline, frame).getextrema())
            assert dimming >= 70, 'Blinking is too subtle.'
            assert background.bounding_box() == layout
            frames[-1].save(artifacts / f'twinkle-{width}.png')
            page.emulate_media(reduced_motion='reduce')
            for _ in range(2):
                still = Image.open(BytesIO(page.screenshot())).convert('RGB')
                assert ImageChops.difference(still, baseline).getbbox() is None, 'Reduced motion changed the static sky.'
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            results.append({'width': width, 'blinks': True, 'neverBrighter': True,
                'layoutUnchanged': True, 'reducedMotionStatic': True, 'dimmingLevels': dimming})
        assert not errors, errors
        browser.close()
    report = {'viewports': results, 'pageErrors': 0}
    (artifacts / 'result.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == '__main__':
    main()
