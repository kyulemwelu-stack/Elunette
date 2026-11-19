"""Responsive smoke check of live routes backed by disposable fixtures."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_smoke import DevTools
from test_adaptive import complete
from test_workflows import Workflows, app
from werkzeug.serving import make_server, WSGIRequestHandler


class QuietRequests(WSGIRequestHandler):
    def log_request(self, code="-", size="-"):
        pass


def fixture_pages(fixture, root):
    app.config["ADAPTIVE_UPLOAD_ROOT"] = str(root / "uploads")
    fixture.prepare_atelier()
    sessions = {role: app.test_client() for role in ("public", "client", "provider", "admin")}
    for role, user_id in (("client", 1), ("provider", 2), ("admin", 5)):
        fixture.login(user_id, sessions[role])
    client, provider = sessions["client"], sessions["provider"]
    fixture.post("/briefs/1/submit", {"save_answers":"1", "answer_1":"No"}, client)
    fixture.post("/provider/briefs/1/review", {
        "decision":"request_revision", "revision_comments":"Clarify the main message.",
    }, provider)
    pages = {
        "public": ["/", "/about", "/login", "/login?role=service_provider", "/login?role=administrator",
                   "/register", "/register?role=service_provider", "/forgot-password", "/reset-password-preview"],
        "client": ["/dashboard/client", "/briefs", "/briefs/new", "/briefs/new?provider_id=2",
                   "/briefs/2/delete", "/client/questionnaires/1?brief_id=1", "/notifications", "/notifications?view=unread",
                   "/client/adaptive/new", "/questionnaire-preview", "/brief-preview",
                   "/brief-details-preview", "/revision-history-preview"],
        "provider": ["/dashboard/provider", "/provider/briefs", "/provider/briefs/1/review",
                     "/provider/questionnaires", "/provider/questionnaires/new", "/provider/questionnaires/1/edit",
                     "/provider/questionnaires/2/rules", "/provider/questionnaires/2/questions/5/edit",
                     "/provider/briefs/review-preview", "/notifications", "/notifications?view=unread"],
        "admin": ["/dashboard/admin", "/admin/users", "/admin/users/new", "/admin/users/edit-preview", "/notifications"],
    }
    for service in ("posters_flyers", "logo_branding", "websites_applications", "social_media_design",
                    "events_invitations", "brochures_menus", "packaging_design"):
        def make_draft():
            created = fixture.post("/client/adaptive/new", {
                "META01":"Audit project", "META02":service, "provider_id":2,
            }, client)
            wizard = created.location
            saved = client.post(wizard + "/save", json={
                "generation":0, "answers":complete(service), "revision_response":"",
            }, headers={"X-CSRFToken":fixture.token(client)})
            assert saved.status_code == 200, (service, saved.json)
            return wizard

        draft = make_draft()
        pages["client"] += [draft, draft + "/review"]
        wizard = make_draft()
        submitted = fixture.post(wizard + "/submit", {"generation":1, "confirm":"yes"}, client)
        assert submitted.status_code == 302, (service, submitted.status_code)
        if service == "posters_flyers":
            pages["client"].append(submitted.location)
            bid = wizard.split("/")[-2]
            revised = fixture.post(f"/provider/briefs/{bid}/adaptive", {
                "decision":"revision_requested", "comment":"Please clarify the intended audience.",
            }, provider)
            assert revised.status_code == 302
            pages["client"] += [wizard, wizard + "/review"]
        bid = wizard.split("/")[-2]
        pages["provider"].append(f"/provider/briefs/{bid}/review")
    return sessions, pages


LAYOUT = """(width => {
    const issues = [];
    if (document.documentElement.scrollWidth > width + 2) {
        const edges = [...document.querySelectorAll('main *, header *, nav *')].filter(node =>
            node.getClientRects().length && node.getBoundingClientRect().right > width + 2 &&
            !node.closest('svg, [aria-hidden=true], .adaptive-sr-only')).slice(0, 5);
        issues.push('page overflow ' + document.documentElement.scrollWidth + '/' + width + ' ' +
            edges.map(node => node.tagName + '.' + node.className).join(', '));
    }
    for (const image of document.images) {
        if (image.complete && !image.naturalWidth) issues.push('broken image ' + image.getAttribute('src'));
    }
    for (const link of document.querySelectorAll('a[href^="#"]')) {
        if (link.hash && !document.getElementById(decodeURIComponent(link.hash.slice(1))))
            issues.push('missing anchor ' + link.hash);
    }
    if (!document.querySelector('main')) issues.push('missing main landmark');
    if (!document.querySelector('h1')) issues.push('missing page heading');
    if (!location.pathname.endsWith('-preview')) {
        for (const control of document.querySelectorAll('input:not([type=hidden]), select, textarea')) {
            if (control.getClientRects().length && !control.closest('[aria-hidden=true]') &&
                !control.labels?.length && !control.hasAttribute('aria-label') && !control.hasAttribute('aria-labelledby')) {
                issues.push('form control missing accessible name: ' + (control.id || control.name || control.type));
            }
        }
    }
    if (document.body.classList.contains('about-page')) {
        const columns = getComputedStyle(document.querySelector('.about-stage')).gridTemplateColumns.split(' ').length;
        if (columns !== (innerWidth <= 768 ? 1 : 2)) issues.push('About hero does not reflow');
    }
    if (!location.pathname.endsWith('-preview')) {
        for (const link of document.querySelectorAll('a[href]')) {
            if (link.origin === location.origin && link.pathname.endsWith('-preview')) issues.push('workspace link uses preview ' + link.pathname);
        }
    }
    return [...issues, ...window.auditErrors];
})"""


def main():
    chrome = os.environ.get("CHROME_EXECUTABLE", "C:/Program Files/Google/Chrome/Application/chrome.exe")
    Workflows.setUpClass()
    fixture = Workflows()
    fixture.setUp()
    root = Path(fixture.directory.name)
    sessions, pages = fixture_pages(fixture, root)
    server = make_server("127.0.0.1", 0, app, threaded=True, request_handler=QuietRequests)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    process = subprocess.Popen([
        chrome, "--headless", "--disable-gpu", "--no-first-run", "--disable-background-networking",
        "--remote-debugging-port=0", f"--user-data-dir={root / 'chrome'}", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    dev = None
    try:
        for _ in range(100):
            try:
                port = (root / "chrome" / "DevToolsActivePort").read_text().splitlines()[0]
                with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as response:
                    target = next(item for item in json.load(response) if item["type"] == "page")
                break
            except (OSError, IndexError, StopIteration):
                time.sleep(.1)
        else:
            raise RuntimeError("Chrome did not expose DevTools")
        dev = DevTools(target["webSocketDebuggerUrl"])
        dev.call("Page.enable")
        dev.call("Network.enable")
        dev.call("Network.setBlockedURLs", {"urls":["*fonts.googleapis.com*", "*fonts.gstatic.com*"]})
        dev.call("Page.addScriptToEvaluateOnNewDocument", {"source":
            "window.auditErrors=[];addEventListener('error',e=>auditErrors.push(e.message));"
            "addEventListener('unhandledrejection',e=>auditErrors.push(String(e.reason)));"})

        def evaluate(expression):
            result = dev.call("Runtime.evaluate", {"expression":expression, "returnByValue":True})
            if "exceptionDetails" in result:
                raise RuntimeError(result["exceptionDetails"])
            return result["result"].get("value")

        failures = []
        for role, paths in pages.items():
            dev.call("Network.deleteCookies", {"name":"session", "url":origin})
            cookie = sessions[role].get_cookie("session")
            if cookie:
                dev.call("Network.setCookie", {"name":"session", "value":cookie.value, "url":origin})
            for path in paths:
                response = sessions[role].get(path)
                if response.status_code != 200:
                    failures.append(f"{role} {path} returned HTTP {response.status_code}")
                    continue
                for width in (360, 768, 1366, 1920):
                    dev.call("Emulation.setDeviceMetricsOverride", {
                        "width":width, "height":900, "deviceScaleFactor":1, "mobile":width < 600,
                    })
                    dev.call("Page.navigate", {"url":origin + path})
                    for _ in range(100):
                        if evaluate(f"location.href==={json.dumps(origin + path)} && document.readyState==='complete'"):
                            break
                        time.sleep(.05)
                    else:
                        failures.append(f"{role} {path} {width}px did not load ({evaluate('location.pathname')})")
                        continue
                    failures.extend(f"{role} {path} {width}px {issue}" for issue in set(evaluate(f"{LAYOUT}({width})")))
            print(f"{role}: {len(paths)} pages checked at four widths", flush=True)
        if failures:
            raise SystemExit("\n".join(failures))
        print(f"{sum(map(len, pages.values())) * 4} browser renders passed", flush=True)
    finally:
        if dev:
            dev.socket.close()
        process.terminate()
        process.wait(timeout=10)
        server.shutdown()
        server.server_close()
        fixture.tearDown()


if __name__ == "__main__":
    main()
