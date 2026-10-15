"""Optional secretary-calls simulation with a fake user. Synthetic records only.

python tests/browser/calls.py --screenshots /tmp/opencode/calls-shots
python tests/browser/calls.py --preview --port 18793

Exercises: manual CLI scan (read-only), website scan candidates, approved
create from the page, resolve with revision checks, ask-in-chat through the
normal chat route, and day/night English/Chinese panel screenshots.
Creates no real sessions and makes no model calls.
"""
import argparse
import json
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from support import TEMP_ROOT, returning_viewer
from support import start_server
from test_weekly_schedule import make_runtime

NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)


def http(server, method, path, body=None, csrf=None):
    origin = f"http://127.0.0.1:{server.server_port}"
    url = origin + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json", "Origin": origin} if body is not None else {}
    if body is not None and csrf:
        headers["X-Briefing-CSRF"] = csrf
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"{}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screenshots", type=Path)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--port", type=int, default=18793)
    args = parser.parse_args()
    if args.screenshots:
        args.screenshots.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=TEMP_ROOT) as temporary:
        from goodmorning.records.inbox_store import InboxStore, initialize
        from goodmorning.records.task_store import TaskStore
        from goodmorning.web.briefing_server import serve_live
        root = Path(temporary)
        app = make_runtime(root)
        initialize(root)
        inbox = InboxStore(root, write=True)
        try:
            store = TaskStore(inbox)
            inbox.mutate("add", {"kind": "todo", "raw": "do stuff",
                                 "task": {"title": "Currently do vague things etc."}},
                         "ses_fake", "fake-filler", NOW.isoformat())
            inbox.mutate("add", {"kind": "todo", "raw": "11月初提醒这件事",
                                 "task": {"title": "11月初提醒这件事"}}, "ses_fake", "fake-amb", NOW.isoformat())
            inbox.mutate("add", {"kind": "event_proposal", "raw": "Dentist?",
                                 "draft": {"title": "Dentist", "date": "2026-10-15",
                                           "timezone": "Europe/London", "confirmed_day": True}},
                         "ses_fake", "fake-tbc", NOW.isoformat())
        finally:
            inbox.close()
        returning_viewer(app.runtime)
        if args.preview:
            serve_live(app, args.port)
            return
        server = start_server(app)
        try:
            status, listed = http(server, "GET", "/api/calls")
            assert status == 200 and listed == {"calls": [], "total": 0, "open": 0}, (status, listed)
            status, report = http(server, "GET", "/api/calls/scan")
            assert status == 200, (status, report)
            kinds = {(c["kind"], c["target_type"]) for c in report["candidates"]}
            assert ("ambiguous_schedule", "task") in kinds, kinds
            assert ("tbc_time", "draft") in kinds, kinds
            assert ("calendar_review", "event") in kinds, kinds
            assert ("task_wording", "task") in kinds, kinds
            print(f"scan candidates: {report['total']} {sorted(kinds)}")
            first = report["candidates"][0]
            status, created = http(server, "POST", "/api/calls", {"item": first}, app.csrf)
            assert status == 201 and created["saved"], (status, created)
            status, duplicate = http(server, "POST", "/api/calls", {"item": first}, app.csrf)
            assert duplicate.get("id") == created["id"] and duplicate.get("replayed") is True, (status, duplicate)
            other = dict(first, title="A different proposed title")
            status, refused = http(server, "POST", "/api/calls", {"item": other}, app.csrf)
            assert status == 400, (status, refused)
            status, listed = http(server, "GET", "/api/calls")
            assert listed["open"] == 1, listed
            call_id = created["id"]
            status, resolved = http(server, "POST", f"/api/calls/{call_id}/resolve",
                                    {"note": "fixed in chat"}, app.csrf)
            assert status == 200 and resolved["status"] == "resolved", (status, resolved)
            status, listed = http(server, "GET", "/api/calls")
            assert listed["open"] == 0, listed
            print("HTTP flow passed: scan, create, duplicate-refused, resolve.")
            if args.screenshots:
                from playwright.sync_api import sync_playwright
                url = f"http://127.0.0.1:{server.server_port}"
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    page = browser.new_page(viewport={"width": 1440, "height": 1000})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    # Chat edition follows the account clock; pin daytime for day shots.
                    page.clock.install(time=datetime(2026, 10, 14, 12, tzinfo=timezone.utc))
                    page.goto(url + "/chat")
                    page.locator("#secretary-calls").scroll_into_view_if_needed()
                    page.wait_for_timeout(1200)
                    assert page.locator("#calls-review").count() == 1
                    # Approve a fresh candidate through the page: the resolved one
                    # would replay its old receipt instead of opening anew.
                    page.locator("#calls-review").click()
                    page.locator(".call-card", has_not_text=first["title"]).first.get_by_role("button").click()
                    page.locator(".call-card[data-status=open]").first.wait_for()
                    assert page.locator(".call-card[data-status=open]").count() == 1
                    assert page.locator(".call-card").count() >= 1
                    assert page.locator(".call-actions button").count() >= 3
                    assert page.get_attribute("html", "data-edition") == "gm"
                    page.screenshot(path=str(args.screenshots / "calls-day-en.png"))
                    page.locator("#prefs-menu summary").click()
                    page.locator("#website-language").select_option("zh-CN")
                    page.wait_for_timeout(800)
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(300)
                    page.screenshot(path=str(args.screenshots / "calls-day-zh.png"))
                    page.locator("#prefs-menu summary").click()
                    page.clock.install(time=datetime(2026, 10, 14, 22, tzinfo=timezone.utc))
                    page.reload()
                    page.locator("#secretary-calls").scroll_into_view_if_needed()
                    page.wait_for_timeout(1200)
                    assert page.get_attribute("html", "data-edition") == "gn"
                    page.screenshot(path=str(args.screenshots / "calls-night-zh.png"))
                    # Asking starts a normal secretary chat; capture it instead of running a model.
                    asked = []
                    page.route("**/api/chats", lambda route: (asked.append(route.request.post_data_json),
                               route.fulfill(status=202, json={"chat": "a" * 32})))
                    page.locator(".call-card[data-status=open] .call-actions button").first.click()
                    page.wait_for_url("**/chat?id=" + "a" * 32)
                    assert asked and asked[0]["mode"] == "secretary" and asked[0]["text"], asked
                    assert not errors, errors
                    browser.close()
                print("screenshots:", sorted(p.name for p in args.screenshots.glob("*.png")))
        finally:
            server.shutdown()


if __name__ == "__main__":
    main()
