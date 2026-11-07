"""Weather chart captions stay apart at tablet and desktop widths, and headlines fit their tiles, in both languages.

python tests/browser/weather_chart.py
Uses the README demo's fictional morning; no network or model calls.
"""

import json
import sys
import tempfile
from itertools import pairwise
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "tests" / "browser")]
from readme_demo import DAY, fixture
from support import TEMP_ROOT, start_server

from goodmorning.briefings.briefing_document import encode, parse, source_path

WIDTHS = (768, 1024, 1280, 1440)
# Each headline's lines, its size against the tile's full size, its height and its size.
HEADLINES = """() => [...document.querySelectorAll('.weather-main')].map(main => {
    const style = getComputedStyle(main), full = parseFloat(getComputedStyle(main.parentElement).fontSize);
    return [main.textContent, Math.round(main.offsetHeight / parseFloat(style.lineHeight)),
            parseFloat(style.fontSize) / full, main.offsetHeight, parseFloat(style.fontSize)];
})"""
# Each caption's text extent, so text spilling past its equal-width cell counts as overlap.
CAPTIONS = """() => [...document.querySelectorAll('.wx-periods')].map(row => [...row.children].map(cell => {
    const range = document.createRange(); range.selectNodeContents(cell);
    const box = range.getBoundingClientRect(); return [box.left, box.right, cell.textContent];
}))"""


def main():
    failures = []
    with tempfile.TemporaryDirectory(
        dir=TEMP_ROOT, prefix="gm-weather-chart-"
    ) as folder:
        runtime = Path(folder)
        server = start_server(fixture(runtime))
        url = f"http://127.0.0.1:{server.server_port}/gm"
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page()
                for language in ("en", "zh-CN"):
                    (runtime / "website-language.json").write_text(
                        json.dumps({"language": language})
                    )
                    for width in WIDTHS:
                        page.set_viewport_size({"width": width, "height": 1000})
                        page.goto(url)
                        page.evaluate("document.fonts.ready")
                        rows = page.evaluate(CAPTIONS)
                        assert len(rows) == 3, rows
                        for row in rows:
                            gaps = [right[0] - left[1] for left, right in pairwise(row)]
                            if min(gaps) < 4:
                                failures.append(
                                    f"{language} {width}px: {[cell[2] for cell in row]} gaps {gaps}"
                                )
                # Air quality all day "Unhealthy for sensitive groups": the longest headline in both languages.
                path = source_path(runtime, DAY, "gm")
                document = parse(path.read_text())
                for hour in document["sections"][0][1][0][2]["hours"]:
                    hour[2] = 120
                path.write_text(encode(document))
                (runtime / "website-language.json").write_text(
                    json.dumps({"language": "en"})
                )
                for width in (390, *WIDTHS):
                    page.set_viewport_size({"width": width, "height": 1000})
                    page.goto(url)
                    page.evaluate("document.fonts.ready")
                    checks = [("en", page.evaluate(HEADLINES))]
                    # Switching language in place changes the words, so the fit must follow them.
                    page.evaluate("applyWebsiteLanguage('zh-CN')")
                    checks.append(("zh-CN", page.evaluate(HEADLINES)))
                    for language, tiles in checks:
                        temperature, *_, air = tiles
                        # The short temperature keeps its full size; the long headline takes at most two lines
                        # (one in Chinese, above the 26px floor a stale English measurement would give) and, side by
                        # side, stays about as tall as the temperature's one line.
                        if (
                            temperature[2] != 1
                            or air[1] > (1 if language == "zh-CN" else 2)
                            or language == "zh-CN"
                            and air[4] <= 26
                            or width >= 1280
                            and air[3] > temperature[3] * 1.2
                        ):
                            failures.append(f"{language} {width}px headlines: {tiles}")
                browser.close()
        finally:
            server.shutdown()
    for failure in failures:
        print("FAIL", failure)
    print("PASS" if not failures else f"FAIL {len(failures)} rows")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
