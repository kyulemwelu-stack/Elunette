r"""Run with: .venv\Scripts\python -m unittest discover -s tests -v.

All requests use disposable SQLite databases and real CSRF tokens.
"""
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from html.parser import HTMLParser

from werkzeug.security import generate_password_hash


_temporary = tempfile.TemporaryDirectory()
_old_database = os.environ.get("ELUNETTE_DATABASE")
os.environ["ELUNETTE_DATABASE"] = str(Path(_temporary.name) / "bootstrap.db")
from app import app
if _old_database is None:
    os.environ.pop("ELUNETTE_DATABASE")
else:
    os.environ["ELUNETTE_DATABASE"] = _old_database


def tearDownModule():
    _temporary.cleanup()


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class Workflows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = generate_password_hash("Test-password-123")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / "test.db")
        app.config.update(TESTING=True, DATABASE=self.path, WTF_CSRF_ENABLED=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(Path("schema.sql").read_text(encoding="utf-8"))
        for i, role in enumerate(("client", "service_provider", "client", "service_provider", "administrator"), 1):
            self.db.execute("INSERT INTO users (id, full_name, email, password_hash, role) VALUES (?, ?, ?, ?, ?)",
                            (i, f"User {i}", f"user{i}@example.test", self.password_hash, role))
        self.db.execute("INSERT INTO questionnaires (id,title,description,created_by,status) VALUES (1,'Design','Project requirements',2,'active')")
        self.db.execute("INSERT INTO questionnaire_versions (id,questionnaire_id,version_number) VALUES (1,1,1)")
        for i, kind, required in ((1, "multiple_choice", 1), (2, "text", 1), (3, "number", 0), (4, "date", 0)):
            self.db.execute("INSERT INTO questions (id,questionnaire_version_id,question_text,question_type,position,is_required,option_one,option_two) VALUES (?,1,?,?,?,?, 'Yes','No')",
                            (i, f"Question {i}", kind, i, required))
        self.db.execute("INSERT INTO adaptive_rules (questionnaire_version_id,source_question_id,target_question_id,expected_answer) VALUES (1,1,2,'Yes')")
        self.db.execute("INSERT INTO questionnaire_publications (questionnaire_id,questionnaire_version_id,title_snapshot,description_snapshot) VALUES (1,1,'Published Design','Published requirements')")
        for i in range(1, 9):
            self.db.execute("INSERT INTO project_briefs (id,client_id,questionnaire_version_id,title) VALUES (?,1,1,?)", (i, f"Project {i}"))
        self.db.commit()
        self.client = app.test_client()
        self.login(1)

    def tearDown(self):
        self.db.close()
        self.directory.cleanup()

    def token(self, client=None):
        response = (client or self.client).get("/login")
        return re.search(r'name="csrf_token"\s+value="([^"]+)"', response.get_data(as_text=True))[1]

    def login(self, user_id, client=None):
        client = client or self.client
        return client.post("/login", data={"email": f"user{user_id}@example.test", "password": "Test-password-123", "csrf_token": self.token(client)})

    def post(self, url, data=None, client=None, follow=False):
        client = client or self.client
        return client.post(url, data={**(data or {}), "csrf_token": self.token(client)}, follow_redirects=follow)

    def brief(self):
        return self.db.execute("SELECT * FROM project_briefs WHERE id=1").fetchone()

    def answers(self):
        return dict(self.db.execute("SELECT question_id,answer_text FROM brief_responses WHERE brief_id=1"))

    def test_eight_drafts_list_dashboard_filters_and_ownership(self):
        html = self.client.get("/briefs").get_data(as_text=True)
        for i in range(1, 9):
            self.assertIn(f"Project {i}", html)
        self.assertNotIn("No project briefs yet.", html)
        self.assertIn('overview-number">8', self.client.get("/dashboard/client").get_data(as_text=True))
        filtered = self.client.get("/briefs?search=Project+2&status=draft").get_data(as_text=True)
        self.assertIn("Project 2", filtered)
        self.assertNotIn("Project 1", filtered)
        self.login(3)
        self.assertNotIn("Project 1", self.client.get("/briefs").get_data(as_text=True))
        self.assertEqual(self.client.get("/client/questionnaires/1?brief_id=1").status_code, 404)
        for action in ("answers", "submit"):
            self.assertEqual(self.post(f"/briefs/1/{action}").status_code, 404)

    def test_partial_save_reload_update_clear_and_adaptive_cleanup(self):
        response = self.post("/briefs/1/answers", {"answer_1": "Yes"}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.answers(), {1: "Yes"})
        self.assertEqual(self.brief()["completeness_percentage"], 50)
        self.post("/briefs/1/answers", {"answer_1": "Yes", "answer_2": "A & B <design>", "answer_3": "12.5"})
        html = self.client.get("/client/questionnaires/1?brief_id=1").get_data(as_text=True)
        self.assertIn("A &amp; B &lt;design&gt;", html)
        self.assertEqual(self.brief()["completeness_percentage"], 100)
        self.post("/briefs/1/answers", {"answer_1": "No", "answer_2": "discard hidden"})
        self.assertEqual(self.answers(), {1: "No"})
        self.post("/briefs/1/answers", {"answer_1": ""})
        self.assertEqual(self.answers(), {})

    def test_validation_is_atomic(self):
        self.post("/briefs/1/answers", {"answer_1": "No"})
        for field, value in (("answer_1", "Fake"), ("answer_3", "NaN"), ("answer_3", "Infinity"), ("answer_3", "oops"), ("answer_4", "2026-02-30"), ("answer_2", "x" * 5001)):
            data = {"answer_1": "Yes", "answer_2": "Keep", field: value}
            self.assertEqual(self.post("/briefs/1/answers", data).status_code, 400)
            self.assertEqual(self.answers(), {1: "No"})

    def test_submission_saves_latest_answers_provider_review_and_approval(self):
        self.post("/briefs/1/answers", {"answer_1": "No"})
        response = self.post("/briefs/1/submit", {"save_answers": "1", "answer_1": "Yes", "answer_2": "Latest answer"}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.answers(), {1: "Yes", 2: "Latest answer"})
        self.assertEqual(self.brief()["status"], "submitted")
        self.assertIsNotNone(self.brief()["submitted_at"])
        self.assertEqual(self.post("/briefs/1/submit").status_code, 409)
        self.assertEqual(self.post("/briefs/1/answers", {"answer_1": "No"}).status_code, 404)
        provider = app.test_client()
        self.login(2, provider)
        for url in ("/provider/briefs", "/dashboard/provider", "/provider/briefs/1/review"):
            self.assertIn("Project 1", provider.get(url).get_data(as_text=True))
        review = provider.get("/provider/briefs/1/review").get_data(as_text=True)
        buttons = [attrs for tag, attrs in Page(review).elements if tag == "button" and attrs.get("value") == "approve"]
        self.assertEqual(len(buttons), 1)
        self.assertNotIn("disabled", buttons[0])
        self.assertIn("Latest answer", review)
        self.assertEqual(self.post("/provider/briefs/1/review", {"decision": "approve"}, provider).status_code, 302)
        self.assertEqual(self.brief()["status"], "approved")
        self.assertEqual(self.db.execute("SELECT count(*) FROM brief_reviews").fetchone()[0], 1)
        self.login(4, provider)
        self.assertNotIn("Project 1", provider.get("/provider/briefs").get_data(as_text=True))
        self.assertEqual(provider.get("/provider/briefs/1/review").status_code, 404)

    def test_incomplete_and_empty_submissions_remain_drafts(self):
        for data in ({}, {"save_answers": "1", "answer_1": "Yes"}):
            response = self.post("/briefs/1/submit", data, follow=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn("required", response.get_data(as_text=True))
            self.assertEqual(self.brief()["status"], "draft")
            self.assertIsNone(self.brief()["submitted_at"])
        self.assertEqual(self.answers(), {1: "Yes"})

    def test_revision_feedback_edit_resubmit(self):
        self.post("/briefs/1/submit", {"save_answers": "1", "answer_1": "No"})
        provider = app.test_client()
        self.login(2, provider)
        self.assertEqual(self.post("/provider/briefs/1/review", {"decision": "request_revision", "revision_comments": "Clarify scope"}, provider).status_code, 302)
        html = self.client.get("/client/questionnaires/1?brief_id=1").get_data(as_text=True)
        self.assertIn("Clarify scope", html)
        self.assertIn("Save Draft", html)
        self.post("/briefs/1/answers", {"answer_1": "Yes", "answer_2": "Updated scope"})
        self.assertEqual(self.brief()["status"], "revision_requested")
        self.assertEqual(self.post("/briefs/1/submit").status_code, 302)
        self.assertEqual(self.brief()["status"], "submitted")

    def test_csrf_authentication_roles_inactive_account_and_logout(self):
        anonymous = app.test_client()
        self.assertEqual(anonymous.get("/briefs").status_code, 302)
        self.assertEqual(self.client.get("/provider/briefs").status_code, 403)
        for url in ("/login", "/register", "/logout", "/briefs/new", "/briefs/1/answers", "/briefs/1/submit"):
            for token in (None, "invalid"):
                self.assertEqual(self.client.post(url, data={} if token is None else {"csrf_token": token}).status_code, 400)
        self.assertEqual(self.client.get("/logout").status_code, 405)
        self.assertEqual(self.post("/logout").status_code, 302)
        self.assertEqual(self.client.get("/briefs").status_code, 302)
        self.login(1)
        self.db.execute("UPDATE users SET status='inactive' WHERE id=1")
        self.db.commit()
        self.assertEqual(self.client.get("/briefs").status_code, 302)
        self.assertEqual(self.login(1).location, "/login")

    def test_questionnaire_form_posts_and_role_navigation(self):
        html = self.client.get("/client/questionnaires/1?brief_id=1").get_data(as_text=True)
        elements = Page(html).elements
        form = next(a for tag, a in elements if tag == "form" and a.get("id") == "client-questionnaire-form")
        self.assertEqual(form["action"], "/briefs/1/answers")
        submit = next(a for tag, a in elements if a.get("id") == "submit-brief-button")
        self.assertEqual(submit["form"], form["id"])
        self.assertEqual(submit["formaction"], "/briefs/1/submit")
        self.assertIn('event.submitter !== submitButton', html)
        for i, prefix in ((1, "/dashboard/client"), (2, "/dashboard/provider"), (5, "/dashboard/admin")):
            self.login(i)
            html = self.client.get("/notifications").get_data(as_text=True)
            links = [a["href"] for tag, a in Page(html).elements if tag == "a" and a.get("href", "").startswith("/")]
            self.assertTrue(any(link.startswith(prefix) for link in links))
            for link in links:
                self.assertLess(self.client.get(link).status_code, 400, link)

    def test_new_brief_uses_published_version(self):
        response = self.post("/briefs/new", {"project_title": "New project", "questionnaire_id": "1"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("brief_id=9", response.location)
        self.assertEqual(self.client.get(response.location).status_code, 200)

    def test_existing_brief_stays_on_original_published_version(self):
        self.db.execute("INSERT INTO questionnaire_versions (id,questionnaire_id,version_number) VALUES (2,1,2)")
        self.db.execute("INSERT INTO questions (id,questionnaire_version_id,question_text,question_type,position) VALUES (5,2,'New version question','text',1)")
        self.db.execute("INSERT INTO questionnaire_publications (questionnaire_id,questionnaire_version_id,title_snapshot,description_snapshot) VALUES (1,2,'New Design','New requirements')")
        self.db.execute("UPDATE questionnaires SET status='inactive' WHERE id=1")
        self.db.commit()
        html = self.client.get("/client/questionnaires/1?brief_id=1").get_data(as_text=True)
        self.assertIn("Published Design", html)
        self.assertNotIn("New version question", html)
        self.post("/briefs/1/answers", {"answer_1": "No", "answer_5": "foreign question"})
        self.assertEqual(self.answers(), {1: "No"})
        self.assertEqual(self.post("/briefs/1/submit").status_code, 302)
        self.assertEqual(self.brief()["status"], "submitted")

    def test_optional_only_questionnaire_progress_and_empty_guard(self):
        self.db.execute("INSERT INTO questionnaires (id,title,description,created_by,status) VALUES (2,'Optional','Optional answers',2,'active')")
        self.db.execute("INSERT INTO questionnaire_versions (id,questionnaire_id,version_number) VALUES (2,2,1)")
        self.db.execute("INSERT INTO questions (id,questionnaire_version_id,question_text,question_type,position) VALUES (5,2,'Optional answer','text',1)")
        self.db.execute("INSERT INTO questionnaire_publications (questionnaire_id,questionnaire_version_id,title_snapshot,description_snapshot) VALUES (2,2,'Optional','Optional answers')")
        self.db.execute("INSERT INTO project_briefs (id,client_id,questionnaire_version_id,title) VALUES (9,1,2,'Optional project')")
        self.db.commit()
        self.assertEqual(self.post("/briefs/9/submit").status_code, 302)
        self.assertEqual(self.db.execute("SELECT status FROM project_briefs WHERE id=9").fetchone()[0], "draft")
        self.post("/briefs/9/answers", {"answer_5": "Some detail"})
        self.assertEqual(self.db.execute("SELECT completeness_percentage FROM project_briefs WHERE id=9").fetchone()[0], 100)
        self.post("/briefs/9/submit")
        self.assertEqual(self.db.execute("SELECT status FROM project_briefs WHERE id=9").fetchone()[0], "submitted")

    def test_delete_owned_draft_cascades_answers_and_preserves_other_records(self):
        self.post("/briefs/1/answers", {"answer_1": "No"})
        self.post("/briefs/2/answers", {"answer_1": "Yes", "answer_2": "Keep me"})
        response = self.post("/briefs/1/delete", {"confirm_delete": "delete"}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Your draft brief has been deleted.", response.get_data(as_text=True))
        self.assertIsNone(self.brief())
        self.assertEqual(self.answers(), {})
        self.assertEqual(self.db.execute("SELECT count(*) FROM project_briefs").fetchone()[0], 7)
        self.assertEqual(self.db.execute("SELECT count(*) FROM brief_responses WHERE brief_id=2").fetchone()[0], 2)
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.post("/briefs/1/delete", {"confirm_delete": "delete"}).status_code, 404)

    def test_delete_requires_csrf_and_explicit_confirmation(self):
        for token in (None, "bad-token"):
            data = {"confirm_delete": "delete"}
            if token:
                data["csrf_token"] = token
            self.assertEqual(self.client.post("/briefs/1/delete", data=data).status_code, 400)
        self.assertEqual(self.post("/briefs/1/delete").status_code, 400)
        self.assertIsNotNone(self.brief())

    def test_delete_rejects_other_clients_providers_admins_and_anonymous_users(self):
        for user, expected in ((3, 404), (2, 403), (5, 403)):
            self.login(user)
            self.assertEqual(self.client.get("/briefs/1/delete").status_code, expected)
            self.assertEqual(self.post("/briefs/1/delete", {"confirm_delete": "delete"}).status_code, expected)
        self.post("/logout")
        self.assertEqual(self.client.get("/briefs/1/delete").status_code, 302)
        self.assertEqual(self.post("/briefs/1/delete", {"confirm_delete": "delete"}).status_code, 302)
        self.assertIsNotNone(self.brief())

    def test_delete_rechecks_status_and_rejects_every_non_draft_state(self):
        self.assertEqual(self.client.get("/briefs/1/delete").status_code, 200)
        for status in ("submitted", "under_review", "revision_requested", "approved"):
            self.db.execute("UPDATE project_briefs SET status=? WHERE id=1", (status,))
            self.db.commit()
            self.assertEqual(self.client.get("/briefs/1/delete").status_code, 409)
            self.assertEqual(self.post("/briefs/1/delete", {"confirm_delete": "delete"}).status_code, 409)
            self.assertEqual(self.brief()["status"], status)

    def test_delete_get_is_read_only_and_confirmation_escapes_title(self):
        self.db.execute("UPDATE project_briefs SET title=? WHERE id=1", ('<script>alert("x")</script>',))
        self.db.commit()
        html = self.client.get("/briefs/1/delete").get_data(as_text=True)
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn('<script>alert("x")</script>', html)
        self.assertIsNotNone(self.brief())
        form = next(a for tag, a in Page(html).elements if tag == "form")
        self.assertEqual(form["method"], "POST")
        self.assertEqual(form["action"], "/briefs/1/delete")

    def test_delete_returns_only_to_local_pages_and_retains_filters(self):
        response = self.post("/briefs/1/delete", {"confirm_delete": "delete", "return_to": "dashboard"})
        self.assertIn("/dashboard/client", response.location)
        response = self.post("/briefs/2/delete", {"confirm_delete": "delete", "return_to": "https://example.test", "search": "Project 3", "status": "draft"})
        self.assertTrue(response.location.startswith("/briefs"))
        self.assertIn("search=Project+3", response.location)
        self.assertIn("status=draft", response.location)

    def test_project_components_actions_and_accessible_table(self):
        self.db.execute("UPDATE project_briefs SET status='submitted',completeness_percentage=100 WHERE id=1")
        self.db.commit()
        for url in ("/briefs", "/dashboard/client"):
            html = self.client.get(url).get_data(as_text=True)
            elements = Page(html).elements
            deletes = [a["href"] for tag, a in elements if tag == "a" and "data-delete-draft" in a]
            self.assertNotIn("/briefs/1/delete", deletes)
            self.assertTrue(deletes)
            self.assertTrue(any(tag == "progress" and a.get("aria-label") for tag, a in elements))
            dialog = next(a for tag, a in elements if tag == "dialog")
            self.assertIn("aria-labelledby", dialog)
            self.assertIn("aria-describedby", dialog)
        elements = Page(self.client.get("/briefs").get_data(as_text=True)).elements
        self.assertEqual(sum(tag == "th" and a.get("scope") == "col" for tag, a in elements), 6)
        self.assertEqual(sum(tag == "th" and a.get("scope") == "row" for tag, a in elements), 8)
        self.assertTrue(any(tag == "div" and a.get("role") == "region" and a.get("tabindex") == "0" for tag, a in elements))

    def test_filtered_and_first_project_empty_states(self):
        html = self.client.get("/briefs?search=missing-project").get_data(as_text=True)
        self.assertIn("No briefs match your filters.", html)
        self.assertIn("Clear Filters", html)
        self.login(3)
        html = self.client.get("/briefs").get_data(as_text=True)
        self.assertIn("No project briefs yet.", html)
        self.assertIn("Create Your First Brief", html)

    def test_dashboard_shows_six_latest_brief_cards(self):
        html = self.client.get("/dashboard/client").get_data(as_text=True)
        cards = [a["id"] for tag, a in Page(html).elements
                 if tag == "h3" and a.get("id", "").startswith("brief-card-")]
        self.assertEqual(cards, [f"brief-card-{i}" for i in range(8, 2, -1)])

    def test_delete_preserves_draft_if_review_history_exists(self):
        self.post("/briefs/1/answers", {"answer_1": "No"})
        self.db.execute("INSERT INTO brief_reviews (brief_id,reviewer_id,decision) VALUES (1,2,'approved')")
        self.db.commit()
        self.assertEqual(self.post("/briefs/1/delete", {"confirm_delete": "delete"}).status_code, 409)
        self.assertIsNotNone(self.brief())
        self.assertEqual(self.answers(), {1: "No"})
        self.assertEqual(self.db.execute("SELECT count(*) FROM brief_reviews").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
