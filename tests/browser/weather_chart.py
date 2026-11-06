"""Weather chart captions stay apart at tablet and desktop widths, in both languages.

python tests/browser/weather_chart.py
Uses the README demo's fictional morning; no network or model calls.
"""
import json
from pathlib import Path
import sys
import tempfile

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT / 'tests' / 'browser')]
from readme_demo import fixture
from support import TEMP_ROOT, start_server

WIDTHS = (768, 1024, 1280, 1440)
# Each caption's text extent, so text spilling past its equal-width cell counts as overlap.
CAPTIONS = '''() => [...document.querySelectorAll('.wx-periods')].map(row => [...row.children].map(cell => {
    const range = document.createRange(); range.selectNodeContents(cell);
    const box = range.getBoundingClientRect(); return [box.left, box.right, cell.textContent];
}))'''


def main():
    failures = []
    with tempfile.TemporaryDirectory(dir=TEMP_ROOT, prefix='gm-weather-chart-') as folder:
        runtime = Path(folder)
        server = start_server(fixture(runtime))
        url = f'http://127.0.0.1:{server.server_port}/gm'
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page()
                for language in ('en', 'zh-CN'):
                    (runtime / 'website-language.json').write_text(json.dumps({'language': language}))
                    for width in WIDTHS:
                        page.set_viewport_size({'width': width, 'height': 1000})
                        page.goto(url)
                        page.evaluate('document.fonts.ready')
                        rows = page.evaluate(CAPTIONS)
                        assert len(rows) == 3, rows
                        for row in rows:
                            gaps = [right[0] - left[1] for left, right in zip(row, row[1:])]
                            if min(gaps) < 4:
                                failures.append(f'{language} {width}px: {[cell[2] for cell in row]} gaps {gaps}')
                browser.close()
        finally:
            server.shutdown()
    for failure in failures:
        print('FAIL', failure)
    print('PASS' if not failures else f'FAIL {len(failures)} rows')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
