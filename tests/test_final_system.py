"""Final acceptance checks on disposable accounts, files and SQLite databases."""
from concurrent.futures import ThreadPoolExecutor
import io
from pathlib import Path
import sqlite3
from threading import Barrier
import time
import unittest
from unittest.mock import patch

from werkzeug.security import check_password_hash

from database import get_db
from test_adaptive import complete
import test_workflows


app = test_workflows.app


class FinalSystem(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_workflows.Workflows.setUpClass()

    def setUp(self):
        self.fixture = test_workflows.Workflows()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.addCleanup(app.config.update, ADAPTIVE_UPLOAD_ROOT=app.config["ADAPTIVE_UPLOAD_ROOT"])
        app.config["ADAPTIVE_UPLOAD_ROOT"] = str(Path(self.fixture.directory.name) / "uploads")
        self.db = self.fixture.db
        self.post = self.fixture.post
        self.token = self.fixture.token

    def create_draft(self, client, provider_id=2, title="Stage 5 fixture"):
        response = self.post("/client/adaptive/new", {
            "META01": title, "META02": "logo_branding", "provider_id": provider_id,
        }, client)
        self.assertEqual(response.status_code, 302)
        return response.location, int(response.location.split("/")[-2])

    def save(self, client, wizard, answers, generation, revision_response=""):
        return client.post(wizard + "/save", json={
            "answers": answers, "generation": generation, "revision_response": revision_response,
        }, headers={"X-CSRFToken": self.token(client)})

    def test_registered_accounts_complete_full_adaptive_handoff(self):
        browsers = []
        for role in ("client", "service_provider"):
            browser = app.test_client()
            email = f"{role}@stage5.example.test"
            credentials = {"email": email, "password": "Stage5-fixture-password"}
            response = self.post(f"/register?role={role}", {
                **credentials, "full_name": f"Stage 5 {role.title()}",
                "confirm_password": credentials["password"],
            }, browser)
            self.assertEqual(response.status_code, 302)
            account = self.db.execute("SELECT id,password_hash,role FROM users WHERE email=?", (email,)).fetchone()
            self.assertEqual(account["role"], role)
            self.assertNotEqual(account["password_hash"], credentials["password"])
            self.assertTrue(check_password_hash(account["password_hash"], credentials["password"]))
            self.assertEqual(self.post("/login", credentials, browser).status_code, 302)
            browsers.append((browser, account["id"]))

        (client, client_id), (designer, designer_id) = browsers
        wizard, brief_id = self.create_draft(client, designer_id)
        answers = complete("logo_branding", {"META01": "Stage 5 brand brief"})
        saved = self.save(client, wizard, answers, 0)
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(saved.json["assessment"]["percentage"], 100)
        self.assertIn(b'Stage 5 brand brief', client.get(wizard + "/review").data)
        submit = {"confirm": "yes", "generation": 1}
        self.assertEqual(self.post(wizard + "/submit", submit, client).status_code, 302)
        review = f"/provider/briefs/{brief_id}/review"
        self.assertIn(b'Stage 5 brand brief', designer.get(review).data)
        first_id = self.db.execute("SELECT id FROM adaptive_submissions WHERE brief_id=?", (brief_id,)).fetchone()[0]
        decision = review.replace("/review", "/adaptive")
        self.assertEqual(self.post(decision, {
            "decision":"revision_requested", "comment":"Clarify where the logo will be used.",
            "submission_id": first_id,
        }, designer).status_code, 302)
        self.assertIn(b'Revision requested', client.get("/notifications").data)
        saved = self.save(client, wizard, {"LB04": "Revised design context"}, 2, "Added usage context.")
        self.assertEqual(saved.status_code, 200, saved.json)
        self.assertEqual(self.post(wizard + "/submit", dict(submit, generation=3), client).status_code, 302)
        latest_id = self.db.execute(
            "SELECT id FROM adaptive_submissions WHERE brief_id=? ORDER BY revision_number DESC", (brief_id,),
        ).fetchone()[0]
        self.assertEqual(self.post(decision, {
            "decision":"approved", "submission_id": latest_id,
        }, designer).status_code, 302)
        self.assertIn(b'id="studio-stat-approved">1', client.get("/dashboard/client").data)
        self.assertIn(b'id="provider-stat-approved">1', designer.get("/dashboard/provider").data)
        self.assertIn(b'Brief approved', client.get("/notifications").data)
        self.assertIn(b'Revised brief submitted', designer.get("/notifications").data)

        self.assertEqual([tuple(row) for row in self.db.execute(
            "SELECT event_type,recipient_id FROM notifications WHERE brief_id=? ORDER BY id", (brief_id,),
        )], [("submitted", designer_id), ("revision_requested", client_id),
             ("resubmitted", designer_id), ("approved", client_id)])
        self.assertEqual([tuple(row) for row in self.db.execute(
            "SELECT decision,reviewer_id FROM brief_reviews WHERE brief_id=? ORDER BY id", (brief_id,),
        )], [("revision_requested", designer_id), ("approved", designer_id)])
        self.assertEqual([tuple(row) for row in self.db.execute(
            "SELECT revision_number,actor_id FROM adaptive_submissions WHERE brief_id=? ORDER BY revision_number", (brief_id,),
        )], [(1, client_id), (2, client_id)])
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_concurrent_draft_saves_and_submissions_are_serialized(self):
        clients = [app.test_client(), app.test_client()]
        for client in clients:
            with client.session_transaction() as session:
                session["user_id"] = 1
        wizard, brief_id = self.create_draft(clients[0])
        tokens = [self.token(client) for client in clients]

        def race(action):
            barrier = Barrier(2, timeout=10)

            def request(index):
                barrier.wait()
                with action(clients[index], tokens[index], index) as response:
                    return response.status_code

            with ThreadPoolExecutor(max_workers=2) as executor:
                return sorted(executor.map(request, range(2)))

        statuses = race(lambda client, token, index: client.post(wizard + "/save", json={
            "answers": complete("logo_branding", {"META01": f"Concurrent draft {index}"}),
            "generation": 0, "revision_response": "",
        }, headers={"X-CSRFToken": token}))
        self.assertEqual(statuses, [200, 409])
        self.assertEqual(self.db.execute("SELECT generation FROM adaptive_drafts WHERE brief_id=?", (brief_id,)).fetchone()[0], 1)
        statuses = race(lambda client, token, _: client.post(wizard + "/submit", data={
            "csrf_token": token, "generation": 1, "confirm": "yes",
        }))
        self.assertEqual(statuses, [302, 409])
        for table in ("adaptive_submissions", "notifications"):
            count = self.db.execute(f"SELECT COUNT(*) FROM {table} WHERE brief_id=?", (brief_id,)).fetchone()[0]
            self.assertEqual(count, 1)

    def test_signed_session_expires_and_cookie_flags_are_enforced(self):
        client = app.test_client()
        secure = app.config["SESSION_COOKIE_SECURE"]
        self.addCleanup(app.config.update, SESSION_COOKIE_SECURE=secure)
        app.config["SESSION_COOKIE_SECURE"] = True
        with client.get("/login", base_url="https://localhost") as page:
            token = next(attrs["value"] for tag, attrs in test_workflows.Page(page.get_data(as_text=True)).elements
                         if tag == "input" and attrs.get("name") == "csrf_token")
        response = client.post("/login", data={
            "email":"user1@example.test", "password":"Test-password-123", "csrf_token":token,
        }, base_url="https://localhost", headers={"Referer":"https://localhost/login"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("Secure", response.headers["Set-Cookie"])
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        self.assertIn("SameSite=Lax", response.headers["Set-Cookie"])
        self.assertEqual(client.get("/dashboard/client", base_url="https://localhost").status_code, 200)
        lifetime = app.config["PERMANENT_SESSION_LIFETIME"].total_seconds()
        with patch("itsdangerous.timed.time.time", return_value=time.time() + lifetime + 10):
            expired = client.get("/dashboard/client", base_url="https://localhost")
            self.assertEqual(expired.status_code, 302)
            self.assertEqual(expired.location, "/login")

    def test_recovery_guidance_matches_supported_operations(self):
        browser = app.test_client()
        for path in ("/forgot-password", "/reset-password-preview"):
            with self.subTest(path=path):
                with browser.get(path, query_string={"role":"service_provider"}) as response:
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(b'Password reset by email is currently unavailable', response.data)
                    self.assertIn(b'href="/login?role=service_provider"', response.data)
                    self.assertNotIn(b'<form', response.data)
                self.assertEqual(self.post(path, {"email":"user2@example.test"}, browser).status_code, 405)

    def test_attachment_checks_current_role_and_existing_assignment(self):
        owner, provider = self.fixture.client, app.test_client()
        self.fixture.login(2, provider)
        wizard, _ = self.create_draft(owner)
        upload = self.post(wizard + "/assets", {"file":(io.BytesIO(b"Stage 5 reference"), "reference.txt")}, owner)
        self.assertEqual(upload.status_code, 200, upload.json)
        asset_id = upload.json["id"]
        answers = complete("logo_branding", {"CORE02A":"yes", "CORE02B":asset_id})
        self.assertEqual(self.save(owner, wizard, answers, 0).status_code, 200)
        self.assertEqual(self.post(wizard + "/submit", {"confirm":"yes","generation":1}, owner).status_code, 302)
        path = f"/brief-assets/{asset_id}"
        with provider.get(path) as response:
            self.assertEqual(response.status_code, 200)
            self.assertIn("attachment", response.headers["Content-Disposition"])
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.db.execute("UPDATE users SET role='client' WHERE id=2")
        self.db.commit()
        self.assertEqual(provider.get(path).status_code, 404)
        self.db.execute("UPDATE users SET role='administrator' WHERE id=1")
        self.db.commit()
        self.assertEqual(owner.get(path).status_code, 404)

    def test_normal_markup_and_quoted_titles_are_rendered_as_text(self):
        client = self.fixture.client
        title = "O'Neill <b>Brand & identity</b>"
        wizard, _ = self.create_draft(client, title=title)
        response = client.get("/briefs", query_string={"search":"O'Neill"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'O&#39;Neill &lt;b&gt;Brand &amp; identity&lt;/b&gt;', response.data)
        self.assertNotIn(b'<b>Brand & identity</b>', response.data)
        self.assertIn(b'&lt;b&gt;Brand &amp; identity&lt;/b&gt;', client.get(wizard).data)

    def test_runtime_connection_rejects_invalid_notification_relationship(self):
        with app.app_context():
            db = get_db()
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError), db:
                db.execute(
                    """INSERT INTO notifications
                    (recipient_id, recipient_role, brief_id, event_type, title, message, event_reference)
                    VALUES (?, 'client', 1, 'approved', 'Fixture', 'Fixture', 'invalid-reference')""",
                    (99999,),
                )
            self.assertEqual(db.execute("SELECT COUNT(*) FROM notifications").fetchone()[0], 0)
