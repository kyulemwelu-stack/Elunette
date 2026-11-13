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

REVIEW_CHECK = """(() => {
    try {
        if (document.documentElement.scrollWidth > innerWidth + 1) throw Error('Page overflow');
        const progress = document.querySelector('.review-progress');
        const recorded = Number(document.querySelector('.review-percentage').textContent.replace('%', ''));
        if (!progress || progress.value !== recorded) throw Error('Progress differs from recorded percentage');
        if (getComputedStyle(progress).accentColor !== 'rgb(163, 177, 138)') throw Error('Progress is not sage');
        for (const card of document.querySelectorAll('.requirement-card')) {
            if (getComputedStyle(card).backgroundColor !== 'rgb(255, 255, 255)') throw Error('Requirement card is not white');
            if (getComputedStyle(card.querySelector('.requirement-answer')).whiteSpace !== 'pre-wrap') throw Error('Answer line breaks lost');
        }
        const forms = document.querySelectorAll('.decision-card form');
        if (forms.length !== 2 || Array.from(forms).some(form => !form.querySelector('[name="csrf_token"]'))) throw Error('Review forms missing CSRF');
        if (!document.getElementById('revision-comments').required) throw Error('Feedback is not required');
        const columns = getComputedStyle(document.querySelector('.decision-container')).gridTemplateColumns.split(' ').length;
        if (columns !== (innerWidth <= 750 ? 1 : 2)) throw Error('Review action grid is not responsive');
        document.body.dataset.browserCheck = 'passed';
    } catch(error) { document.body.dataset.browserCheck = 'failed: ' + error.message; }
})();"""

REVISION_CHECK = """(() => {
    try {
        if (document.documentElement.scrollWidth > innerWidth + 1) throw Error('Page overflow');
        if (document.body.classList.contains('review-page')) {
            const history = document.querySelector('.revision-cycle-history');
            if (!history || !history.textContent.includes('Clarified scope and added milestones.')) throw Error('Provider cannot see the revision response');
            for (const details of history.querySelectorAll('details')) details.open = true;
        } else {
            const form = document.getElementById('client-questionnaire-form');
            const response = document.getElementById('revision-response');
            if (!response || response.value !== 'Clarified scope and added milestones.') throw Error('Saved response was not restored');
            const save = form.querySelector('[formaction$="/answers"]');
            const submit = document.getElementById('submit-brief-button');
            const dialog = document.getElementById('submit-brief-dialog');
            if (save.textContent.trim() !== 'Save Changes' || submit.textContent.trim() !== 'Resubmit for Review') throw Error('Wrong revision actions');
            let sent = null;
            form.addEventListener('submit', event => {
                if (event.defaultPrevented) return;
                event.preventDefault(); // No browser POST requests are sent to the preview server.
                sent = {action: event.submitter.formAction, data: new FormData(form)};
            });
            save.click();
            if (!sent || dialog.open) throw Error('Saving incorrectly requires confirmation');
            sent = null;
            submit.click();
            if (!dialog.open || sent) throw Error('Resubmission bypassed confirmation');
            document.getElementById('cancel-brief-submission').click();
            if (dialog.open || sent) throw Error('Cancellation failed');
            submit.click();
            document.getElementById('confirm-brief-submission').click();
            if (!sent || !sent.action.endsWith('/resubmit') || sent.data.get('confirm_resubmission') !== 'yes') throw Error('Confirmed resubmission missing');
            if (sent.data.get('revision_response') !== response.value || !sent.data.get('revision_review_id')) throw Error('Cycle or response not included');
            if (location.search.includes('dialog')) dialog.showModal();
        }
        document.body.dataset.browserCheck = 'passed';
    } catch(error) { document.body.dataset.browserCheck = 'failed: ' + error.message; }
})();"""

APPROVED_CHECK = """(() => {
    try {
        if (document.documentElement.scrollWidth > innerWidth + 1) throw Error('Page overflow');
        const form = document.getElementById('client-questionnaire-form');
        if (!document.querySelector('.approved-brief-notice').textContent.includes('This project brief has been approved and finalised. Your responses are now available for viewing only.')) throw Error('Missing approved message');
        if (form.querySelector('textarea, select, input[name^="answer_"]') || document.getElementById('check-questionnaire') || document.getElementById('submit-brief-button')) throw Error('Editing control remains');
        const answers = Array.from(form.querySelectorAll('.approved-answer'));
        if (answers.length !== 4 || answers.some(answer => !answer.checkVisibility())) throw Error('Answers are hidden');
        if (!answers.some(answer => answer.textContent === 'Final client answer')) throw Error('Conditional answer was lost');
        if (document.body.textContent.includes('Save your progress anytime')) throw Error('Outdated instructions remain');
        if (!document.body.textContent.includes('Ready to proceed') || !document.querySelector('.revision-cycle-history')) throw Error('Feedback or history missing');
        if (window.browserErrors.length) throw Error(window.browserErrors.join('; '));
        document.body.dataset.browserCheck = 'passed';
    } catch(error) { document.body.dataset.browserCheck = 'failed: ' + error.message; }
})();"""

WELCOME_CHECK = """(() => {
    try {
        if (document.documentElement.scrollWidth > innerWidth + 1) throw Error('Page overflow');
        const title = document.querySelector('.welcome-copy h1');
        if (title.textContent.trim() !== 'Every beautiful idea starts somewhere.') throw Error('Incorrect heading');
        const image = document.querySelector('.welcome-hero-image');
        if (!image.complete || image.naturalWidth !== 1672 || image.naturalHeight !== 941) throw Error('Hero image failed to load');
        const bounds = image.getBoundingClientRect();
        if (Math.abs(bounds.width / bounds.height - 1672 / 941) > 0.01) throw Error('Illustration is distorted');
        const roles = Array.from(document.querySelectorAll('.welcome-role'));
        if (roles.length !== 2 || roles.some(role => role.getBoundingClientRect().height > 56 || role.getBoundingClientRect().width > 260)) throw Error('Oversized or missing role controls');
        if (roles.some(role => role.tabIndex < 0 || !role.href.includes('/login?role='))) throw Error('Role links are not accessible');
        if (window.browserErrors.length) throw Error(window.browserErrors.join('; '));
        document.body.dataset.browserCheck = 'passed';
    } catch(error) { document.body.dataset.browserCheck = 'failed: ' + error.message; }
})();"""

STUDIO_CHECK = """(() => {
    try {
        if (document.documentElement.scrollWidth > innerWidth + 1) throw Error('Page overflow');
        const empty = location.pathname.includes('empty');
        for (const [name, count] of Object.entries(empty ? {total:0,pending:0,approved:0,revision:0} : {total:8,pending:2,approved:2,revision:1})) {
            if (Number(document.getElementById('studio-stat-'+name).textContent) !== count) throw Error('Incorrect '+name+' count');
        }
        if (getComputedStyle(document.querySelector('.studio-bento')).display !== 'grid') throw Error('Missing bento grid');
        if (!empty) {
            const bars = Array.from(document.querySelectorAll('.studio-flow-list progress'));
            if (bars.length !== 5 || bars.reduce((sum, bar) => sum+bar.value, 0) !== 8 || bars.some(bar => bar.max !== 8)) throw Error('Invalid workflow distribution');
            if (!document.querySelector('.studio-attention--active .studio-revision-list a')) throw Error('Revision request is not highlighted');
            if (document.querySelectorAll('.project-brief-card').length !== 6) throw Error('Missing recent projects');
            const link = document.querySelector('[data-delete-draft]');
            const dialog = document.getElementById('delete-draft-dialog');
            link.click();
            if (!dialog.open) throw Error('Draft deletion confirmation failed');
            dialog.querySelector('.cancel-btn').click();
            if (dialog.open) throw Error('Draft deletion cancellation failed');
        } else if (!document.querySelector('.studio-empty-projects') || document.querySelector('.studio-flow-list')) throw Error('Empty state contains fake workflow data');
        const summary = document.querySelector('.studio-account summary');
        summary.click();
        if (!summary.parentElement.open || !summary.parentElement.querySelector('form [name="csrf_token"]')) throw Error('Account controls failed');
        summary.click();
        const rail = document.querySelector('.studio-rail').getBoundingClientRect();
        if (innerWidth < 600 && rail.bottom > innerHeight) throw Error('Mobile navigation is offscreen');
        if (window.browserErrors.length) throw Error(window.browserErrors.join('; '));
        document.body.dataset.browserCheck = 'passed';
    } catch(error) { document.body.dataset.browserCheck = 'failed: ' + error.message; }
})();"""

PROVIDER_STUDIO_CHECK = """(() => {
    try {
        if (document.documentElement.scrollWidth > innerWidth + 1) throw Error('Page overflow');
        const empty = location.pathname.includes('empty');
        const one = location.pathname.includes('one');
        const expected = empty ? {total:0,pending:0,approved:0,revision:0} : one ? {total:1,pending:1,approved:0,revision:0} : {total:5,pending:2,approved:2,revision:1};
        for (const [name, value] of Object.entries(expected)) {
            if (Number(document.getElementById('provider-stat-'+name).textContent) !== value) throw Error('Incorrect '+name+' count');
        }
        if (document.querySelectorAll('.project-brief-card').length !== expected.pending) throw Error('Incorrect review queue');
        if (empty && (!document.querySelector('.studio-empty-projects') || document.querySelector('.studio-flow-list'))) throw Error('Missing honest empty state');
        if (!empty && Array.from(document.querySelectorAll('.studio-flow-list progress')).reduce((sum, bar) => sum+bar.value, 0) !== expected.total) throw Error('Invalid status distribution');
        if (!empty && !one && document.querySelectorAll('.provider-activity-list li').length !== 2) throw Error('Missing real review activity');
        if (document.querySelector('a[href*="/admin"]') || document.querySelector('a[href*="/dashboard/client"]')) throw Error('Incorrect role navigation');
        if (!document.querySelector('a[href="/provider/questionnaires"]')) throw Error('Questionnaire navigation missing');
        const summary = document.querySelector('.studio-account summary');
        summary.click();
        if (!summary.parentElement.open || !summary.parentElement.querySelector('form [name="csrf_token"]')) throw Error('Account controls failed');
        summary.click();
        if (window.browserErrors.length) throw Error(window.browserErrors.join('; '));
        document.body.dataset.browserCheck = 'passed';
    } catch(error) { document.body.dataset.browserCheck = 'failed: ' + error.message; }
})();"""

LIBRARY_CHECK = """(() => {
    try {
        if (document.documentElement.scrollWidth > innerWidth + 1) throw Error('Page overflow');
        const file = location.pathname;
        const expected = file.includes('empty') || file.includes('new') ? 0 : file.includes('filtered') ? 2 : 5;
        const dossiers = Array.from(document.querySelectorAll('.edit-dossier'));
        if (dossiers.length !== expected) throw Error('Incorrect dossier count');
        if (!document.querySelector('.studio-navigation a[aria-current="page"]').href.includes('/provider/briefs')) throw Error('Incorrect active navigation');
        const tabs = document.querySelectorAll('.edit-folder-tabs a');
        if (tabs.length !== 5 || Array.from(tabs).some(tab => tab.tabIndex < 0)) throw Error('Folder navigation is not accessible');
        for (const dossier of dossiers) {
            if (!/^PROJECT FILE [0-9]{3,}$/.test(dossier.querySelector('.edit-file-number').textContent.trim())) throw Error('Incorrect file label');
            if (!dossier.querySelector('.edit-review-action').href.endsWith('/provider/briefs/'+dossier.dataset.briefId+'/review')) throw Error('Database reference changed');
        }
        if (!expected && !document.querySelector('.edit-library-empty')) throw Error('Missing empty state');
        if (window.browserErrors.length) throw Error(window.browserErrors.join('; '));
        document.body.dataset.browserCheck = 'passed';
    } catch(error) { document.body.dataset.browserCheck = 'failed: ' + error.message; }
})();"""

ATELIER_FOOTER_CHECK = """(() => {
    try {
        if (document.documentElement.scrollWidth > innerWidth + 1) throw Error('Page overflow');
        const footers = document.querySelectorAll('footer.signature-footer');
        if (footers.length !== 1 || document.querySelector('footer.studio-footer, footer.dashboard-footer')) throw Error('Missing or duplicated site footer');
        const footer = footers[0];
        if (getComputedStyle(footer).backgroundColor !== 'rgb(92, 58, 38)' || getComputedStyle(footer).position !== 'static') throw Error('Incorrect footer styling');
        if (footer.querySelector('.signature-footer-wordmark').textContent !== 'elunette.') throw Error('Wordmark changed');
        if (footer.querySelectorAll('nav a').length !== 2) throw Error('Unexpected footer links');
        if (document.body.classList.contains('atelier-page')) {
            const expected = location.pathname.includes('empty') ? 0 : location.pathname.includes('filtered') ? 2 : 4;
            const cards = document.querySelectorAll('.atelier-card');
            if (cards.length !== expected) throw Error('Incorrect questionnaire count');
            if (document.querySelector('.atelier-grid .studio-paper-art')) throw Error('Decorative artwork inside a card');
            const columns = getComputedStyle(document.querySelector('.atelier-grid') || document.querySelector('.atelier-empty')).gridTemplateColumns.split(' ').length;
            if (expected && columns !== (innerWidth > 1250 ? 3 : innerWidth > 600 ? 2 : 1)) throw Error('Incorrect responsive card columns');
            for (const form of document.querySelectorAll('.atelier-card form')) {
                if (form.method !== 'post' || !form.querySelector('[name="csrf_token"]')) throw Error('Questionnaire action lost CSRF');
            }
            if (!document.querySelector('.studio-navigation [aria-current="page"]').href.endsWith('/provider/questionnaires')) throw Error('Wrong active navigation');
        }
        if (window.browserErrors.length) throw Error(window.browserErrors.join('; '));
        document.body.dataset.browserCheck = 'passed';
    } catch(error) { document.body.dataset.browserCheck = 'failed: ' + error.message; }
})();"""


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

    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):
            # Headless Chrome may close a speculative connection at shutdown.
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
        review_only = "--review-only" in sys.argv
        revision_only = "--revision-only" in sys.argv
        approved_only = "--approved-only" in sys.argv
        welcome_only = "--welcome-only" in sys.argv
        studio_only = "--studio-only" in sys.argv
        provider_studio_only = "--provider-studio-only" in sys.argv
        library_only = "--library-only" in sys.argv
        atelier_only = "--atelier-only" in sys.argv
        if atelier_only:
            fixture.prepare_atelier()
            fixture.db.execute("UPDATE questionnaires SET title='Project foundations',description='A thoughtful starting point for project vision, scope and priorities.' WHERE id=1")
            for qid, title, description, status in ((3,'Brand voice','Explore your story, audience and the way your brand speaks.','inactive'), (4,'Digital presence','Define a clear direction for your next digital experience.','active')):
                fixture.db.execute('INSERT INTO questionnaires (id,title,description,created_by,status) VALUES (?,?,?,2,?)', (qid,title,description,status))
                fixture.db.execute('INSERT INTO questionnaire_versions (id,questionnaire_id,version_number) VALUES (?,?,1)', (qid,qid))
                fixture.db.execute("INSERT INTO questions (id,questionnaire_version_id,question_text,question_type,position) VALUES (?,?,'Your project direction','text',1)", (qid+4,qid))
                if status == 'active':
                    fixture.db.execute('INSERT INTO questionnaire_publications (questionnaire_id,questionnaire_version_id,title_snapshot,description_snapshot) VALUES (?,?,?,?)', (qid,qid,title,description))
            fixture.db.execute("UPDATE project_briefs SET status='submitted',completeness_percentage=100 WHERE id=1")
            fixture.db.commit()
            provider_pages = (('atelier','/provider/questionnaires'), ('atelier-filtered','/provider/questionnaires?search=Brand&status=inactive'), ('atelier-empty','/provider/questionnaires?search=no-match'), ('footer-provider','/dashboard/provider'), ('footer-library','/provider/briefs'), ('footer-notifications','/notifications'), ('footer-review','/provider/briefs/1/review'))
            for name,url in provider_pages:
                html=fixture.client.get(url).get_data(as_text=True).replace('/static/','/assets/')
                (root/(name+'.html')).write_text(html,encoding='utf-8')
            fixture.login(1)
            for name,url in (('footer-client','/dashboard/client'), ('footer-briefs','/briefs'), ('footer-questionnaire','/client/questionnaires/1?brief_id=2')):
                html=fixture.client.get(url).get_data(as_text=True).replace('/static/','/assets/')
                (root/(name+'.html')).write_text(html,encoding='utf-8')
            fixture.login(2)
        if provider_studio_only or library_only:
            fixture.db.execute("UPDATE users SET full_name='Iris Njeri' WHERE id=2")
            fixture.db.commit()
            _, provider = fixture.start_revision(brief_id=4, feedback='Please clarify the scope.')
            fixture.post('/briefs/3/submit', {'save_answers':'1', 'answer_1':'No'})
            fixture.post('/provider/briefs/3/review', {'decision':'approve'}, client=provider)
            fixture.post('/briefs/5/submit', {'save_answers':'1', 'answer_1':'No'})
            fixture.login(2)
            html = fixture.client.get('/dashboard/provider').get_data(as_text=True).replace('/static/', '/assets/')
            (root / 'provider-studio.html').write_text(html, encoding='utf-8')
            fixture.login(4)
            html = fixture.client.get('/dashboard/provider').get_data(as_text=True).replace('/static/', '/assets/')
            (root / 'provider-studio-empty.html').write_text(html, encoding='utf-8')
            if library_only:
                html = fixture.client.get('/provider/briefs').get_data(as_text=True).replace('/static/', '/assets/')
                (root / 'library-new.html').write_text(html, encoding='utf-8')
            fixture.db.execute("INSERT INTO questionnaires (id,title,description,created_by,status) VALUES (2,'Creative direction','Tell us about your idea.',4,'active')")
            fixture.db.execute("INSERT INTO questionnaire_versions (id,questionnaire_id,version_number) VALUES (2,2,1)")
            fixture.db.execute("INSERT INTO questions (id,questionnaire_version_id,question_text,question_type,position) VALUES (5,2,'Your project vision','text',1)")
            fixture.db.execute("INSERT INTO questionnaire_publications (questionnaire_id,questionnaire_version_id,title_snapshot,description_snapshot) VALUES (2,2,'Creative direction','Your project vision')")
            fixture.db.execute("INSERT INTO project_briefs (id,client_id,questionnaire_version_id,title,status,completeness_percentage) VALUES (9,3,2,'A thoughtful new identity','submitted',100)")
            fixture.db.execute("INSERT INTO brief_responses (brief_id,question_id,answer_text) VALUES (9,5,'A refreshed creative identity.')")
            fixture.db.commit()
            html = fixture.client.get('/dashboard/provider').get_data(as_text=True).replace('/static/', '/assets/')
            (root / 'provider-studio-one.html').write_text(html, encoding='utf-8')
            if library_only:
                fixture.login(2)
                for name, query in (('library', ''), ('library-filtered', '?search=Project&status=approved'),
                                    ('library-empty', '?search=no-such-client')):
                    html = fixture.client.get('/provider/briefs'+query).get_data(as_text=True).replace('/static/', '/assets/')
                    (root / (name+'.html')).write_text(html, encoding='utf-8')
        if studio_only:
            fixture.db.execute("UPDATE users SET full_name='Amara Mwangi' WHERE id=1")
            fixture.db.execute("UPDATE project_briefs SET status='submitted',completeness_percentage=100 WHERE id=4")
            fixture.db.execute("UPDATE project_briefs SET status='approved',completeness_percentage=100 WHERE id=3")
            fixture.db.commit()
            fixture.start_revision(brief_id=5, feedback="Please clarify the project scope.")
            html = fixture.client.get('/dashboard/client').get_data(as_text=True).replace('/static/', '/assets/')
            (root / 'studio.html').write_text(html, encoding='utf-8')
            fixture.login(3)
            html = fixture.client.get('/dashboard/client').get_data(as_text=True).replace('/static/', '/assets/')
            (root / 'studio-empty.html').write_text(html, encoding='utf-8')
        if welcome_only:
            html = fixture.client.get("/").get_data(as_text=True).replace("/static/", "/assets/")
            (root / "welcome.html").write_text(html, encoding="utf-8")
        if approved_only:
            fixture.approved_revision()
            # A legacy conditional answer remains visible even if its source changed.
            fixture.db.execute("UPDATE brief_responses SET answer_text='No' WHERE brief_id=1 AND question_id=1")
            fixture.db.commit()
            html = fixture.client.get("/client/questionnaires/1?brief_id=1").get_data(as_text=True).replace("/static/", "/assets/")
            (root / "approved.html").write_text(html, encoding="utf-8")
        if revision_only:
            review_id, provider = fixture.start_revision(feedback="Please clarify the scope and include key milestones.")
            data = {"revision_review_id": str(review_id), "revision_response": "Clarified scope and added milestones.", "answer_2": "Revised project scope with clear milestones."}
            fixture.post("/briefs/1/answers", data)
            html = fixture.client.get("/client/questionnaires/1?brief_id=1").get_data(as_text=True).replace("/static/", "/assets/")
            (root / "revision.html").write_text(html, encoding="utf-8")
            fixture.post("/briefs/1/resubmit", dict(data, confirm_resubmission="yes"))
            html = provider.get("/provider/briefs/1/review").get_data(as_text=True).replace("/static/", "/assets/")
            (root / "revision-provider.html").write_text(html, encoding="utf-8")
        if review_only:
            fixture.db.execute("UPDATE project_briefs SET status='submitted',completeness_percentage=65 WHERE id=1")
            fixture.db.execute("UPDATE project_briefs SET status='submitted',completeness_percentage=25 WHERE id=2")
            fixture.db.execute("INSERT INTO brief_responses (brief_id,question_id,answer_text) VALUES (1,1,'Yes')")
            fixture.db.execute("INSERT INTO brief_responses (brief_id,question_id,answer_text) VALUES (1,2,?)",
                               ("A thoughtful editorial identity and accessible website.\nInclude a clear project timeline and a welcoming client experience.",))
            fixture.db.execute("INSERT INTO brief_reviews (brief_id,reviewer_id,decision,comment) VALUES (1,2,'revision_requested',?)",
                               ("Please clarify the scope.\nInclude the key milestones and launch date.",))
            fixture.db.execute("INSERT INTO brief_reviews (brief_id,reviewer_id,decision,comment) VALUES (1,2,'revision_requested','Add the project deliverables.')")
            fixture.db.commit()
            fixture.login(2)
            for name, brief_id in (("review", 1), ("review-empty", 2)):
                html = fixture.client.get(f"/provider/briefs/{brief_id}/review").get_data(as_text=True).replace("/static/", "/assets/")
                (root / (name + ".html")).write_text(html, encoding="utf-8")
        class PreviewHandler(QuietHandler):
            def do_GET(self):
                if (library_only and urlsplit(self.path).path == '/provider/briefs') or (atelier_only and urlsplit(self.path).path == '/provider/questionnaires'):
                    # Exercise real GET filtering against the temporary Flask fixture.
                    response = fixture.client.get(self.path)
                    content = response.get_data(as_text=True).replace('/static/', '/assets/').encode('utf-8')
                    self.send_response(response.status_code)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Content-Length', str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                else:
                    super().do_GET()
        server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(PreviewHandler, directory=str(root)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        cases = (("dashboard", "1440,1300", ""), ("dashboard-mobile", "390,1000", ""),
                 ("briefs", "1440,1300", ""), ("briefs-mobile", "390,1000", ""),
                 ("dialog", "390,850", "?dialog"), ("empty", "390,950", ""))
        if review_only:
            cases = (("review", "1440,1500", ""), ("review-mobile", "390,1200", ""),
                     ("review-empty", "1440,1300", ""), ("review-empty-mobile", "390,1200", ""))
        if revision_only:
            cases = (("revision", "1440,1200", ""), ("revision-mobile", "390,1100", ""),
                     ("revision-dialog", "390,900", "?dialog"), ("revision-provider", "1440,1400", ""),
                     ("revision-provider-mobile", "390,1200", ""))
        if approved_only:
            cases = (("approved", "1440,1400", ""), ("approved-mobile", "390,1200", ""))
        if welcome_only:
            cases = (("welcome", "1440,1100", ""), ("welcome-tablet", "820,1180", ""),
                     ("welcome-mobile", "390,1150", ""), ("welcome-small", "320,1100", ""))
        if studio_only:
            cases = (("studio", "1440,1400", ""), ("studio-tablet", "820,1400", ""),
                     ("studio-mobile", "390,1300", ""), ("studio-small", "320,1200", ""),
                     ("studio-empty", "1440,1300", ""), ("studio-empty-mobile", "390,1300", ""))
        if provider_studio_only:
            cases = (("provider-studio", "1440,1450", ""), ("provider-studio-tablet", "820,1400", ""),
                     ("provider-studio-mobile", "390,1300", ""), ("provider-studio-small", "320,1300", ""),
                     ("provider-studio-empty", "1440,1300", ""), ("provider-studio-empty-mobile", "390,1300", ""),
                     ("provider-studio-one", "1440,1400", ""))
        if library_only:
            cases = (('library', '1440,1500', ''), ('library-tablet', '820,1400', ''),
                     ('library-mobile', '390,1400', ''), ('library-small', '320,1400', ''),
                     ('library-filtered', '1440,1400', ''), ('library-empty', '390,1200', ''),
                     ('library-new', '1440,1300', ''))
        if atelier_only:
            cases = (('atelier','1440,1300',''), ('atelier-tablet','820,1400',''), ('atelier-mobile','390,1400',''),
                     ('atelier-small','320,1300',''), ('atelier-filtered','1440,1200',''), ('atelier-empty','390,1200',''),
                     ('footer-client','1440,1500',''), ('footer-provider','390,1400',''), ('footer-library','1440,1400',''),
                     ('footer-notifications','390,1400',''), ('footer-briefs','390,1400',''), ('footer-questionnaire','390,1400',''),
                     ('footer-review','390,1400',''))
        for name, size, query in cases:
            page = "briefs" if name in ("briefs-mobile", "dialog") else "dashboard" if name == "dashboard-mobile" else name
            if review_only:
                page = name.removesuffix("-mobile")
            if revision_only:
                page = "revision" if name == "revision-dialog" else name.removesuffix("-mobile")
            if approved_only:
                page = "approved"
            if welcome_only:
                page = "welcome"
            if studio_only:
                page = "studio-empty" if 'empty' in name else "studio"
            if provider_studio_only:
                page = 'provider-studio-empty' if 'empty' in name else 'provider-studio-one' if 'one' in name else 'provider-studio'
            if library_only:
                page = name if name in ('library-filtered', 'library-empty', 'library-new') else 'library'
            if atelier_only:
                page = 'atelier' if name in ('atelier-tablet','atelier-mobile','atelier-small') else name
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
                devtools.call("Page.enable")
                devtools.call("Page.addScriptToEvaluateOnNewDocument", {"source": "window.browserErrors = []; window.addEventListener('error', event => window.browserErrors.push(event.message));"})
                width, height = map(int, size.split(","))
                devtools.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": width < 600})
                devtools.call("Page.navigate", {"url": f"http://127.0.0.1:{server.server_port}/{page}.html{query}"})
                for _ in range(100):
                    selector = ".signature-footer" if atelier_only else ".edit-library" if library_only else ".studio-bento" if studio_only or provider_studio_only else ".welcome-hero-image" if welcome_only else ".approved-brief-notice" if approved_only else ".revision-cycle-history" if revision_only and "provider" in name else "#revision-response" if revision_only else ".review-progress" if review_only else "#delete-draft-dialog"
                    ready = devtools.call("Runtime.evaluate", {"expression": f"document.readyState === 'complete' && Boolean(document.querySelector('{selector}'))"})
                    if ready.get("result", {}).get("value"):
                        break
                    time.sleep(0.1)
                devtools.call("Runtime.evaluate", {"expression": "document.fonts.ready", "awaitPromise": True})
                devtools.call("Runtime.evaluate", {"expression": ATELIER_FOOTER_CHECK if atelier_only else LIBRARY_CHECK if library_only else PROVIDER_STUDIO_CHECK if provider_studio_only else STUDIO_CHECK if studio_only else WELCOME_CHECK if welcome_only else APPROVED_CHECK if approved_only else REVISION_CHECK if revision_only else REVIEW_CHECK if review_only else CHECK.removeprefix("<script>").removesuffix("</script>")})
                result = devtools.call("Runtime.evaluate", {"expression": "document.body.dataset.browserCheck"})
                if result.get("result", {}).get("value") != "passed":
                    raise RuntimeError(f"{name}: {result}")
                actual_width = devtools.call("Runtime.evaluate", {"expression": "innerWidth"})
                if actual_width["result"]["value"] != width:
                    raise RuntimeError("Incorrect browser viewport width")
                if welcome_only:
                    reached = set()
                    for _ in range(16):
                        devtools.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9})
                        devtools.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Tab", "code": "Tab", "windowsVirtualKeyCode": 9})
                        active = devtools.call("Runtime.evaluate", {"expression": "document.activeElement.textContent.trim()"})
                        reached.add(active.get("result", {}).get("value"))
                    if not all(any(label in (text or '') for text in reached) for label in ("Continue as Client", "Continue as Provider", "Administrator access")):
                        raise RuntimeError("Keyboard navigation could not reach all access options")
                    devtools.call("Runtime.evaluate", {"expression": "document.activeElement.blur()"})
                if name == "dialog":
                    devtools.call("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
                    devtools.call("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
                    result = devtools.call("Runtime.evaluate", {"expression": "!document.getElementById('delete-draft-dialog').open"})
                    if not result["result"]["value"]:
                        raise RuntimeError("Escape did not close modal")
                    devtools.call("Runtime.evaluate", {"expression": "document.querySelector('[data-delete-draft]').click()"})
                elif name != "revision-dialog":
                    devtools.call("Runtime.evaluate", {"expression": "new Promise(resolve => setTimeout(() => { scrollTo(0, 0); requestAnimationFrame(() => requestAnimationFrame(resolve)); }, 100))", "awaitPromise": True})
                    if (width < 600 or review_only or revision_only) and not welcome_only and not studio_only and not provider_studio_only and not library_only and not atelier_only:
                        section = ".approved-brief-notice" if approved_only else ".revision-cycle-history" if revision_only and "provider" in name else ".revision-response-card" if revision_only else ".review-requirements" if review_only else ".dashboard-briefs" if page == "dashboard" else ".briefs-list-section"
                        devtools.call("Runtime.evaluate", {"expression": f"document.querySelector('{section}').scrollIntoView()"})
                image = devtools.call("Page.captureScreenshot", {"format": "png"})
                (root / (name + ".png")).write_bytes(base64.b64decode(image["data"]))
                if atelier_only:
                    devtools.call('Runtime.evaluate', {'expression': "scrollTo(0, document.documentElement.scrollHeight)"})
                    time.sleep(.1)
                    check = devtools.call('Runtime.evaluate', {'expression': "(() => { const footer=document.querySelector('.signature-footer').getBoundingClientRect(); const rail=document.querySelector('.studio-rail')?.getBoundingClientRect(); return !rail || (innerWidth > 600 ? footer.left >= rail.right : footer.bottom <= rail.top); })()"})
                    if not check.get('result', {}).get('value'):
                        raise RuntimeError('Footer overlaps the Studio navigation rail')
                    image = devtools.call('Page.captureScreenshot', {'format':'png'})
                    (root/(name+'-footer.png')).write_bytes(base64.b64decode(image['data']))
                if library_only and name == 'library':
                    devtools.call('Runtime.evaluate', {'expression': "document.querySelector('.edit-folder-tabs a[href*=\"status=approved\"]').focus()"})
                    devtools.call('Input.dispatchKeyEvent', {'type':'keyDown', 'key':'Enter', 'code':'Enter', 'windowsVirtualKeyCode':13, 'text':'\r'})
                    devtools.call('Input.dispatchKeyEvent', {'type':'keyUp', 'key':'Enter', 'code':'Enter', 'windowsVirtualKeyCode':13})
                    for _ in range(100):
                        result = devtools.call('Runtime.evaluate', {'expression': "document.readyState === 'complete' && document.querySelector('input[name=\"status\"]')?.value === 'approved' && document.querySelectorAll('.edit-dossier').length === 2"})
                        if result.get('result', {}).get('value'):
                            break
                        time.sleep(.1)
                    else:
                        raise RuntimeError('Live folder filter failed')
                    devtools.call('Runtime.evaluate', {'expression': "document.getElementById('library-search').value = 'Project 3'; document.getElementById('library-search').focus()"})
                    devtools.call('Input.dispatchKeyEvent', {'type':'keyDown', 'key':'Enter', 'code':'Enter', 'windowsVirtualKeyCode':13, 'text':'\r'})
                    devtools.call('Input.dispatchKeyEvent', {'type':'keyUp', 'key':'Enter', 'code':'Enter', 'windowsVirtualKeyCode':13})
                    for _ in range(100):
                        result = devtools.call('Runtime.evaluate', {'expression': "document.readyState === 'complete' && document.querySelectorAll('.edit-dossier').length === 1 && document.querySelector('.edit-dossier')?.dataset.briefId === '3'"})
                        if result.get('result', {}).get('value'):
                            break
                        time.sleep(.1)
                    else:
                        raise RuntimeError('Live search within the selected folder failed')
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
