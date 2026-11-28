"""Page-switch timings through the real gateway with a synthetic account (issue #346).

Chromium talks to the gateway over real HTTPS (a local TLS proxy standing in for NGINX), so the
service worker, its offline refresh and the HTTP cache behave as on the live site. Per page switch
it records the navigation timing (service worker start, first byte, first contentful paint) and
screencast frames, and counts frames that show a blank white canvas instead of the page.

    PY --with playwright tests/benchmarks/page_switch.py OUT_DIR [--rounds N]

Prints one JSON summary and writes it to OUT_DIR/page_switch.json."""

import http.client
import io
import json
import ssl
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from base64 import b64decode
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image
from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
from support import TEMP_ROOT

HOST = "https://gm.language.test"
TIMING = """() => { const n = performance.getEntriesByType('navigation')[0];
    const fcp = performance.getEntriesByName('first-contentful-paint')[0];
    return {path: location.pathname, ttfb: n.responseStart, fcp: fcp ? fcp.startTime : null, controlled: !!navigator.serviceWorker.controller}; }"""
FCP = "() => new Promise(done => { const seen = () => performance.getEntriesByName('first-contentful-paint').length; if (seen()) return done(); new PerformanceObserver(() => seen() && done()).observe({type: 'paint', buffered: true}); })"


def proxy(gateway, directory, log, network):
    """NGINX's part: TLS, the forwarded headers, and passing every response through unchanged. A phone's
    connection is emulated here, so it slows the worker's own requests too: network["latency"] seconds before
    every response and network["asset"] more before stylesheets, scripts and fonts."""
    target = urlsplit(gateway)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def handle_one_request(self):
            try:
                super().handle_one_request()
            except (ConnectionError, ssl.SSLError):
                self.close_connection = True

        def relay(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            headers = {
                k: v
                for k, v in self.headers.items()
                if k.lower() not in ("connection", "keep-alive")
            }
            headers.update({"X-Forwarded-Proto": "https", "X-Real-IP": "192.0.2.1"})
            started = time.monotonic()
            upstream = http.client.HTTPConnection(
                target.hostname, target.port, timeout=120
            )
            upstream.request(self.command, self.path, body or None, headers)
            response = upstream.getresponse()
            path = self.path.split("?")[0]
            time.sleep(
                network["latency"]
                + (network["asset"] if path.endswith((".css", ".js", ".woff2")) else 0)
            )
            log.append((started, time.monotonic(), self.command, path, response.status))
            self.send_response_only(response.status, response.reason)
            length = response.getheader("Content-Length")
            for key, value in response.getheaders():
                if key.lower() not in ("connection", "keep-alive", "transfer-encoding"):
                    self.send_header(key, value)
            if length is None:
                self.send_header("Connection", "close")
                self.close_connection = True
            self.end_headers()
            while chunk := response.read1(65536):
                self.wfile.write(chunk)
                self.wfile.flush()
            upstream.close()

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = relay

    certificate, key = directory / "cert.pem", directory / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=*.language.test",
            "-keyout",
            key,
            "-out",
            certificate,
        ],
        check=True,
        capture_output=True,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_port


def blank(frame):
    """A frame that is almost entirely pure white: the canvas before the page's colours arrive."""
    image = Image.open(io.BytesIO(b64decode(frame))).convert("RGB").resize((40, 80))
    pixels = list(image.get_flattened_data())
    return sum(min(pixel) >= 250 for pixel in pixels) / len(pixels) > 0.9


def summary(values):
    values = [v for v in values if v is not None]
    if not values:
        return None
    return {
        "median": round(statistics.median(values)),
        "max": round(max(values)),
        "n": len(values),
    }


def session_check_cost(rounds=300):
    """Gateway-side cost of the session check that runs on every request."""
    from goodmorning.security.briefing_accounts import Accounts

    with tempfile.TemporaryDirectory(
        dir=TEMP_ROOT, prefix="gm-switch-db-"
    ) as directory:
        store = Accounts(Path(directory), testing=True, n=1024)
        store.create("alice", "a1alice-temporary")
        token, _ = store.anonymous("gm.language.test")
        times = []
        for _ in range(rounds):
            start = time.perf_counter()
            store.session(token, "gm.language.test")
            times.append((time.perf_counter() - start) * 1e6)
        return {
            "median_us": round(statistics.median(times)),
            "p95_us": round(sorted(times)[int(rounds * 0.95)]),
        }


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    rounds = (
        int(sys.argv[sys.argv.index("--rounds") + 1]) if "--rounds" in sys.argv else 6
    )
    log, network = [], {"latency": 0, "asset": 0}
    with tempfile.TemporaryDirectory(dir=TEMP_ROOT, prefix="gm-switch-") as directory:
        directory = Path(directory)
        (directory / "fixture").mkdir()
        fixture = subprocess.Popen(
            [
                sys.executable,
                str(REPO / "tests/browser/language.py"),
                "--serve",
                str(directory / "fixture"),
            ],
            stdout=subprocess.PIPE,
            stderr=open(out / "fixture.log", "w"),
            text=True,
        )
        try:
            while not (line := fixture.stdout.readline()).startswith("{"):
                if not line:
                    raise RuntimeError(
                        "Synthetic gateway fixture did not start; see fixture.log."
                    )
            port = proxy(json.loads(line)["gateway"], directory, log, network)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    args=[
                        f"--host-resolver-rules=MAP *.language.test 127.0.0.1:{port}",
                        "--ignore-certificate-errors",
                    ]
                )
                context = browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    ignore_https_errors=True,
                    timezone_id="Europe/London",
                    reduced_motion="reduce",
                )
                page = context.new_page()
                sign_in(page)
                page.goto(HOST + "/gm")
                page.wait_for_function(
                    "() => navigator.serviceWorker.controller !== null", timeout=15000
                )
                pages = page.eval_on_selector_all(
                    "nav a.edition-link",
                    "links => [...new Set(links.map(a => a.getAttribute('href')))]",
                )
                pages = [p for p in pages if p.startswith("/") and p != "/gm"][:4] + [
                    "/gm"
                ]
                client = context.new_cdp_session(page)
                workers = {}
                client.on(
                    "ServiceWorker.workerVersionUpdated",
                    lambda event: workers.update(
                        {v["versionId"]: v["runningStatus"] for v in event["versions"]}
                    ),
                )
                client.send("ServiceWorker.enable")
                client.send("Network.enable")
                frames = []
                client.on(
                    "Page.screencastFrame",
                    lambda event: (
                        frames.append(event["data"]),
                        client.send(
                            "Page.screencastFrameAck", {"sessionId": event["sessionId"]}
                        ),
                    ),
                )

                def switch(path, before=None):
                    """Click the page bar link; the new page's timings, white frames and the worker's refreshes around it."""
                    if before:
                        before()
                    frames.clear()
                    client.send(
                        "Page.startScreencast",
                        {
                            "format": "jpeg",
                            "quality": 40,
                            "maxWidth": 320,
                            "maxHeight": 240,
                        },
                    )
                    clicked = time.monotonic()
                    with page.expect_navigation(wait_until="commit", timeout=60000):
                        page.evaluate(
                            "path => document.querySelector(`nav a.edition-link[href='${path}']`).click()",
                            path,
                        )
                    if network[
                        "asset"
                    ]:  # Past Chromium's paint holding, while the stylesheet still loads.
                        page.wait_for_timeout(600)
                        probe = client.send(
                            "Page.captureScreenshot", {"format": "jpeg", "quality": 40}
                        )["data"]
                        frames.append(probe)
                        (out / f"loading-{path.strip('/')}.jpg").write_bytes(
                            b64decode(probe)
                        )
                    page.evaluate(FCP)
                    page.wait_for_timeout(150)
                    client.send("Page.stopScreencast")
                    result = page.evaluate(TIMING)
                    result["blank_frames"] = sum(map(blank, frames))
                    result["frames"] = len(frames)
                    # Offline refreshes still running when the click came, or started before the new page painted.
                    painted = clicked + (result["fcp"] or 0) / 1000
                    result["refreshes_overlapping"] = sum(
                        1
                        for start, end, _, p, _ in log
                        if p.startswith("/offline/")
                        and start < painted
                        and end > clicked
                    )
                    return result

                def settle():
                    page.wait_for_timeout(
                        2500 + int(network["latency"] * 20000)
                    )  # The previous page's refresh finishes.

                def stop_worker():
                    settle()
                    client.send("ServiceWorker.stopAllWorkers")
                    deadline = time.monotonic() + 5
                    while any(status != "stopped" for status in workers.values()):
                        assert time.monotonic() < deadline, workers
                        page.wait_for_timeout(50)

                def clear_cache():
                    settle()
                    client.send("Network.clearBrowserCache")

                results = {"pages": pages}
                cycle = lambda n: [pages[i % len(pages)] for i in range(n)]
                results["warm"] = [switch(p, settle) for p in cycle(rounds)]
                # A phone's connection: 150 ms before every response.
                network["latency"] = 0.15
                results["phone_idle_worker"] = [
                    switch(p, stop_worker) for p in cycle(rounds)
                ]
                settle()
                results["phone_rapid"] = [switch(p) for p in cycle(rounds * 2)]
                # Right after a deploy: nothing cached and slow stylesheets, scripts and fonts.
                network["asset"] = 0.8
                results["phone_after_deploy"] = [
                    switch(p, clear_cache) for p in cycle(rounds)
                ]
                network.update(latency=0, asset=0)
                settle()
                browser.close()
        finally:
            fixture.terminate()
            fixture.wait()
    report = {"session_check": session_check_cost()}
    for name in ("warm", "phone_idle_worker", "phone_rapid", "phone_after_deploy"):
        runs = results[name]
        report[name] = {key: summary([r[key] for r in runs]) for key in ("ttfb", "fcp")}
        for key in ("blank_frames", "refreshes_overlapping"):
            report[name][key] = sum(r[key] for r in runs)
        report[name]["uncontrolled"] = sum(not r["controlled"] for r in runs)
    report["offline_fetches"] = sum(1 for *_, p, _ in log if p.startswith("/offline/"))
    (out / "page_switch.json").write_text(
        json.dumps({"report": report, "runs": results}, indent=1)
    )
    print(json.dumps(report))


def sign_in(page):
    page.goto(HOST + "/login")
    page.locator("input[name=username]").fill("alice")
    page.locator("#password-password").fill("a1alice-temporary")
    page.locator("#account-form button[type=submit]").click()
    page.get_by_role("heading", name="Change password", exact=True).wait_for()
    page.locator("#site-patch-note").wait_for()
    page.locator("#patch-note-dismiss").click()
    page.locator("#site-patch-note").wait_for(state="hidden")
    page.locator("input[name=current]").fill("a1alice-temporary")
    page.locator("input[name=replacement]").fill("a1alice-permanent")
    page.locator("input[name=repeat]").fill("a1alice-permanent")
    with page.expect_response("**/api/auth/password"):
        page.locator("#account-form button[type=submit]").click()
    page.wait_for_url(lambda url: not url.endswith(("/login", "/password")))


if __name__ == "__main__":
    main()
