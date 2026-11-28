"""Emulator check for the Today widget's checklist (#371), against a local fake server.

    python tests/android/widget_today.py --serial emulator-5554

Needs what widget_chat.py needs, and reuses its fake server, Device and setup. The widget is placed at its
default 2×2 size and checked through a tick, the Undo, an offline queue sent in order once the server is
back, a refused tap, a tap outside the row, and the 04:00 rollover to the cached next day. The day is the
account's (UTC here) from 04:00, worked out from the real clock as the server would. Logs and screenshots
go to `--out` (default: the project scratch folder).
"""

import argparse
import json
import os
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
from widget_chat import LINK_PROMPT, PACKAGE, Device, Fake, build, fresh_app, preflight

REFUSAL = "This task changed since the page loaded."


class Schedule(Fake):
    """The summary with a schedule, and the tick endpoint: answering, down (503) or refusing (409)."""

    def __init__(self):
        super().__init__()
        self.mode = "ok"
        self.rolled = False
        self.language = "en"
        self.widgets = "day"
        self.ticks = []
        self.revisions = {"cu_b": 5, "task_a": 2}
        self.done = {}

    def day(self, offset):
        return (
            (datetime.now(UTC) - timedelta(hours=4) + timedelta(days=offset))
            .date()
            .isoformat()
        )

    def tasks(self, date):
        def row(id, text, kind, **extra):
            return {
                "id": id,
                "text": text,
                "kind": kind,
                "done": self.done.get((id, date), False),
                "revision": self.revisions[id],
                "tickable": True,
                "status": "open",
                "project": "",
                "optional": False,
                **extra,
            }

        return [
            row("task_a", "Pick up a parcel", "todo", project="Home"),
            row("cu_b", "Stretch", "routine", cadence="Every day"),
            {
                "text": "Report due",
                "kind": "deadline",
                "done": False,
                "tickable": False,
            },
        ]

    def summary(self):
        data = super().summary()
        data["language"] = self.language
        data["appearance"]["widgets"] = self.widgets
        # Rolled: fetched before 04:00, so its first day is now yesterday and today is the cached next day.
        dates = (
            [self.day(-1), self.day(0)] if self.rolled else [self.day(0), self.day(1)]
        )
        data["schedule"] = {
            "today": dates[0],
            "timezone": "UTC",
            "days": [
                {"date": date, "events": [], "tasks": self.tasks(date)}
                for date in dates
            ],
            "warnings": [],
        }
        return data

    def handler(fake):
        base = Fake.handler(fake)

        class Handler(base):
            def answer(self):
                if urlsplit(self.path).path != "/api/app/schedule/tick":
                    return super().answer()
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                with fake.lock:
                    fake.requests.append((time.time(), self.command, self.path))
                    fake.ticks.append((fake.mode, body))
                if fake.mode == "down":
                    self.send_response(503)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if fake.mode == "refuse":
                    raw = json.dumps({"error": REFUSAL}).encode()
                    self.send_response(409)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                with fake.lock:
                    fake.revisions[body["id"]] += 1
                    fake.done[(body["id"], body["date"])] = body["done"]
                    revision = fake.revisions[body["id"]]
                self.reply(
                    {
                        "saved": True,
                        "id": body["id"],
                        "date": body["date"],
                        "done": body["done"],
                        "revision": revision,
                    }
                )

            do_GET = do_POST = answer

        return Handler


def widget_bounds(device):
    """The widget's left, top, right and bottom on screen: its largest view around the TODAY label."""
    device.shell("uiautomator dump /sdcard/gm-ui.xml >/dev/null", check=False)
    raw = device.run("exec-out", "cat", "/sdcard/gm-ui.xml", check=False)
    try:
        tree = ElementTree.fromstring(raw[raw.index("<?xml") :])
    except (ElementTree.ParseError, ValueError):
        return None
    found = None
    for node in tree.iter("node"):
        if node.get("package") != PACKAGE or not any(
            inner.get("text", "").startswith("TODAY") for inner in node.iter("node")
        ):
            continue
        box = [
            int(n)
            for n in node.get("bounds", "").replace("][", ",").strip("[]").split(",")
        ]
        if found is None or (box[2] - box[0]) * (box[3] - box[1]) > (
            found[2] - found[0]
        ) * (found[3] - found[1]):
            found = box
    return found


def resize(device, wider, taller):
    """Resizes the widget with the launcher's handles: a long press, then the right and bottom handles."""
    box = widget_bounds(device)
    if not box:
        return None
    left, top, right, bottom = box
    middle, center = (left + right) // 2, (top + bottom) // 2
    device.shell(f"input swipe {middle} {center} {middle} {center} 1500")
    time.sleep(2)
    device.shell(f"input swipe {right} {center} {right + wider} {center} 1200")
    time.sleep(1)
    device.shell(f"input swipe {middle} {bottom} {middle} {bottom + taller} 1200")
    time.sleep(1)
    device.shell("input keyevent KEYCODE_HOME")
    time.sleep(3)
    return widget_bounds(device)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL"))
    parser.add_argument(
        "--out",
        type=Path,
        default=Path.home() / "t3-apps/GoodMorning/scratch/android-widget-today",
    )
    parser.add_argument(
        "--skip-build", action="store_true", help="install the debug APK already built"
    )
    arguments = parser.parse_args()
    adb, problem = preflight(arguments)
    if problem:
        print("PREFLIGHT FAIL: " + problem)
        return 2
    out = arguments.out
    out.mkdir(parents=True, exist_ok=True)
    (out / "adb.log").write_bytes(b"")
    results = []

    def check(name, passed, detail=""):
        results.append(passed)
        print(
            f"{'PASS' if passed else 'FAIL'} {name}"
            + (f": {detail}" if detail else ""),
            flush=True,
        )

    apk = build(arguments, out)
    if apk is None:
        return 1
    fake = Schedule()
    server = ThreadingHTTPServer(("127.0.0.1", 0), fake.handler())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://10.0.2.2:{server.server_address[1]}"
    device = Device(adb, arguments.serial, out)

    def home():
        """The home screen, at the launcher page holding the widget."""
        device.shell("input keyevent KEYCODE_HOME")
        time.sleep(2)
        for _ in range(6):
            if device.find(
                lambda text: text.startswith(("TODAY", LINK_PROMPT)), timeout=2
            ):
                return
            device.shell("input swipe 860 1200 200 1200 300")
            time.sleep(1)

    def sync():
        device.hook("--ez sync true")
        time.sleep(4)
        home()

    def shows(text, timeout=15):
        return device.find(lambda seen: seen == text, timeout=timeout)

    def seen():
        return device.texts()[:12]

    def soon_after(node):
        """Taps the node and reads the widget once, quickly, while its 5-second Undo still shows."""
        if node:
            device.tap(node)
        time.sleep(1.5)
        return {
            text: (text, package, x, y, checked)
            for text, package, x, y, checked in device.nodes()
            if text
        }

    try:
        fresh_app(device, apk, origin)
        device.pin("Checklist")
        device.hook("--ez sync true")
        time.sleep(2)
        home()
        prompt = device.find(lambda text: text.startswith(LINK_PROMPT), timeout=20)
        check(
            "widget placed and unlinked",
            prompt is not None,
            "" if prompt else f"screen: {device.screenshot('placed')}",
        )
        if not prompt:
            return 1
        moment = time.time()
        device.tap(prompt)  # Link this phone pairs with the fake server and syncs.
        deadline = time.time() + 40
        while time.time() < deadline and not fake.since(moment, "/api/app/sync"):
            time.sleep(1)
        check(
            "app links through the fake server",
            bool(fake.since(moment, "/api/app/sync")),
        )
        home()

        # Routines first; the deadline is not part of the list or its count.
        title = shows("0/2", 20)
        row = shows("Stretch")
        check(
            "small widget: count and the next routine",
            title is not None and row is not None,
            f"saw {seen()}",
        )
        device.screenshot("today-small")

        # A tick flips at once, offers Undo and keeps the row where it was, then settles on the next row.
        snapshot = soon_after(row)
        check(
            "after the tick: 1/2, the row stays with Undo",
            {"1/2", "Stretch", "Undo"} <= set(snapshot),
            f"saw {list(snapshot)[:12]}",
        )
        device.screenshot("today-small-undo")
        time.sleep(2)
        sent = [body for _, body in fake.ticks]
        check(
            "tick reaches the server with the row's revision and today's date",
            sent[-1:]
            and sent[-1]["id"] == "cu_b"
            and sent[-1]["revision"] == 5
            and sent[-1]["done"] is True
            and sent[-1]["date"] == fake.day(0),
            f"sent {sent}",
        )
        time.sleep(4)
        home()
        check(
            "once Undo ends the next row shows",
            shows("Pick up a parcel", 10) is not None and not shows("Undo", 2),
            f"saw {seen()}",
        )

        # Offline: the tap waits on the phone; Undo queues the opposite; both go out in order once back.
        fake.mode = "down"
        snapshot = soon_after(shows("Pick up a parcel"))
        check(
            "offline: the tick shows and waits",
            {"All done", "Pick up a parcel", "Not sent yet", "Undo"} <= set(snapshot),
            f"saw {list(snapshot)[:12]}",
        )
        device.screenshot("today-small-offline")
        if "Undo" in snapshot:
            device.tap(snapshot["Undo"])
        time.sleep(3)
        attempts = [body for mode, body in fake.ticks if mode == "down"]
        fake.mode = "ok"
        before = len(fake.ticks)
        sync()
        time.sleep(3)
        later = [body for _, body in fake.ticks[before:]]
        check(
            "back online: waiting ticks go out one at a time, the retry with its key, the next with the new revision",
            len(later) == 2
            and attempts
            and later[0]["key"] == attempts[0]["key"]
            and later[0]["done"] is True
            and later[0]["revision"] == 2
            and later[1]["done"] is False
            and later[1]["revision"] == 3,
            f"while down {attempts}; then {later}",
        )
        check(
            "after sending: back to 1/2",
            shows("1/2", 10) is not None and not shows("Not sent yet", 2),
            f"saw {seen()}",
        )

        # A refused tap puts the row back and shows the server's reason.
        fake.mode = "refuse"
        parcel = shows("Pick up a parcel")
        if parcel:
            device.tap(parcel)
        time.sleep(4)
        home()
        reason = device.find(
            lambda text: text == f"“Pick up a parcel”: {REFUSAL}", timeout=10
        )
        check(
            "refused: the server's reason shows and the row is open again",
            reason is not None and shows("1/2", 5) is not None,
            f"saw {seen()}",
        )
        device.screenshot("today-small-refused")
        fake.mode = "ok"

        # Outside the row: the day schedule in the app.
        moment = time.time()
        count = shows("1/2")
        if count:
            device.tap(count)
        deadline = time.time() + 30
        opened = []
        while time.time() < deadline and not opened:
            opened = [
                parse_qs(urlsplit(entry[2]).query).get("next", [""])[0]
                for entry in fake.since(moment, "/app")
            ]
            time.sleep(1)
        check(
            "a tap outside the row opens /schedule?view=day",
            opened[:1] == ["/schedule?view=day"],
            f"opened {opened or 'nothing'}",
        )
        home()

        # 04:00 passed since the last summary: the cached next day shows and ticks, without a new sync first.
        fake.rolled = True
        fake.done.clear()
        sync()
        fake.mode = "down"  # No answer may stand in for the rollover.
        stretch = shows("Stretch", 10)
        check(
            "rolled over: the cached next day's list",
            shows("0/2", 5) is not None and stretch is not None,
            f"saw {seen()}",
        )
        before = len(fake.ticks)
        if stretch:
            device.tap(stretch)
        time.sleep(3)
        later = [body for _, body in fake.ticks[before:]]
        check(
            "rolled over: a tick goes out for today's date",
            later[:1] and later[0]["date"] == fake.day(0),
            f"sent {later}",
        )
        fake.mode = "ok"
        sync()
        device.screenshot("today-small-rolled")

        def gallery(size):
            for language in ("en", "zh-CN"):
                for scheme in ("day", "night"):
                    fake.language, fake.widgets = language, scheme
                    sync()
                    device.screenshot(f"today-{size}-{scheme}-{language}")
            fake.language, fake.widgets = "en", "day"
            sync()

        gallery("small")
        # Large: resized to about 4×4, the whole list under the progress, done rows under "Done · N".
        before = widget_bounds(device)
        after = resize(device, 560, 700)
        home()
        label = device.find(lambda text: text.startswith("TODAY · "), timeout=15)
        check(
            "large widget: the whole list with its progress and Done · N",
            label is not None
            and shows("1 of 2 done", 5) is not None
            and shows("Pick up a parcel", 5) is not None
            and shows("Stretch", 5) is not None
            and shows("Done · 1", 5) is not None,
            f"bounds {before} -> {after}; saw {seen()}",
        )
        if label:
            gallery("large")
            # The large list ticks a row too, with Undo in its header.
            snapshot = soon_after(shows("Pick up a parcel"))
            check(
                "large widget: a row ticks, with Undo",
                {"All done for today", "Undo"} <= set(snapshot),
                f"saw {list(snapshot)[:14]}",
            )
            device.screenshot("today-large-undo")
            time.sleep(5)
            home()
            check(
                "large widget: all done settles under Done · 2",
                shows("Done · 2", 10) is not None,
                f"saw {seen()}",
            )
            device.screenshot("today-large-all-done")
            resize(device, -560, -700)  # Back to 2×2, so a rerun starts small.
    except (RuntimeError, OSError) as error:
        check("device steps", False, str(error))
    finally:
        server.shutdown()
        (out / "requests.log").write_text(
            "".join(f"{at:.1f} {method} {path}\n" for at, method, path in fake.requests)
        )
        (out / "ticks.log").write_text(
            "".join(f"{mode} {json.dumps(body)}\n" for mode, body in fake.ticks)
        )
    print(f"{sum(results)}/{len(results)} passed; logs and screenshots in {out}")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
