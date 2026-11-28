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
                    return self.reply(
                        f"<!doctype html><title>Chat</title><script>{away}</script>",
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

    def has_chat_widget(self):
        # The dump names each provider once, then once more per placed widget.
        return self.shell("dumpsys appwidget").count(f"{PACKAGE}.Widgets$Chat") > 1

    def hook(self, *extras):
        self.shell(f"am start -n {PACKAGE}/.TestHooks " + " ".join(extras))

    def screenshot(self, name):
        path = self.out / f"{name}.png"
        path.write_bytes(
            subprocess.run(
                [self.adb, "-s", self.serial, "exec-out", "screencap", "-p"],
                capture_output=True,
                timeout=30,
            ).stdout
        )
        return path


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

    android = ROOT / "android"
    if not arguments.skip_build:
        with open(out / "gradle.log", "wb") as log:
            built = subprocess.run(
                ["./gradlew", "-q", "assembleDebug"],
                cwd=android,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=900,
            )
        if built.returncode:
            print(f"FAIL build: see {out / 'gradle.log'}")
            return 1
    apk = android / "app/build/outputs/apk/debug/app-debug.apk"
    if not apk.exists():
        print("PREFLIGHT FAIL: no debug APK; run without --skip-build")
        return 2

    fake = Fake()
    server = ThreadingHTTPServer(("127.0.0.1", 0), fake.handler())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://10.0.2.2:{server.server_address[1]}"
    device = Device(adb, arguments.serial, out)
    try:
        # A clean app, pointed at the fake server; force-stop drops the settings a running process holds.
        device.run("install", "-r", str(apk), timeout=240)
        device.shell(f"pm clear {PACKAGE}")
        prefs = f"<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n<map><string name=\"server\">{origin}</string></map>\n"
        device.run(
            "shell",
            f"run-as {PACKAGE} sh -c 'mkdir -p shared_prefs && cat > shared_prefs/app.xml'",
            input=prefs.encode(),
        )
        device.shell(f"am force-stop {PACKAGE}")

        # Place the widget once; a rerun finds it again, showing the link prompt after the data was cleared.
        if not device.has_chat_widget():
            device.hook("--es pin Chat")
            add = device.find(
                lambda text: (
                    text.lower() in ("add to home screen", "add automatically", "add")
                ),
                timeout=15,
            )
            if add:
                device.tap(add)
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

        def scenario(name, chat, ago, shown, expected_path, change_before_tap=None):
            fake.chat = {
                "id": CHAT,
                "title": "Trip plan",
                "unread": False,
                "active": time.time() - 3600,
                "reply": REPLY,
                **chat,
            }
            device.hook(f"--es departed {CHAT} --ei ago {ago} --ez sync true")
            time.sleep(2)
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
            if change_before_tap:
                fake.chat.update(change_before_tap)
            name_node = device.find(lambda text: text == NAME, timeout=5)
            moment = time.time()
            if name_node:
                device.tap(name_node)
            deadline = time.time() + 30
            opened = []
            while time.time() < deadline and not opened:
                opened = [
                    parse_qs(urlsplit(entry[2]).query).get("next", [""])[0]
                    for entry in fake.since(moment, "/app")
                ]
                time.sleep(1)
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
        device.hook(f"--es departed {'b' * 32} --ei ago 60 --ez sync true")
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
        departed = re.search(r'name="departedChat">([^<]*)<', record)
        at = re.search(r'name="departedAt" value="(\d+)"', record)
        when = int(at[1]) / 1000 if at else 0
        check(
            "leaving the chat page in the app records the departure then",
            bool(left)
            and departed is not None
            and departed[1] == CHAT
            and abs(when - left[0][0]) < 3
            and home - when > 3,
            f"left at {left[0][0] if left else None}, recorded {departed[1] if departed else None} at {when}, home at {home}",
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
