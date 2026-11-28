"""Emulator check for the chat widget's conversation restore (#352), against a local fake server.

    python tests/android/widget_chat.py --serial emulator-5554

Needs a booted emulator (yanglab16: `android-emu`) and JDK 17 (`JAVA_HOME`). It builds and installs the debug
APK, whose debug-only overlay allows plain HTTP to the emulator host (10.0.2.2) and adds the TestHooks
activity. The app links itself through the fake server's pairing endpoints, so it seals a real token, then
the chat widget is placed and checked. Time away is simulated with the phone's departure record
(TestHooks) and the summary's `active` time, not the emulator clock. Rerunning clears the app's data first.
Logs and screenshots go to `--out` (default: the project scratch folder).
"""

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "me.love765.goodmorning"
CHAT = "a" * 32
NAME = "Aria"
REPLY = "All set for Friday."
LINK_PROMPT = "Link this phone to show"
EMPTY = f"Tap the message box below to talk to {NAME}."
WAITING = f"{NAME} needs your answer"


class Fake:
    """The server side: pairing, the app summary with a chat the test changes, and a placeholder /app."""

    def __init__(self):
        self.chat = None
        self.leave_chat = False
        self.draft = False
        self.requests = []
        self.lock = threading.Lock()

    def summary(self):
        return {
            "device": "0123456789abcdef",
            "settings": {},
            "language": "en",
            "appearance": {"day": "morning-sky", "night": "starry", "widgets": "day"},
            "notifications": [],
            "busy": False,
            "schedule": None,
            "secretary": {"name": NAME, "avatar": "f1"},
            "reminders": [],
            "chat": self.chat,
            "briefings": None,
            "weather": None,
        }

    def handler(fake):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def reply(self, value, kind="application/json"):
                body = (
                    json.dumps(value) if kind == "application/json" else value
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def answer(self):
                path = urlsplit(self.path).path
                with fake.lock:
                    fake.requests.append((time.time(), self.command, self.path))
                if path == "/api/app/pair" and self.command == "POST":
                    return self.reply(
                        {"code": "TEST-0001", "secret": "s" * 32, "expires": 600}
                    )
                if path == "/api/app/pair":
                    return self.reply({"token": "t" * 43})
                if path == "/api/app/sync":
                    return self.reply(fake.summary())
                if path == "/app":
                    # Follows `next` like the real /app; a plain page otherwise.
                    target = json.dumps(
                        parse_qs(urlsplit(self.path).query).get("next", [""])[0]
                    )
                    return self.reply(
                        f"<!doctype html><script>if ({target}) location.replace({target})</script>",
                        "text/html",
                    )
                if path == "/chat":
                    # Leaves the conversation by in-app navigation once asked to (the departure check).
                    away = (
                        "setTimeout(() => location.href = '/schedule', 1500)"
                        if fake.leave_chat
                        else ""
                    )
                    # chat.js's own unsent-input check, which the app asks before opening a fresh conversation.
                    draft = f"function hasUnsentInput() {{ return {str(fake.draft).lower()} }}"
                    return self.reply(
                        f"<!doctype html><title>Chat</title><script>{draft}; {away}</script>",
                        "text/html",
                    )
                if path == "/schedule":
                    return self.reply(
                        "<!doctype html><title>Schedule</title>", "text/html"
                    )
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

            do_GET = do_POST = answer

        return Handler

    def since(self, moment, path):
        with self.lock:
            return [
                entry
                for entry in self.requests
                if entry[0] >= moment and urlsplit(entry[2]).path == path
            ]


class Device:
    def __init__(self, adb, serial, out):
        self.adb, self.serial, self.out = adb, serial, out

    def run(self, *args, check=True, timeout=60, **kwargs):
        result = subprocess.run(
            [self.adb, "-s", self.serial, *args],
            check=False,
            capture_output=True,
            timeout=timeout,
            **kwargs,
        )
        with open(self.out / "adb.log", "ab") as log:
            log.write(
                b"$ adb "
                + " ".join(args).encode()
                + b"\n"
                + result.stdout[-2000:]
                + result.stderr[-2000:]
                + b"\n"
            )
        if check and result.returncode:
            raise RuntimeError(
                f"adb {' '.join(args)} failed: {result.stderr.decode().strip()[:200]}"
            )
        return result.stdout.decode(errors="replace")

    def shell(self, command, **kwargs):
        return self.run("shell", command, **kwargs)

    def nodes(self):
        self.shell("uiautomator dump /sdcard/gm-ui.xml >/dev/null", check=False)
        raw = self.run("exec-out", "cat", "/sdcard/gm-ui.xml", check=False)
        try:
            tree = ElementTree.fromstring(
                raw[raw.index("<?xml") :] if "<?xml" in raw else raw
            )
        except (ElementTree.ParseError, ValueError):
            return []
        found = []
        for node in tree.iter("node"):
            bounds = [int(n) for n in re.findall(r"\d+", node.get("bounds", ""))]
            if len(bounds) == 4:
                found.append(
                    (
                        node.get("text", ""),
                        node.get("package", ""),
                        (bounds[0] + bounds[2]) // 2,
                        (bounds[1] + bounds[3]) // 2,
                        node.get("checked") == "true",
                    )
                )
        return found

    def find(self, match, timeout=20):
        deadline = time.time() + timeout
        while time.time() < deadline:
            for node in self.nodes():
                if match(node[0]):
                    return node
            time.sleep(1)
        return None

    def texts(self):
        return [node[0] for node in self.nodes() if node[0]]

    def tap(self, node):
        self.shell(f"input tap {node[2]} {node[3]}")

    def home(self):
        """The home screen, at the launcher page holding the chat widget."""
        self.shell("input keyevent KEYCODE_HOME")
        time.sleep(1)
        size = re.findall(r"\d+", self.shell("wm size"))[-2:]
        width, height = int(size[0]), int(size[1])
        for _ in range(6):
            if self.find(
                lambda text: text == "SECRETARY" or text.startswith(LINK_PROMPT),
                timeout=2,
            ):
                return
            self.shell(
                f"input swipe {width * 4 // 5} {height // 2} {width // 5} {height // 2} 300"
            )
            time.sleep(1)

    def pin(self, widget):
        """Places that widget unless one is already placed; the dump names each provider once, then per widget."""
        if self.shell("dumpsys appwidget").count(f"{PACKAGE}.Widgets${widget}") > 1:
            return
        self.hook(f"--es pin {widget}")
        add = self.find(
            lambda text: (
                text.lower() in ("add to home screen", "add automatically", "add")
            ),
            timeout=15,
        )
        if add:
            self.tap(add)

    def hook(self, *extras):
        self.shell(f"am start -n {PACKAGE}/.TestHooks " + " ".join(extras))

    def screenshot(self, name):
        path = self.out / f"{name}.png"
        path.write_bytes(
            subprocess.run(
                [self.adb, "-s", self.serial, "exec-out", "screencap", "-p"],
                check=False,
                capture_output=True,
                timeout=30,
            ).stdout
        )
        return path


def fresh_app(device, apk, origin):
    """A clean app, pointed at the fake server; force-stop drops the settings a running process holds."""
    device.run("install", "-r", str(apk), timeout=240)
    device.shell(f"pm clear {PACKAGE}")
    prefs = f"<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n<map><string name=\"server\">{origin}</string></map>\n"
    device.run(
        "shell",
        f"run-as {PACKAGE} sh -c 'mkdir -p shared_prefs && cat > shared_prefs/app.xml'",
        input=prefs.encode(),
    )
    device.shell(f"am force-stop {PACKAGE}")


def build(arguments, out):
    """The debug APK, built unless --skip-build; None when it failed or is missing."""
    android = ROOT / "android"
    if not arguments.skip_build:
        with open(out / "gradle.log", "wb") as log:
            built = subprocess.run(
                ["./gradlew", "-q", "assembleDebug"],
                check=False,
                cwd=android,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=900,
            )
        if built.returncode:
            print(f"FAIL build: see {out / 'gradle.log'}")
            return None
    apk = android / "app/build/outputs/apk/debug/app-debug.apk"
    if not apk.exists():
        print("PREFLIGHT FAIL: no debug APK; run without --skip-build")
        return None
    return apk


def preflight(arguments):
    adb = shutil.which("adb") or str(
        Path(os.environ.get("ANDROID_HOME", "")) / "platform-tools" / "adb"
    )
    if not Path(adb).exists():
        return None, "adb not found: put platform-tools on PATH or set ANDROID_HOME"
    if not arguments.serial:
        return (
            None,
            "no emulator named: pass --serial (yanglab16: start one with android-emu)",
        )
    state = subprocess.run(
        [adb, "-s", arguments.serial, "shell", "getprop", "sys.boot_completed"],
        check=False,
        capture_output=True,
        timeout=20,
    )
    if state.stdout.strip() != b"1":
        return None, f"emulator {arguments.serial} is not booted or not reachable"
    if (
        not arguments.skip_build
        and not Path(
            os.environ.get("JAVA_HOME", "/nonexistent"), "bin", "javac"
        ).exists()
    ):
        return (
            None,
            "JAVA_HOME must point at a JDK 17 (yanglab16: /usr/lib/jvm/java-17-openjdk-amd64)",
        )
    return adb, None


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL"))
    parser.add_argument(
        "--out",
        type=Path,
        default=Path.home() / "t3-apps/GoodMorning/scratch/android-widget-chat",
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

    fake = Fake()
    server = ThreadingHTTPServer(("127.0.0.1", 0), fake.handler())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://10.0.2.2:{server.server_address[1]}"
    device = Device(adb, arguments.serial, out)
    try:
        fresh_app(device, apk, origin)
        # Place the widget once; a rerun finds it again, showing the link prompt after the data was cleared.
        device.pin("Chat")
        device.hook(
            "--ez sync true"
        )  # Unlinked, this redraws every widget with the link prompt.
        time.sleep(2)
        device.home()
        prompt = device.find(lambda text: text.startswith(LINK_PROMPT), timeout=20)
        check(
            "widget placed and unlinked",
            prompt is not None,
            "" if prompt else f"screen: {device.screenshot('placed')}",
        )
        if not prompt:
            return 1

        moment = time.time()
        fake.chat = {
            "id": CHAT,
            "title": "Trip plan",
            "state": "idle",
            "unread": False,
            "active": time.time() - 3600,
            "reply": REPLY,
        }
        device.tap(
            prompt
        )  # Opens Link this phone, which pairs with the fake server and syncs.
        deadline = time.time() + 40
        while time.time() < deadline and not fake.since(moment, "/api/app/sync"):
            time.sleep(1)
        check(
            "app links through the fake server",
            bool(fake.since(moment, "/api/app/sync")),
        )
        device.home()

        def prepare(chat, ago):
            """The server's chat, then this phone's times: left `ago` minutes ago, last reply read long before.
            The first sync lets the phone see any state change before the times are set over it."""
            fake.chat = {
                "id": CHAT,
                "title": "Trip plan",
                "unread": False,
                "active": time.time() - 3600,
                "reply": REPLY,
                "reply_id": "m1",
                **chat,
            }
            device.hook("--ez sync true")
            time.sleep(3)
            device.hook(
                f"--es departed {CHAT} --ei ago {ago} --ei replied_ago 600 --ez sync true"
            )
            time.sleep(3)

        def opened_after(moment):
            deadline = time.time() + 30
            opened = []
            while time.time() < deadline and not opened:
                opened = [
                    parse_qs(urlsplit(entry[2]).query).get("next", [""])[0]
                    for entry in fake.since(moment, "/app")
                ]
                time.sleep(1)
            return opened

        def scenario(name, chat, ago, shown, expected_path, change_before_tap=None):
            prepare(chat, ago)
            device.home()
            node = device.find(lambda text: text == shown, timeout=20)
            check(
                f"{name}: widget shows {shown!r}",
                node is not None,
                ""
                if node
                else f"saw {device.texts()[:8]}; screen {device.screenshot(name.replace(' ', '-'))}",
            )
            device.screenshot(name.replace(" ", "-"))
            if change_before_tap == "unavailable":
                fake.chat = None  # The server couldn't read the conversations.
            elif change_before_tap:
                fake.chat.update(change_before_tap)
            name_node = device.find(lambda text: text == NAME, timeout=5)
            moment = time.time()
            if name_node:
                device.tap(name_node)
            opened = opened_after(moment)
            check(
                f"{name}: tap opens {expected_path}",
                opened[:1] == [expected_path],
                f"opened {opened or 'nothing'}",
            )
            device.home()

        scenario(
            "settled 14 min away", {"state": "idle"}, 14, REPLY, f"/chat?id={CHAT}"
        )
        scenario(
            "settled 16 min away", {"state": "idle"}, 16, EMPTY, "/chat?mode=secretary"
        )
        scenario(
            "waiting 16 min away", {"state": "waiting"}, 16, WAITING, f"/chat?id={CHAT}"
        )
        scenario(
            "unread 16 min away",
            {"state": "idle", "unread": True},
            16,
            REPLY,
            f"/chat?id={CHAT}",
        )
        # Drawn empty from a settled summary, but running by the time of the tap: the tap's own check keeps it.
        scenario(
            "settled then running at tap",
            {"state": "idle"},
            16,
            EMPTY,
            f"/chat?id={CHAT}",
            {"state": "running"},
        )

        # A failed check at tap time never starts fresh from the cached summary.
        scenario(
            "settled then unavailable at tap",
            {"state": "idle"},
            16,
            EMPTY,
            f"/chat?id={CHAT}",
            "unavailable",
        )

        # A reply that finishes while the user is away keeps the conversation until they have read it.
        prepare({"state": "running", "reply": ""}, 16)
        fake.chat.update(state="idle", reply="Booked the 9:40 train.", reply_id="m2")
        device.hook("--ez sync true")
        time.sleep(3)
        device.home()
        kept = device.find(lambda text: text == "Booked the 9:40 train.", timeout=20)
        check(
            "reply finished while away: widget keeps it",
            kept is not None,
            "" if kept else f"saw {device.texts()[:8]}",
        )
        name_node = device.find(lambda text: text == NAME, timeout=5)
        moment = time.time()
        if name_node:
            device.tap(name_node)
        opened = opened_after(moment)
        check(
            f"reply finished while away: tap opens /chat?id={CHAT}",
            opened[:1] == [f"/chat?id={CHAT}"],
            f"opened {opened or 'nothing'}",
        )
        device.home()

        def kept(name, shown):
            """The widget still shows this conversation and a tap opens it."""
            device.home()
            node = device.find(lambda text: text == shown, timeout=20)
            check(
                f"{name}: widget keeps it",
                node is not None,
                "" if node else f"saw {device.texts()[:8]}",
            )
            name_node = device.find(lambda text: text == NAME, timeout=5)
            moment = time.time()
            if name_node:
                device.tap(name_node)
            opened = opened_after(moment)
            check(
                f"{name}: tap opens /chat?id={CHAT}",
                opened[:1] == [f"/chat?id={CHAT}"],
                f"opened {opened or 'nothing'}",
            )
            device.home()

        def sync():
            device.hook("--ez sync true")
            time.sleep(3)

        # Seen running, then another conversation was the latest while this one settled: still a reply not read.
        prepare({"state": "running", "reply": "", "reply_id": ""}, 16)
        mine = fake.chat
        fake.chat = {
            **mine,
            "id": "b" * 32,
            "title": "Other plan",
            "state": "idle",
            "reply": "Noted.",
            "reply_id": "b1",
        }
        sync()
        fake.chat = {
            **mine,
            "state": "idle",
            "reply": "Booked the 9:40 train.",
            "reply_id": "m2",
        }
        sync()
        kept("reply settled while another was latest", "Booked the 9:40 train.")

        # A new reply with the same text as the last one is still new.
        prepare({"state": "idle"}, 16)
        fake.chat.update(reply_id="m3")
        sync()
        kept("new reply with the same text", REPLY)

        # A chat page in the app holding an unsent draft is not replaced by a fresh conversation.
        prepare({"state": "idle"}, 14)
        fake.draft = True
        device.home()
        name_node = device.find(lambda text: text == NAME, timeout=5)
        if name_node:
            device.tap(name_node)  # Opens the conversation, which now holds a draft.
        opened_after(time.time() - 1)
        time.sleep(3)
        device.home()
        prepare({"state": "idle"}, 16)
        device.home()
        name_node = device.find(lambda text: text == NAME, timeout=5)
        moment = time.time()
        if name_node:
            device.tap(name_node)
        time.sleep(10)
        reloaded = [
            parse_qs(urlsplit(entry[2]).query).get("next", [""])[0]
            for entry in fake.since(moment, "/app")
        ] + [entry[2] for entry in fake.since(moment, "/chat")]
        check(
            "a chat page with a draft stays instead of opening fresh",
            reloaded == [],
            f"loaded {reloaded}",
        )
        # Nor by another conversation the widget now shows.
        fake.chat = {
            **fake.chat,
            "id": "b" * 32,
            "title": "Other plan",
            "state": "idle",
            "reply": "Noted.",
            "reply_id": "b1",
        }
        sync()
        device.home()
        other = device.find(lambda text: text == "Noted.", timeout=20)
        name_node = device.find(lambda text: text == NAME, timeout=5)
        moment = time.time()
        if other and name_node:
            device.tap(name_node)
        time.sleep(10)
        reloaded = [
            parse_qs(urlsplit(entry[2]).query).get("next", [""])[0]
            for entry in fake.since(moment, "/app")
        ] + [entry[2] for entry in fake.since(moment, "/chat")]
        check(
            "a chat page with a draft stays instead of opening another conversation",
            other is not None and name_node is not None and reloaded == [],
            f"widget showed other: {other is not None}; loaded {reloaded}",
        )
        fake.draft = False
        # The drafted page would hold off every later chat load; start the app afresh.
        device.shell(f"am force-stop {PACKAGE}")
        device.home()

        # Ask starts fresh by default only once the server confirms the conversation is still settled.
        def ask(name, ago, at_open, expected):
            prepare({"state": "idle"}, ago)
            device.home()
            if at_open == "unavailable":
                fake.chat = None
            composer = device.find(lambda text: text == f"Message {NAME}…", timeout=10)
            if composer:
                device.tap(composer)
            time.sleep(5)  # The dialog's own check.
            box = device.find(
                lambda text: text == "Start a new conversation", timeout=10
            )
            device.screenshot("ask-" + name.replace(" ", "-"))
            check(
                f"Ask, {name}: starts new by default is {expected}",
                box is not None and box[4] == expected,
                f"box {'checked' if box and box[4] else 'missing' if box is None else 'clear'}",
            )
            device.shell("input keyevent KEYCODE_BACK")
            time.sleep(1)
            device.shell("input keyevent KEYCODE_BACK")
            device.home()

        ask("settled 14 min away", 14, None, False)
        ask("settled 16 min away", 16, None, True)
        ask("settled 16 min away, check fails", 16, "unavailable", False)

        # The user's own choice in Ask survives the dialog being recreated (as on rotation), when it checks again.
        # A dark-mode switch recreates it the same way; the launcher behind it keeps the screen upright.
        prepare({"state": "idle"}, 16)
        device.home()
        composer = device.find(lambda text: text == f"Message {NAME}…", timeout=10)
        if composer:
            device.tap(composer)
        time.sleep(5)
        box = device.find(lambda text: text == "Start a new conversation", timeout=10)
        if box:
            device.tap(box)  # Cleared by the user.
        device.shell("cmd uimode night yes")
        time.sleep(8)  # Recreated, and its new check has answered.
        after = device.find(lambda text: text == "Start a new conversation", timeout=10)
        device.screenshot("ask-rotated")
        device.shell("cmd uimode night no")
        check(
            "Ask keeps the user's choice when recreated",
            box is not None and box[4] and after is not None and not after[4],
            f"before tap {'checked' if box and box[4] else 'clear'}, after recreation {'missing' if after is None else 'checked' if after[4] else 'clear'}",
        )
        device.shell("input keyevent KEYCODE_BACK")
        time.sleep(1)
        device.shell("input keyevent KEYCODE_BACK")
        device.home()

        # Leaving the conversation for another page in the app starts its time away then, not at Home.
        fake.chat = {
            "id": CHAT,
            "title": "Trip plan",
            "state": "idle",
            "unread": False,
            "active": time.time() - 3600,
            "reply": REPLY,
        }
        fake.leave_chat = True
        device.hook(f"--es departed {'b' * 32} --ei ago 60")
        time.sleep(2)
        device.hook(
            f"--es departed {CHAT} --ei ago 1 --ez sync true"
        )  # Continued, not fresh.
        time.sleep(3)
        device.home()
        name_node = device.find(lambda text: text == NAME, timeout=10)
        moment = time.time()
        if name_node:
            device.tap(name_node)
        deadline = time.time() + 30
        while time.time() < deadline and not fake.since(moment, "/schedule"):
            time.sleep(1)
        left = fake.since(moment, "/schedule")
        time.sleep(
            6
        )  # Home comes well after the navigation, so the two times are apart.
        home = time.time()
        device.home()
        time.sleep(2)
        record = device.run(
            "shell", f"run-as {PACKAGE} cat shared_prefs/sync.xml", check=False
        )
        saved = re.search(r'name="departures">([^<]*)<', record)
        departures = json.loads(html.unescape(saved[1])) if saved else {}
        when = departures.get(CHAT, 0) / 1000
        check(
            "leaving the chat page in the app records the departure then",
            bool(left) and abs(when - left[0][0]) < 3 and home - when > 3,
            f"left at {left[0][0] if left else None}, recorded {when}, home at {home}",
        )
        check(
            "leaving one conversation keeps another's departure",
            "b" * 32 in departures,
            f"departures for {sorted(key[:4] for key in departures)}",
        )
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        check("device steps", False, str(error))
    finally:
        server.shutdown()
        (out / "requests.log").write_text(
            "".join(f"{at:.1f} {method} {path}\n" for at, method, path in fake.requests)
        )
    print(f"{sum(results)}/{len(results)} passed; logs and screenshots in {out}")
    return 0 if results and all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
