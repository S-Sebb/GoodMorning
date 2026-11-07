"""Optional real-browser weekly schedule checks, using only a synthetic runtime.

python tests/browser/schedule.py --screenshots /tmp/opencode/schedule-shots
python tests/browser/schedule.py --preview --port 18791
"""

import argparse
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import TEMP_ROOT, returning_viewer, start_server
from test_weekly_schedule import canonical_records, make_runtime

from goodmorning.calendar.calendar_store import CalendarStore
from goodmorning.records.inbox_store import InboxStore
from goodmorning.records.task_store import TaskStore
from goodmorning.web.briefing_server import serve_live


def check(app, url, shots, canonical=False):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1050})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url + "/schedule")
        expect(page.locator(".schedule-day")).to_have_count(7)
        expect(page.locator(".schedule-day.is-today")).to_have_count(1)
        expect(page.locator("#schedule-status")).to_contain_text("Checked at")
        expect(page.locator("#schedule-refresh")).to_be_enabled()
        assert page.locator("#schedule-refresh svg").bounding_box()["width"] == 18
        expect(page.locator(".schedule-info-panel")).to_be_hidden()
        if canonical:
            expect(page.locator(".schedule-event.is-tbc")).to_have_count(1)
            expect(page.locator(".schedule-event.is-tbc")).to_contain_text("TBC")
            # The project is a tag: only its name shows, and screen readers still hear "Project:".
            project = page.locator(".task-project").first
            expect(project).to_have_text("Project: Atlas")
            assert project.locator(".visually-hidden").bounding_box()["width"] <= 1
            expect(page.locator(".task-deadline")).to_contain_text("Due: Fri, Oct 16")
            expect(page.locator(".schedule-task.is-partial")).to_contain_text(
                "First baseline compared."
            )
            expect(page.locator(".schedule-task.is-blocked")).to_contain_text(
                "Awaiting lab approval."
            )
            # A deadline is a marker on its due day, never a workday.
            expect(
                page.get_by_text("Deadline only, not a workday", exact=True)
            ).to_have_count(1)
            # The week shows a short tag; the full explanation is the icon's tooltip and the day view's text.
            deadline_day = page.locator("#day-2026-10-16")
            expect(deadline_day.locator(".task-marker.is-short")).to_have_text(
                "Deadline"
            )
            expect(deadline_day.locator(".task-marker.is-long")).to_be_hidden()
            expect(deadline_day.locator(".task-icon.is-deadline")).to_have_attribute(
                "title", "Deadline · no workday assigned"
            )
            # Notes leave the week grid for the row's tooltip.
            partial = page.locator(".schedule-task.is-partial")
            expect(partial.locator(".task-detail")).to_be_hidden()
            expect(partial).to_have_attribute(
                "title", re.compile("First baseline compared.")
            )
            # Every to-do's icon loads.
            for icon in page.locator(".task-icon").all():
                url = icon.evaluate(
                    "el => getComputedStyle(el).backgroundImage.slice(5, -2)"
                )
                assert page.request.get(url).ok, url
            # Done work steps back: faded, a thin strike-through, no tags or notes.
            done = page.locator(".schedule-grid .schedule-task.is-done").first
            assert done.evaluate("el => getComputedStyle(el).opacity") == "0.55"
            assert (
                done.locator(".task-title").evaluate(
                    "el => getComputedStyle(el).textDecorationLine"
                )
                == "line-through"
            )
            for tag in done.locator("small").all():
                expect(tag).to_be_hidden()
        # Only lists with something in them get a heading; a day with nothing saved says so once.
        for day in page.locator(".schedule-day").all():
            events, tasks = (
                day.locator(".schedule-event").count(),
                day.locator(".schedule-task").count(),
            )
            expect(day.locator(".schedule-calendar h4")).to_have_count(
                1 if events else 0
            )
            expect(day.locator(".schedule-work h4")).to_have_count(1 if tasks else 0)
            expect(day.get_by_text("Nothing saved", exact=True)).to_have_count(
                0 if events or tasks else 1
            )
        # The calendar icon sits beside the heading.
        assert "desk-schedule" in page.locator(".schedule-date").evaluate(
            'el => getComputedStyle(el, "::before").backgroundImage'
        )
        # Routine metadata stays in the details menu.
        visible_text = page.locator("main").inner_text()
        assert "Europe/London" not in visible_text
        assert "completed" not in visible_text and "Checked at" not in visible_text
        expect(
            page.locator(".schedule-guide, .schedule-summary, .schedule-intro")
        ).to_have_count(0)
        page.get_by_label("Schedule details", exact=True).click()
        expect(page.locator(".schedule-info-panel")).to_be_visible()
        expect(page.locator(".schedule-info-panel")).to_contain_text("Europe/London")
        expect(page.locator(".schedule-info-panel")).not_to_contain_text(
            "awaits review"
        )
        expect(page.locator(".schedule-info-panel")).not_to_contain_text(
            "provider sync"
        )
        page.keyboard.press("Escape")
        expect(page.locator(".schedule-info-panel")).to_be_hidden()
        if shots:
            page.locator("summary.schedule-icon").blur()
            page.screenshot(
                path=str(shots / "schedule-calm-desktop.png"), full_page=True
            )
        assert (
            page.locator(".schedule-grid").evaluate(
                'element => getComputedStyle(element).gridTemplateColumns.split(" ").length'
            )
            == 7
        )
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")

        def aligned_work():
            tops = page.locator(".schedule-work").evaluate_all(
                "nodes => nodes.map(node => node.getBoundingClientRect().top)"
            )
            assert len(tops) == 7 and max(tops) - min(tops) < 1, tops
            return tops[0]

        initial_work_top = aligned_work()
        page.locator(".schedule-event summary").first.click()
        expect(page.locator(".schedule-event").first).to_have_attribute("open", "")
        expanded_work_top = aligned_work()
        assert expanded_work_top > initial_work_top, (
            initial_work_top,
            expanded_work_top,
        )
        if canonical:
            inbox = InboxStore(app.runtime, write=True)
            try:
                store = TaskStore(inbox)
                parcel = next(
                    t for t in store.all() if t["title"] == "Pick up a parcel"
                )
                store.mutate(
                    parcel["id"],
                    parcel["revision"],
                    {"status": "done", "confirmed_completion": True},
                    "ses_synthetic",
                    "parcel-done",
                    app.now().isoformat(),
                )
            finally:
                inbox.close()
        else:
            daily = app.runtime / "daily/2026-10-13.md"
            daily.write_text(daily.read_text().replace("[ ] Pick up", "[x] Pick up"))
        page.locator("#schedule-refresh").click()
        expect(page.locator(".schedule-task.is-done")).to_have_count(2)
        expect(page.locator(".schedule-event").first).to_have_attribute("open", "")
        if shots:
            page.screenshot(path=str(shots / "schedule-desktop.png"), full_page=True)
        for offset in range(1, 4):
            page.get_by_role("link", name="Previous week", exact=True).click()
            expect(page).to_have_url(url + f"/schedule?week={-offset}")
        expect(page).to_have_url(url + "/schedule?week=-3")
        expect(
            page.get_by_role("link", name="Previous week", exact=True)
        ).to_have_count(0)
        page.get_by_role("link", name="This week", exact=True).click()
        expect(page).to_have_url(url + "/schedule")
        for offset in range(1, 4):
            page.get_by_role("link", name="Next week", exact=True).click()
            expect(page).to_have_url(url + f"/schedule?week={offset}")
        expect(page).to_have_url(url + "/schedule?week=3")
        expect(page.get_by_role("link", name="Next week", exact=True)).to_have_count(0)
        page.go_back()
        expect(page.locator(".schedule-range")).to_contain_text("2 weeks ahead")
        # The range names both months and reads at body size in the main text colour.
        expect(page.locator(".schedule-range")).to_contain_text("Oct 26–Nov 1")
        expect(page.locator(".schedule-range")).to_have_css("font-size", "16px")
        assert page.locator(".schedule-range").evaluate(
            'node => getComputedStyle(node).color === getComputedStyle(node.closest(".schedule-date")).color'
        )
        page.get_by_role("link", name="This week", exact=True).click()
        page.locator("#prefs-menu summary").click()
        page.locator("#website-language").select_option("zh-CN")
        expect(page.locator("h1")).to_have_text("2026年10月")
        expect(page.locator(".schedule-range")).to_have_text("10月12日–18日")
        expect(page.locator(".schedule-event").first).to_contain_text("Team check-in")
        page.locator("#prefs-menu summary").click()
        page.locator("#schedule-refresh").click()
        expect(page.locator("#schedule-status")).to_contain_text("已检查")
        if canonical:
            expect(page.locator(".schedule-event.is-tbc")).to_contain_text("时间待确认")
            expect(page.locator(".task-progress").first).to_contain_text("部分完成")
        page.set_viewport_size({"width": 820, "height": 1180})
        expect(page.locator(".schedule-grid")).to_have_css(
            "grid-template-columns", re.compile(r"^[\d.]+px [\d.]+px$")
        )
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.locator(".schedule-grid")).to_have_css(
            "grid-template-columns", re.compile(r"^[\d.]+px$")
        )
        expect(page.locator(".schedule-day-strip")).to_be_visible()
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
        # Phone week controls sit over the sky decoration, so they need their own backing.
        for control in page.locator(".week-arrow, .current-week").all():
            assert (
                control.evaluate("node => getComputedStyle(node).backgroundColor")
                != "rgba(0, 0, 0, 0)"
            )
        page.get_by_label("日程详情", exact=True).click()
        expect(page.locator(".schedule-info-panel")).to_be_visible()
        assert page.locator(".schedule-info-panel").bounding_box()["x"] >= 0
        page.keyboard.press("Escape")
        page.locator("summary.schedule-icon").blur()
        if shots:
            page.screenshot(path=str(shots / "schedule-mobile-zh.png"), full_page=True)
        page.locator(".schedule-day-strip a").nth(1).click()
        expect(page.locator(".schedule-day.is-today")).to_be_in_viewport()
        app.now = lambda: datetime(2026, 10, 13, 21, tzinfo=UTC)
        page.locator("#schedule-refresh").click()
        expect(page.locator("html")).to_have_attribute("data-edition", "gn")
        if shots:
            page.evaluate(
                "new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
            )
            page.evaluate(
                "Promise.all(document.getAnimations().map(animation => animation.finished.catch(() => {})))"
            )
            page.screenshot(
                path=str(shots / "schedule-mobile-night.png"), full_page=True
            )
        app.now = lambda: datetime(
            2026, 10, 18, 23, 30, tzinfo=UTC
        )  # Monday 00:30 is still Sunday's night.
        page.locator("#schedule-refresh").click()
        expect(page.locator(".schedule-day.is-today")).to_have_attribute(
            "id", "day-2026-10-18"
        )
        app.now = lambda: datetime(2026, 10, 19, 3, tzinfo=UTC)
        page.locator("#schedule-refresh").click()
        expect(page.locator(".schedule-day.is-today")).to_have_attribute(
            "id", "day-2026-10-19"
        )
        # A refresh failure retains the existing readable week.
        page.route("**/api/schedule?*", lambda route: route.abort())
        page.locator("#schedule-refresh").click()
        expect(page.locator("#schedule-error")).to_be_visible()
        expect(page.locator(".schedule-day")).to_have_count(7)
        page.unroute("**/api/schedule?*")
        # Real timer behavior: visible records change after the minute check.
        page.clock.install()
        app.now = lambda: datetime(2026, 10, 13, 12, tzinfo=UTC)
        page.locator("#schedule-refresh").click()
        expect(page.locator("#schedule-error")).to_be_empty()
        store = CalendarStore(str(app.runtime / "calendar.sqlite"))
        store.add(
            {
                "subject": "Saved after opening",
                "start": "2026-10-13T15:00:00+01:00",
                "end": "2026-10-13T16:00:00+01:00",
            }
        )
        store.close()
        page.locator(".schedule-event summary").first.focus()
        page.clock.fast_forward(60001)
        expect(
            page.locator(".schedule-event").filter(has_text="Saved after opening")
        ).to_have_count(1)
        expect(page.locator(".schedule-event summary").first).to_be_focused()
        page.get_by_label("日程详情", exact=True).click()
        page.clock.fast_forward(60001)
        expect(page.locator(".schedule-info-panel")).to_be_visible()
        expect(page.locator("#schedule-status")).to_contain_text("已检查")
        page.keyboard.press("Escape")
        # Simulated visibility events exercise the same hidden/return guards.
        checks = []
        page.on(
            "request",
            lambda request: (
                checks.append(request.url) if "/api/schedule?" in request.url else None
            ),
        )
        page.evaluate(
            'Object.defineProperty(document, "hidden", {configurable: true, get: () => true}); document.dispatchEvent(new Event("visibilitychange"))'
        )
        page.clock.fast_forward(120001)
        assert not checks, checks
        page.evaluate(
            'Object.defineProperty(document, "hidden", {configurable: true, get: () => false}); document.dispatchEvent(new Event("visibilitychange"))'
        )
        expect(page.locator("#schedule-refresh")).to_be_enabled()
        assert len(checks) == 1, checks
        page.set_viewport_size({"width": 320, "height": 700})
        expect(page.locator(".schedule-grid")).to_have_css(
            "grid-template-columns", re.compile(r"^[\d.]+px$")
        )
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
        # A quieter presentation must not hide actual source failures.
        calendar = app.runtime / "calendar.sqlite"
        original = calendar.read_bytes()
        calendar.write_bytes(b"not a SQLite calendar")
        page.locator("#schedule-refresh").click()
        expect(page.locator(".schedule-warning")).to_be_visible()
        expect(page.locator(".schedule-task")).not_to_have_count(0)
        calendar.write_bytes(original)
        page.locator("#schedule-refresh").click()
        expect(page.locator(".schedule-warning")).to_have_count(0)
        assert not errors, errors
        browser.close()
        # Server-rendered navigation remains useful without JavaScript.
        browser = playwright.chromium.launch()
        page = browser.new_page(java_script_enabled=False)
        page.goto(url + "/schedule")
        expect(page.locator(".schedule-day")).to_have_count(7)
        page.get_by_label("日程详情", exact=True).click()
        expect(page.locator(".schedule-info-panel")).to_be_visible()
        expect(page.locator("#schedule-status")).to_contain_text("已检查")
        page.get_by_label("日程详情", exact=True).click()
        page.get_by_role("link", name="下一周", exact=True).click()
        expect(page).to_have_url(url + "/schedule?week=1")
        browser.close()


def check_ticks(app, url, shots):
    """Tap a to-do done, undo, tap again later, and keep the old mark on a conflict."""
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1440, "height": 1050},
            **(
                {
                    "record_video_dir": str(shots),
                    "record_video_size": {"width": 1440, "height": 1050},
                }
                if shots
                else {}
            ),
        )
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.clock.install()
        page.goto(url + "/schedule")
        parcel = page.get_by_role(
            "button", name="Mark “Pick up a parcel” done", exact=True
        )
        expect(parcel).to_be_enabled()
        # Future days and deadline markers have no tap target.
        expect(
            page.locator(
                "#day-2026-10-15 button.task-tick, #day-2026-10-16 button.task-tick"
            )
        ).to_have_count(0)
        parcel.click()
        notice = page.locator("#schedule-notice")
        expect(notice).to_contain_text("Marked “Pick up a parcel” done.")
        expect(
            page.get_by_role(
                "button", name="Mark “Pick up a parcel” not done", exact=True
            )
        ).to_be_visible()
        if shots:
            page.screenshot(path=str(shots / "tick-1-done-with-undo.png"))
        notice.get_by_role("button", name="Undo", exact=True).click()
        expect(notice).to_contain_text("Marked “Pick up a parcel” not done.")
        expect(
            page.get_by_role("button", name="Mark “Pick up a parcel” done", exact=True)
        ).to_be_visible()
        if shots:
            page.screenshot(path=str(shots / "tick-2-undone.png"))
        page.clock.fast_forward(6500)
        expect(notice).to_be_empty()
        # Partial work ticked done, then ticked back after the notice has gone: Partial and its note return.
        methods = page.locator(".schedule-task").filter(has_text="Draft the methods")
        expect(methods).to_have_class(re.compile("is-partial"))
        methods.get_by_role("button").click()
        expect(methods).to_have_class(re.compile("is-done"))
        if shots:
            page.screenshot(path=str(shots / "tick-3-partial-ticked-done.png"))
        page.clock.fast_forward(6500)
        expect(notice).to_be_empty()
        methods.get_by_role(
            "button", name="Mark “Draft the methods” not done", exact=True
        ).click()
        expect(methods).to_have_class(re.compile("is-partial"))
        expect(methods).to_contain_text("First baseline compared.")
        if shots:
            page.screenshot(path=str(shots / "tick-4-ticked-back-to-partial.png"))
        # The day view ticks the same way.
        page.get_by_role("link", name="Day", exact=True).click()
        expect(page.locator(".schedule-focus")).to_have_count(1)
        page.get_by_role(
            "button", name="Mark “Pick up a parcel” done", exact=True
        ).click()
        expect(notice).to_contain_text("Marked “Pick up a parcel” done.")
        if shots:
            page.screenshot(path=str(shots / "tick-day-view.png"))
        notice.get_by_role("button", name="Undo", exact=True).click()
        expect(
            page.get_by_role("button", name="Mark “Pick up a parcel” done", exact=True)
        ).to_be_visible()
        page.get_by_role("link", name="Week", exact=True).click()
        expect(page.locator(".schedule-day")).to_have_count(7)
        # Saved elsewhere since the page loaded: the save is refused and the row keeps its mark.
        inbox = InboxStore(app.runtime, write=True)
        try:
            store = TaskStore(inbox)
            blocked = next(
                t for t in store.all() if t["title"] == "Request the dataset"
            )
            store.mutate(
                blocked["id"],
                blocked["revision"],
                {"detail": "Ask the lab manager."},
                "ses_synthetic",
                "elsewhere",
                app.now().isoformat(),
            )
        finally:
            inbox.close()
        dataset = page.locator(".schedule-task").filter(has_text="Request the dataset")
        dataset.get_by_role("button").click()
        expect(page.locator("#schedule-error")).to_have_text(
            "Couldn’t save — this task changed since the page loaded. Refresh and try again."
        )
        expect(page.locator("#schedule-error")).to_be_in_viewport()
        expect(dataset).to_have_class(re.compile("is-blocked"))
        expect(dataset.get_by_role("button")).to_have_text("○")
        expect(notice).to_be_empty()
        if shots:
            page.screenshot(path=str(shots / "tick-5-conflict.png"))
        page.route("**/api/schedule/tick", lambda route: route.abort())
        page.locator("#schedule-refresh").click()
        expect(page.locator("#schedule-error")).to_be_empty()
        parcel.click()
        expect(page.locator("#schedule-error")).to_have_text(
            "Couldn’t save. Check your connection and try again."
        )
        expect(parcel).to_have_text("○")
        page.unroute("**/api/schedule/tick")
        page.locator("#prefs-menu summary").click()
        page.locator("#website-language").select_option("zh-CN")
        expect(
            page.get_by_role("button", name="标记“Pick up a parcel”为完成", exact=True)
        ).to_be_visible()
        assert not errors, errors
        context.close()
        browser.close()
        # Without JavaScript the marks stay visible but cannot be used.
        browser = playwright.chromium.launch()
        page = browser.new_page(java_script_enabled=False)
        page.goto(url + "/schedule")
        expect(page.locator("button.task-tick").first).to_be_disabled()
        expect(page.locator("button.task-tick:enabled")).to_have_count(0)
        browser.close()


def check_day(url):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1050})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url + "/schedule")
        expect(page.locator(".schedule-day")).to_have_count(7)
        page.get_by_role("link", name="Day", exact=True).click()
        expect(page).to_have_url(url + "/schedule?view=day")
        expect(page.locator("h1")).to_have_text("Tuesday, October 13")
        expect(page.locator(".schedule-day")).to_have_count(0)
        expect(page.locator(".focus-panel")).to_have_count(2)
        expect(page.get_by_role("link", name="Day", exact=True)).to_have_attribute(
            "aria-current", "true"
        )
        expect(page.locator(".focus-event.is-past")).to_contain_text("Ended")
        # Side-by-side panels share one top and bottom edge, even when one is shorter.
        edges = page.locator(".focus-panel").evaluate_all(
            "nodes => nodes.map(node => [node.getBoundingClientRect().top, node.getBoundingClientRect().bottom])"
        )
        assert (
            abs(edges[0][0] - edges[1][0]) < 1 and abs(edges[0][1] - edges[1][1]) < 1
        ), edges
        page.get_by_role("link", name="Next day", exact=True).click()
        expect(page).to_have_url(url + "/schedule?view=day&day=1")
        expect(page.locator(".schedule-range")).to_contain_text("Tomorrow")
        expect(page.locator(".focus-event")).to_contain_text("Quiet working block")
        page.go_back()
        expect(page.locator(".schedule-range")).to_contain_text("Today")
        # The last view used in this browser reopens from the plain Schedule link.
        page.goto(url + "/schedule")
        expect(page).to_have_url(url + "/schedule?view=day")
        page.get_by_role("link", name="Week", exact=True).click()
        expect(page).to_have_url(url + "/schedule?week=0")
        expect(page.locator(".schedule-day")).to_have_count(7)
        page.goto(url + "/schedule")
        expect(page).to_have_url(url + "/schedule")
        expect(page.locator(".schedule-day")).to_have_count(7)
        # Phones remember their own view without changing the wider screen's.
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(url + "/schedule")
        expect(page).to_have_url(url + "/schedule")
        page.get_by_role("link", name="Day", exact=True).click()
        expect(page).to_have_url(url + "/schedule?view=day")
        page.goto(url + "/schedule")
        expect(page).to_have_url(url + "/schedule?view=day")
        page.set_viewport_size({"width": 1440, "height": 1050})
        page.goto(url + "/schedule")
        expect(page).to_have_url(url + "/schedule")
        expect(page.locator(".schedule-day")).to_have_count(7)
        page.goto(url + "/schedule?view=day")
        page.set_viewport_size({"width": 390, "height": 844})
        expect(page.locator(".schedule-focus")).to_have_css(
            "grid-template-columns", re.compile(r"^[\d.]+px$")
        )
        assert page.locator(".schedule-mode").bounding_box()["width"] > 300
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
        assert not errors, errors
        browser.close()


def check_top_bar(url):
    """Every page puts the top bar exactly where Morning does, so nothing moves when switching pages."""
    from playwright.sync_api import sync_playwright

    boxes = """() => [...document.querySelectorAll('.toolbar-row, .toolbar-row > *, .masthead, .wordmark, .edition-switch, .edition-link')]
        .map(node => { const box = node.getBoundingClientRect(); return [node.tagName, node.id, box.x, box.y, box.width, box.height]; })"""
    # 701-1000 px is where the tablet header rules switch over.
    widths = [1440, 900, 390, 320, *range(701, 1001, 60), 1000]
    failures = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        for width in widths:
            page.set_viewport_size({"width": width, "height": 900})
            measured = {}
            for path in ("/gm", "/gn", "/schedule", "/letters", "/chat", "/about-me"):
                # The What's new button arrives after load and shifts the settings button.
                page.goto(url + path, wait_until="networkidle")
                measured[path] = page.evaluate(boxes)
            failures += [
                (
                    width,
                    path,
                    [
                        pair
                        for pair in zip(measured["/gm"], boxes_)
                        if pair[0] != pair[1]
                    ][:2],
                )
                for path, boxes_ in measured.items()
                if boxes_ != measured["/gm"]
            ]
        browser.close()
    assert not failures, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshots", type=Path)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--port", type=int, default=18791)
    parser.add_argument(
        "--canonical",
        action="store_true",
        help="Check task-store v2, occurrence reports and TBC drafts",
    )
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temporary:
        app = make_runtime(Path(temporary))
        if args.canonical:
            canonical_records(app.runtime)
        returning_viewer(app.runtime)
        if args.preview:
            serve_live(app, args.port)
        else:
            if args.canonical:
                with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as ticks:
                    tick_app = make_runtime(Path(ticks))
                    canonical_records(tick_app.runtime)
                    returning_viewer(tick_app.runtime)
                    server = start_server(tick_app)
                    try:
                        check_ticks(
                            tick_app,
                            f"http://127.0.0.1:{server.server_port}",
                            args.screenshots,
                        )
                    finally:
                        server.shutdown()
            server = start_server(app)
            try:
                check_top_bar(f"http://127.0.0.1:{server.server_port}")
                check_day(f"http://127.0.0.1:{server.server_port}")
                check(
                    app,
                    f"http://127.0.0.1:{server.server_port}",
                    args.screenshots,
                    args.canonical,
                )
                print(
                    "Schedule browser checks passed (top bar, day view, desktop, mobile, Chinese, refresh, bounds, no JavaScript"
                    + (", ticking" if args.canonical else "")
                    + ")."
                )
            finally:
                server.shutdown()


if __name__ == "__main__":
    main()
