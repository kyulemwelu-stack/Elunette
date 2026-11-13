"""Optional Chrome smoke check using generated records, with screenshots in TEMP.

Run from the project root: .venv/Scripts/python.exe tests/browser_smoke.py
"""
import functools
import base64
import http.server
import json
import os
from pathlib import Path
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_workflows import Workflows


CHECK = """<script>
(() => {
    try {
        const card = document.querySelector('.project-brief-card');
        const table = document.querySelector('.client-briefs-table');
        if (document.documentElement.scrollWidth > innerWidth + 1) throw Error('Page overflow');
        if (card && getComputedStyle(card.parentElement).display !== 'grid') throw Error('Missing grid');
        if (table && innerWidth < 600 && table.querySelector('th[scope="row"]')) {
            const region = table.parentElement;
            region.scrollLeft = region.scrollWidth;
            if (region.scrollLeft <= 0) throw Error('Table is not horizontally scrollable');
            region.scrollLeft = 0;
        }
        const progress = document.querySelector('progress');
        if (progress && getComputedStyle(progress).height !== '5px') throw Error('Missing progress style');
        const link = document.querySelector('[data-delete-draft]');
        const dialog = document.getElementById('delete-draft-dialog');
        if (link) {
            link.click();
            if (!dialog.open || !dialog.matches(':modal')) throw Error('Modal did not open');
            if (document.activeElement.textContent.trim() !== 'Keep Draft') throw Error('Unsafe initial focus');
            if (document.getElementById('delete-draft-name').textContent !== link.dataset.briefTitle) throw Error('Wrong title');
            if (document.getElementById('delete-draft-form').action !== link.href) throw Error('Wrong action');
            dialog.querySelector('.cancel-btn').click();
            if (dialog.open) throw Error('Cancel failed');
        }
        document.body.dataset.browserCheck='passed';
        if (location.search.includes('dialog')) link.click();
    } catch(error) {
        document.body.dataset.browserCheck='failed: '+error.message;
    }
})();
</script>"""


class DevTools:
    """Small local CDP client; no browser automation dependencies required."""
    def __init__(self, url):
        address = urlsplit(url)
        self.socket = socket.create_connection((address.hostname, address.port), timeout=20)
        key = base64.b64encode(os.urandom(16)).decode()
        self.socket.sendall((f"GET {address.path} HTTP/1.1\r\nHost: {address.netloc}\r\n"
                             "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                             f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        response = b""
        while not response.endswith(b"\r\n\r\n"):
            response += self.socket.recv(1)
        if b" 101 " not in response:
            raise RuntimeError("DevTools connection failed")
        self.sequence = 0

    def read(self, length):
        data = b""
        while len(data) < length:
            chunk = self.socket.recv(length - len(data))
            if not chunk:
                raise RuntimeError("DevTools closed")
            data += chunk
        return data

    def call(self, method, params=None):
        self.sequence += 1
        payload = json.dumps({"id": self.sequence, "method": method, "params": params or {}}).encode()
        size = len(payload)
        length = bytes([128 | size]) if size < 126 else bytes([128 | 126]) + struct.pack("!H", size) if size < 65536 else bytes([128 | 127]) + struct.pack("!Q", size)
        mask = os.urandom(4)
        self.socket.sendall(b"\x81" + length + mask + bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload)))
        while True:
            opcode, size = self.read(2)
            size &= 127
            if size == 126:
                size = struct.unpack("!H", self.read(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self.read(8))[0]
            data = self.read(size)
            if opcode & 15 == 8:
                raise RuntimeError("DevTools closed")
            result = json.loads(data)
            if result.get("id") == self.sequence:
                if "error" in result:
                    raise RuntimeError(result["error"])
                return result.get("result", {})


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def main():
    chrome = os.environ.get("CHROME_EXECUTABLE") or shutil.which("chrome")
    if not chrome:
        chrome = "C:/Program Files/Google/Chrome/Application/chrome.exe"
    if not Path(chrome).is_file():
        raise SystemExit("Set CHROME_EXECUTABLE to a local Chrome executable.")

    Workflows.setUpClass()
    fixture = Workflows()
    fixture.setUp()
    root = Path(tempfile.mkdtemp(prefix="elunette-style-preview-"))
    server = None
    try:
        shutil.copytree("static", root / "assets")
        fixture.db.execute("UPDATE project_briefs SET title=?,completeness_percentage=65 WHERE id=8",
                           ('Editorial identity & website',))
        fixture.db.execute("UPDATE project_briefs SET status='approved',completeness_percentage=100 WHERE id=7")
        fixture.db.execute("UPDATE project_briefs SET status='under_review',completeness_percentage=100 WHERE id=6")
        fixture.db.commit()
        for name, url in (("dashboard", "/dashboard/client"), ("briefs", "/briefs"), ("empty", "/briefs?search=not-found")):
            html = fixture.client.get(url).get_data(as_text=True).replace("/static/", "/assets/")
            (root / (name + ".html")).write_text(html, encoding="utf-8")
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(root)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        cases = (("dashboard", "1440,1300", ""), ("dashboard-mobile", "390,1000", ""),
                 ("briefs", "1440,1300", ""), ("briefs-mobile", "390,1000", ""),
                 ("dialog", "390,850", "?dialog"), ("empty", "390,950", ""))
        for name, size, query in cases:
            page = "briefs" if name in ("briefs-mobile", "dialog") else "dashboard" if name == "dashboard-mobile" else name
            profile = root / (name + "-profile")
            command = [chrome, "--headless", "--disable-gpu", "--no-first-run",
                       "--no-default-browser-check", "--disable-background-networking",
                       "--disable-extensions", "--remote-debugging-port=0",
                       f"--user-data-dir={profile}", "about:blank"]
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            devtools = None
            try:
                port_file = profile / "DevToolsActivePort"
                for _ in range(100):
                    try:
                        lines = port_file.read_text().splitlines()
                        if lines:
                            port = lines[0]
                            break
                    except OSError:
                        # Chrome briefly holds an exclusive file lock on Windows.
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Chrome did not publish its DevTools port")
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list") as response:
                    target = next(t for t in json.load(response) if t["type"] == "page")
                devtools = DevTools(target["webSocketDebuggerUrl"])
                width, height = map(int, size.split(","))
                devtools.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600})
                devtools.call("Page.navigate", {"url": f"http://127.0.0.1:{server.server_port}/{page}.html{query}"})
                for _ in range(100):
                    ready = devtools.call("Runtime.evaluate", {"expression": "document.readyState === 'complete' && Boolean(document.getElementById('delete-draft-dialog'))"})
                    if ready.get("result", {}).get("value"):
                        break
                    time.sleep(0.1)
                devtools.call("Runtime.evaluate", {"expression": "document.fonts.ready", "awaitPromise": True})
                devtools.call("Runtime.evaluate", {"expression": CHECK.removeprefix("<script>").removesuffix("</script>")})
                result = devtools.call("Runtime.evaluate", {"expression": "document.body.dataset.browserCheck"})
                if result.get("result", {}).get("value") != "passed":
                    raise RuntimeError(f"{name}: {result}")
                actual_width = devtools.call("Runtime.evaluate", {"expression": "innerWidth"})
                if actual_width["result"]["value"] != width:
                    raise RuntimeError("Incorrect browser viewport width")
                if name == "dialog":
                    devtools.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
                    devtools.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
                    result = devtools.call("Runtime.evaluate", {"expression": "!document.getElementById('delete-draft-dialog').open"})
                    if not result["result"]["value"]:
                        raise RuntimeError("Escape did not close modal")
                    devtools.call("Runtime.evaluate", {"expression": "document.querySelector('[data-delete-draft]').click()"})
                else:
                    devtools.call("Runtime.evaluate", {"expression": "new Promise(resolve => setTimeout(() => { scrollTo(0, 0); requestAnimationFrame(() => requestAnimationFrame(resolve)); }, 100))", "awaitPromise": True})
                    if width < 600:
                        section = ".dashboard-briefs" if page == "dashboard" else ".briefs-list-section"
                        devtools.call("Runtime.evaluate", {"expression": f"document.querySelector('{section}').scrollIntoView()"})
                image = devtools.call("Page.captureScreenshot", {"format": "png"})
                (root / (name + ".png")).write_bytes(base64.b64decode(image["data"]))
            finally:
                if devtools:
                    devtools.socket.close()
                process.terminate()
                process.wait(timeout=10)
            print(f"{name}: passed; {root / (name + '.png')}", flush=True)
    finally:
        if server:
            server.shutdown()
            server.server_close()
        fixture.tearDown()
    print(f"Screenshots: {root}")


if __name__ == "__main__":
    main()
