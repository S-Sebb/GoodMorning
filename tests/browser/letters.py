"""Letters tab: week names follow a live language switch, also after opening another week; Chinese names fit one line on phones."""

import argparse
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import TEMP_ROOT, returning_viewer, start_server

from goodmorning.records import letters
from goodmorning.records.inbox_store import initialize
from goodmorning.web.briefing_server import BrowserApp

WEEKS = ("2026-11-16", "2026-11-23", "2026-11-30")


def check(url):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url + "/letters")
        heading, dates = (
            page.locator(".weekly-letter h1"),
            page.locator(".letter-range"),
        )
        names = page.locator(".wheel-name")
        expect(heading).to_have_text("First week of December")
        page.locator("#prefs-menu summary").click()
        page.locator("#website-language").select_option("zh-CN")
        expect(page.locator("html")).to_have_attribute("lang", "zh-CN")
        expect(heading).to_have_text("12月第1周")
        expect(dates).to_have_text("11月30日 – 12月6日")
        expect(names).to_have_text(["12月第1周", "11月第4周", "11月第3周"])
        page.keyboard.press("Escape")
        page.locator('.letter-wheel a[href="/letters/2026-11-23"]').click()
        page.wait_for_url("**/letters/2026-11-23")
        expect(heading).to_have_text("11月第4周")
        expect(dates).to_have_text("11月23日 – 29日")
        expect(names).to_have_text(["12月第1周", "11月第4周", "11月第3周"])
        tall = page.evaluate(
            "[...document.querySelectorAll('.wheel-name')].filter(node =>"
            " node.getBoundingClientRect().height > 1.5 * parseFloat(getComputedStyle(node).lineHeight)).length"
        )
        assert tall == 0, f"{tall} Chinese week names wrap on a phone"
        page.locator("#prefs-menu summary").click()
        page.locator("#website-language").select_option("en")
        expect(heading).to_have_text("Fourth week of November")
        expect(dates).to_have_text("Nov 23 – 29")
        expect(names.first).to_have_text("First week of December")
        assert not errors, errors
        browser.close()


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temporary:
        root = Path(temporary)
        (root / "profile.md").write_text(
            "timezone: Asia/Shanghai\nsecretary_language: English\ncity: Shanghai, CN\nnews_country: CN\n"
        )
        (root / "daily").mkdir()
        initialize(root)
        for week in WEEKS:  # Quiet weeks: code writes the opening.
            letters.save(
                root, week, {"signoff": "Until the next letter."}, "en", "2026-12-07"
            )
        app = BrowserApp(root, now=lambda: datetime(2026, 12, 8, 4, tzinfo=UTC))
        returning_viewer(root)
        server = start_server(app)
        try:
            check(f"http://127.0.0.1:{server.server_address[1]}")
        finally:
            server.shutdown()
            server.server_close()
    print("PASS letters")


if __name__ == "__main__":
    main()
