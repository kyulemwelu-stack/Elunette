r"""Run with: .venv\Scripts\python -m unittest discover -s tests -v.

All requests use disposable SQLite databases and real CSRF tokens.
"""
import os
import json
from contextlib import closing
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
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
        self.assertIn("Save Changes", html)
        self.assertIn("Resubmit for Review", html)
        review_id = self.db.execute("SELECT MAX(id) FROM brief_reviews WHERE brief_id=1").fetchone()[0]
        self.post("/briefs/1/answers", {"answer_1": "Yes", "answer_2": "Updated scope",
                                       "revision_review_id": str(review_id), "revision_response": "Clarified the scope"})
        self.assertEqual(self.brief()["status"], "revision_requested")
        self.assertEqual(self.post("/briefs/1/resubmit", {"revision_review_id": str(review_id), "confirm_resubmission": "yes"}).status_code, 302)
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

    def test_review_page_displays_recorded_progress_responses_and_history(self):
        self.post("/briefs/1/submit", {"save_answers": "1", "answer_1": "Yes", "answer_2": "First line\nSecond <detail>"})
        self.db.execute("UPDATE project_briefs SET completeness_percentage=65 WHERE id=1")
        self.db.execute("INSERT INTO brief_reviews (brief_id,reviewer_id,decision,comment) VALUES (1,2,'revision_requested',?)", ("Clarify <scope>\nInclude milestones",))
        self.db.commit()
        self.login(2)
        html = self.client.get("/provider/briefs/1/review").get_data(as_text=True)
        elements = Page(html).elements
        progress = next(a for tag, a in elements if tag == "progress")
        self.assertEqual(progress["value"], "65")
        self.assertEqual(progress["max"], "100")
        self.assertEqual(sum(tag == "article" and a.get("class") == "requirement-card" for tag, a in elements), 2)
        self.assertIn("Second &lt;detail&gt;", html)
        self.assertIn("Clarify &lt;scope&gt;", html)
        self.assertIn('class="review-timeline"', html)
        self.assertIn("User 2", html)
        forms = [a for tag, a in elements if tag == "form" and a.get("action") == "/provider/briefs/1/review"]
        self.assertEqual(len(forms), 2)
        self.assertTrue(all(a["method"] == "POST" for a in forms))
        self.assertEqual(sum(tag == "input" and a.get("name") == "csrf_token" for tag, a in elements), 3)
        self.assertNotIn("when the backend and permissions", html)

    def test_review_empty_states_and_closed_actions(self):
        self.db.execute("UPDATE project_briefs SET status='approved',completeness_percentage=37 WHERE id=1")
        self.db.commit()
        self.login(2)
        html = self.client.get("/provider/briefs/1/review").get_data(as_text=True)
        self.assertIn("No previous review decisions", html)
        self.assertIn("No saved responses to display", html)
        elements = Page(html).elements
        buttons = [a for tag, a in elements if tag == "button" and a.get("name") == "decision"]
        self.assertEqual(len(buttons), 2)
        self.assertTrue(all("disabled" in a for a in buttons))
        self.assertEqual(next(a for tag, a in elements if tag == "progress")["value"], "37")
        self.assertEqual(self.post("/provider/briefs/1/review", {"decision": "approve"}).status_code, 409)

    def test_review_csrf_and_required_revision_feedback(self):
        self.post("/briefs/1/submit", {"save_answers": "1", "answer_1": "No"})
        self.login(2)
        self.assertEqual(self.client.post("/provider/briefs/1/review", data={"decision": "approve"}).status_code, 400)
        self.assertEqual(self.post("/provider/briefs/1/review", {"decision": "request_revision", "revision_comments": " "}).status_code, 400)
        self.assertEqual(self.brief()["status"], "submitted")


    def start_revision(self, brief_id=1, feedback="Clarify scope"):
        self.assertEqual(self.post(f"/briefs/{brief_id}/submit", {"save_answers": "1", "answer_1": "Yes", "answer_2": "Original scope"}).status_code, 302)
        provider = app.test_client()
        self.login(2, provider)
        self.assertEqual(self.post(f"/provider/briefs/{brief_id}/review", {"decision": "request_revision", "revision_comments": feedback}, provider).status_code, 302)
        return self.db.execute("SELECT MAX(id) FROM brief_reviews WHERE brief_id=?", (brief_id,)).fetchone()[0], provider

    def cycle(self, review_id):
        return self.db.execute("SELECT * FROM brief_revision_cycles WHERE review_id=?", (review_id,)).fetchone()

    def test_revision_response_save_reload_and_response_only_update(self):
        review_id, provider = self.start_revision()
        baseline = self.cycle(review_id)["requested_answers_json"]
        result = self.post("/briefs/1/answers", {"revision_review_id": str(review_id), "revision_response": "  Clarified <scope>\nAdded milestones.  "}, follow=True)
        self.assertEqual(result.status_code, 200)
        self.assertIn("Clarified &lt;scope&gt;", result.get_data(as_text=True))
        self.assertEqual(self.answers(), {1: "Yes", 2: "Original scope"})
        self.assertEqual(self.cycle(review_id)["response_text"], "Clarified <scope>\nAdded milestones.")
        self.assertEqual(self.cycle(review_id)["requested_answers_json"], baseline)
        self.assertIsNotNone(self.cycle(review_id)["response_updated_at"])
        self.assertIsNone(self.cycle(review_id)["resubmitted_at"])
        self.assertEqual(self.brief()["status"], "revision_requested")
        provider_html = provider.get("/provider/briefs/1/review").get_data(as_text=True)
        self.assertNotIn("Added milestones.", provider_html)

    def test_revision_resubmit_snapshots_provider_visibility_and_closed_edits(self):
        review_id, provider = self.start_revision()
        data = {"revision_review_id": str(review_id), "confirm_resubmission": "yes", "save_answers": "1",
                "answer_1": "Yes", "answer_2": "Revised scope", "revision_response": "Added milestones and clarified scope"}
        result = self.post("/briefs/1/resubmit", data, follow=True)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.brief()["status"], "submitted")
        cycle = self.cycle(review_id)
        self.assertIsNotNone(cycle["resubmitted_at"])
        self.assertEqual(json.loads(cycle["requested_answers_json"])[1]["answer_text"], "Original scope")
        self.assertEqual(json.loads(cycle["resubmitted_answers_json"])[1]["answer_text"], "Revised scope")
        self.assertEqual(self.db.execute("SELECT comment FROM brief_reviews WHERE id=?", (review_id,)).fetchone()[0], "Clarify scope")
        for html in (provider.get("/provider/briefs/1/review").get_data(as_text=True), result.get_data(as_text=True)):
            self.assertIn("Added milestones and clarified scope", html)
            self.assertIn("Original scope", html)
            self.assertIn("Revised scope", html)
            self.assertIn("Clarify scope", html)
        self.assertEqual(self.post("/briefs/1/answers", data).status_code, 404)
        self.assertEqual(self.post("/briefs/1/resubmit", data).status_code, 409)
        self.assertEqual(self.cycle(review_id)["response_text"], data["revision_response"])

    def test_revision_validation_missing_confirmation_empty_response_and_length(self):
        review_id, _ = self.start_revision()
        data = {"revision_review_id": str(review_id)}
        self.assertEqual(self.post("/briefs/1/resubmit", data).status_code, 400)
        data["confirm_resubmission"] = "yes"
        response = self.post("/briefs/1/resubmit", data, follow=True)
        self.assertIn("Explain how you addressed", response.get_data(as_text=True))
        self.assertEqual(self.brief()["status"], "revision_requested")
        for action in ("answers", "resubmit"):
            invalid = dict(data, revision_response="x" * 5001, answer_2="Do not save")
            self.assertEqual(self.post(f"/briefs/1/{action}", invalid).status_code, 400)
            self.assertEqual(self.answers()[2], "Original scope")
            self.assertEqual(self.cycle(review_id)["response_text"], "")
        self.assertEqual(self.post("/briefs/1/answers", dict(data, revision_response="x" * 5000)).status_code, 302)

    def test_incomplete_revision_preserves_progress_without_closing_cycle(self):
        review_id, _ = self.start_revision()
        data = {"revision_review_id": str(review_id), "confirm_resubmission": "yes", "save_answers": "1",
                "answer_1": "Yes", "answer_2": "", "revision_response": "Work in progress"}
        response = self.post("/briefs/1/resubmit", data, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("required answers", response.get_data(as_text=True))
        self.assertEqual(self.brief()["status"], "revision_requested")
        self.assertEqual(self.cycle(review_id)["response_text"], "Work in progress")
        self.assertIsNone(self.cycle(review_id)["resubmitted_at"])
        self.assertEqual(json.loads(self.cycle(review_id)["requested_answers_json"])[1]["answer_text"], "Original scope")

    def test_revision_cycles_are_independent_and_stale_forms_are_rejected(self):
        review_id, provider = self.start_revision()
        data = {"revision_review_id": str(review_id), "confirm_resubmission": "yes", "revision_response": "First response", "answer_2": "First revision"}
        self.post("/briefs/1/resubmit", data)
        first = dict(self.cycle(review_id))
        self.post("/provider/briefs/1/review", {"decision": "request_revision", "revision_comments": "One more detail"}, provider)
        next_id = self.db.execute("SELECT MAX(id) FROM brief_reviews WHERE brief_id=1").fetchone()[0]
        self.assertNotEqual(review_id, next_id)
        self.assertEqual(self.cycle(next_id)["response_text"], "")
        self.assertEqual(json.loads(self.cycle(next_id)["requested_answers_json"])[1]["answer_text"], "First revision")
        for action in ("answers", "resubmit"):
            self.assertEqual(self.post(f"/briefs/1/{action}", data).status_code, 409)
        data.update(revision_review_id=str(next_id), revision_response="Second response", answer_2="Second revision")
        self.assertEqual(self.post("/briefs/1/resubmit", data).status_code, 302)
        self.assertEqual(dict(self.cycle(review_id)), first)
        self.assertEqual(self.db.execute("SELECT count(*) FROM brief_revision_cycles").fetchone()[0], 2)
        html = provider.get("/provider/briefs/1/review").get_data(as_text=True)
        for text in ("First response", "Second response", "Original scope", "First revision", "Second revision", "One more detail"):
            self.assertIn(text, html)

    def test_revision_permissions_csrf_status_and_cross_project_cycle(self):
        review_id, _ = self.start_revision()
        data = {"revision_review_id": str(review_id), "revision_response": "Private client response", "confirm_resubmission": "yes"}
        self.assertEqual(self.client.post("/briefs/1/resubmit", data=data).status_code, 400)
        self.assertEqual(self.client.post("/briefs/1/answers", data=data).status_code, 400)
        self.assertEqual(self.post("/briefs/1/submit", data).status_code, 409)
        self.assertEqual(self.post("/briefs/2/resubmit", data).status_code, 409)
        self.assertEqual(self.post("/briefs/2/answers", data).status_code, 409)
        for role_id, code in ((3, 404), (2, 403), (5, 403)):
            self.login(role_id)
            for action in ("answers", "resubmit"):
                self.assertEqual(self.post(f"/briefs/1/{action}", data).status_code, code)
        self.login(1)
        self.assertEqual(self.post("/briefs/1/answers", dict(data, revision_review_id="invalid")).status_code, 409)
        self.assertEqual(self.cycle(review_id)["response_text"], "")

    def test_pending_revision_answers_are_not_exposed_before_resubmission(self):
        review_id, provider = self.start_revision()
        self.post("/briefs/1/answers", {"revision_review_id": str(review_id), "answer_2": "Private unsent changes", "revision_response": "Private narrative"})
        html = provider.get("/provider/briefs/1/review").get_data(as_text=True)
        self.assertIn("Original scope", html)
        self.assertNotIn("Private unsent changes", html)
        self.assertNotIn("Private narrative", html)

    def test_legacy_revision_request_creates_cycle_before_replacing_answers(self):
        self.post("/briefs/1/submit", {"save_answers": "1", "answer_1": "Yes", "answer_2": "Legacy submitted answer"})
        self.db.execute("UPDATE project_briefs SET status='revision_requested' WHERE id=1")
        cur = self.db.execute("INSERT INTO brief_reviews (brief_id,reviewer_id,decision,comment) VALUES (1,2,'revision_requested','Legacy feedback')")
        self.db.commit()
        review_id = cur.lastrowid
        self.assertIsNone(self.cycle(review_id))
        html = self.client.get("/client/questionnaires/1?brief_id=1").get_data(as_text=True)
        self.assertIn('name="revision_review_id" value="'+str(review_id)+'"', html)
        self.assertIsNone(self.cycle(review_id))  # GET is read-only.
        data = {"revision_review_id": str(review_id), "answer_2": "New answer", "revision_response": "Legacy request addressed"}
        self.post("/briefs/1/answers", data)
        self.assertEqual(json.loads(self.cycle(review_id)["requested_answers_json"])[1]["answer_text"], "Legacy submitted answer")
        self.assertEqual(self.answers()[2], "New answer")

    def test_revision_adaptive_cleanup_preserves_previous_submission(self):
        review_id, _ = self.start_revision()
        self.post("/briefs/1/resubmit", {"revision_review_id": str(review_id), "confirm_resubmission": "yes",
                                       "revision_response": "Removed the extra scope", "answer_1": "No", "save_answers": "1"})
        self.assertEqual(self.answers(), {1: "No"})
        self.assertEqual(len(json.loads(self.cycle(review_id)["requested_answers_json"])), 2)
        self.assertEqual(len(json.loads(self.cycle(review_id)["resubmitted_answers_json"])), 1)

    def test_additive_revision_schema_is_idempotent_and_preserves_existing_records(self):
        self.post("/briefs/1/answers", {"answer_1": "No"})
        before = [tuple(row) for row in self.db.execute("SELECT * FROM project_briefs ORDER BY id")]
        answers = self.answers()
        self.db.executescript(Path("schema.sql").read_text(encoding="utf-8"))
        self.assertEqual([tuple(row) for row in self.db.execute("SELECT * FROM project_briefs ORDER BY id")], before)
        self.assertEqual(self.answers(), answers)
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_revision_schema_upgrade_preserves_a_populated_legacy_database(self):
        schema = Path("schema.sql").read_text(encoding="utf-8")
        path = Path(self.directory.name) / "legacy.db"
        with closing(sqlite3.connect(path)) as legacy:
            legacy.executescript(schema.split("-- Step 85.3:")[0])
            legacy.execute("ATTACH DATABASE ? AS fixtures", (self.path,))
            for table in ("users", "questionnaires", "questionnaire_versions", "questions", "adaptive_rules",
                          "questionnaire_publications", "project_briefs", "brief_responses", "brief_reviews"):
                legacy.execute(f"INSERT INTO {table} SELECT * FROM fixtures.{table}")
            legacy.commit()
            before = legacy.execute("SELECT * FROM project_briefs ORDER BY id").fetchall()
            legacy.executescript(schema)
            self.assertEqual(legacy.execute("SELECT * FROM project_briefs ORDER BY id").fetchall(), before)
            self.assertEqual(legacy.execute("SELECT count(*) FROM users").fetchone()[0], 5)
            self.assertEqual(legacy.execute("SELECT count(*) FROM brief_revision_cycles").fetchone()[0], 0)
            self.assertEqual(legacy.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_failed_resubmission_rolls_back_answers_response_and_status_together(self):
        review_id, _ = self.start_revision()
        self.db.executescript("""
            CREATE TRIGGER fail_revision_close BEFORE UPDATE OF resubmitted_at ON brief_revision_cycles
            BEGIN SELECT RAISE(ABORT, 'Simulated write failure'); END;
        """)
        data = {"revision_review_id": str(review_id), "confirm_resubmission": "yes",
                "revision_response": "Do not partially save", "answer_2": "Do not partially change"}
        with self.assertRaises(sqlite3.IntegrityError):
            self.post("/briefs/1/resubmit", data)
        self.assertEqual(self.brief()["status"], "revision_requested")
        self.assertEqual(self.answers()[2], "Original scope")
        self.assertEqual(self.cycle(review_id)["response_text"], "")
        self.assertIsNone(self.cycle(review_id)["resubmitted_at"])

    def approved_revision(self):
        review_id, provider = self.start_revision()
        self.post("/briefs/1/resubmit", {"revision_review_id": str(review_id), "confirm_resubmission": "yes",
                                       "revision_response": "Scope clarified", "answer_2": "Final client answer"})
        self.assertEqual(self.post("/provider/briefs/1/review", {"decision": "approve", "approval_comment": "Ready to proceed"}, provider).status_code, 302)
        return review_id

    def test_approved_questionnaire_is_view_only_and_retains_feedback_and_history(self):
        self.approved_revision()
        html = self.client.get("/client/questionnaires/1?brief_id=1").get_data(as_text=True)
        self.assertIn("This project brief has been approved and finalised. Your responses are now available for viewing only.", html)
        for obsolete in ("Save your progress anytime", "Check Answers", "Save Changes", "Save Draft",
                         "Resubmit for Review", "Submit for Review", "This brief has been submitted for review.",
                         "Answer the questions below."):
            self.assertNotIn(obsolete, html)
        for preserved in ("Ready to proceed", "Clarify scope", "Scope clarified", "Original scope", "Final client answer"):
            self.assertIn(preserved, html)
        elements = Page(html).elements
        self.assertEqual(sum(tag == "p" and a.get("class") == "approved-answer" for tag, a in elements), 4)
        self.assertFalse(any(tag in ("input", "select", "textarea") and a.get("name", "").startswith("answer_") for tag, a in elements))
        self.assertTrue(any(a.get("role") == "progressbar" and a.get("aria-valuenow") == "100" for tag, a in elements))

    def test_approved_brief_rejects_all_client_mutations_without_changing_records(self):
        review_id = self.approved_revision()
        tables = ("project_briefs", "brief_responses", "brief_reviews", "brief_revision_cycles")
        before = {table: [tuple(row) for row in self.db.execute(f"SELECT * FROM {table} ORDER BY id")] for table in tables}
        data = {"save_answers": "1", "answer_1": "No", "answer_2": "Tampered answer",
                "revision_review_id": str(review_id), "revision_response": "Tampered response",
                "confirm_resubmission": "yes", "confirm_delete": "delete"}
        for action, code in (("answers", 404), ("submit", 409), ("resubmit", 409), ("delete", 409)):
            self.assertEqual(self.post(f"/briefs/1/{action}", data).status_code, code, action)
        self.assertEqual(self.post("/client/questionnaires/1?brief_id=1", data).status_code, 405)
        self.assertEqual(self.client.get("/briefs/1/delete").status_code, 409)
        after = {table: [tuple(row) for row in self.db.execute(f"SELECT * FROM {table} ORDER BY id")] for table in tables}
        self.assertEqual(after, before)

    def test_approved_view_uses_recorded_progress_and_shows_all_saved_answers(self):
        # Legacy answers that no longer match an adaptive condition must stay viewable.
        self.post("/briefs/1/answers", {"answer_1": "Yes", "answer_2": "Saved conditional answer"})
        self.db.execute("UPDATE brief_responses SET answer_text='No' WHERE brief_id=1 AND question_id=1")
        self.db.execute("UPDATE project_briefs SET status='approved',completeness_percentage=73 WHERE id=1")
        self.db.commit()
        html = self.client.get("/client/questionnaires/1?brief_id=1").get_data(as_text=True)
        self.assertIn('aria-valuenow="73"', html)
        self.assertIn('class="approved-answer" aria-labelledby="question-label-2">Saved conditional answer</p>', html)
        self.assertIn("No response provided.", html)
        self.assertEqual(self.answers(), {1: "No", 2: "Saved conditional answer"})

    def test_illustrated_welcome_page_assets_and_navigation(self):
        client = app.test_client()
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        elements = Page(html).elements
        self.assertIn("Every beautiful idea <em>starts somewhere.</em>", html)
        self.assertIn("Welcome to elunette. Where your ideas find clarity, care and a place to grow.", html)
        links = [a for tag, a in elements if tag == "a"]
        hrefs = [a["href"] for a in links]
        for expected in ("/", "/about", "/login?role=client", "/login?role=service_provider", "/login?role=administrator", "/register"):
            self.assertIn(expected, hrefs)
            self.assertEqual(client.get(expected).status_code, 200)
        hero = next(a for tag, a in elements if tag == "img" and a.get("class") == "welcome-hero-image")
        self.assertEqual(hero["src"], "/static/images/welcome/welcome-hero.png")
        self.assertEqual(hero["width"], "1672")
        self.assertEqual(hero["height"], "941")
        self.assertEqual(hero["fetchpriority"], "high")
        asset = client.get(hero["src"])
        self.assertEqual(asset.status_code, 200)
        self.assertTrue(asset.data.startswith(b"\x89PNG\r\n\x1a\n"))
        asset.close()
        css = client.get("/static/css/welcome.css")
        self.assertEqual(css.status_code, 200)
        css.close()
        self.assertNotIn("css/welcome.css", client.get("/about").get_data(as_text=True))

    def test_welcome_role_links_preserve_database_role_authentication(self):
        for user_id, hint, target in ((1, "client", "/dashboard/client"),
                                      (2, "service_provider", "/dashboard/provider"),
                                      (5, "administrator", "/dashboard/admin")):
            client = app.test_client()
            response = client.post(f"/login?role={hint}", data={"email": f"user{user_id}@example.test",
                                   "password": "Test-password-123", "csrf_token": self.token(client)})
            self.assertTrue(response.location.startswith(target))
        # A query-string hint never grants a different role.
        client = app.test_client()
        response = client.post("/login?role=administrator", data={"email": "user1@example.test",
                               "password": "Test-password-123", "csrf_token": self.token(client)})
        self.assertTrue(response.location.startswith("/dashboard/client"))

    def test_studio_real_counts_statuses_revision_links_and_navigation(self):
        updates = {1: "revision_requested", 2: "approved", 3: "submitted", 4: "under_review",
                   5: "revision_requested", 6: "approved"}
        for brief_id, status in updates.items():
            self.db.execute("UPDATE project_briefs SET status=? WHERE id=?", (status, brief_id))
        self.db.commit()
        response = self.client.get("/dashboard/client")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("The Elunette Studio", html)
        self.assertIn("Good to see you, User.", html)
        for metric, count in (("total", 8), ("pending", 2), ("approved", 2), ("revision", 2)):
            self.assertRegex(html, rf'id="studio-stat-{metric}"[^>]*>{count}</strong>')
        for label in ("Draft", "Submitted", "Under Review", "Revision Requested", "Approved"):
            self.assertIn(label, html)
        elements = Page(html).elements
        for link in [a["href"] for tag, a in elements if tag == "a" and a.get("href", "").startswith("/")]:
            self.assertLess(self.client.get(link).status_code, 400, link)
        # Revision 1 is outside the six most recent projects but remains in Attention.
        self.assertIn('brief_id=1', html)
        self.assertIn('class="studio-attention studio-attention--active"', html)
        self.assertEqual(sum(tag == "progress" and a.get("max") == "8" for tag, a in elements), 5)
        self.assertIn('name="csrf_token"', html)
        self.assertIn('/briefs/new', html)

    def test_studio_empty_state_and_personalisation_are_private(self):
        self.login(3)
        html = self.client.get("/dashboard/client").get_data(as_text=True)
        self.assertIn('id="studio-stat-total" class="overview-number">0', html)
        self.assertIn("No project briefs yet.", html)
        self.assertIn("No revision requests waiting.", html)
        self.assertIn("Your workflow starts with your first brief.", html)
        self.assertNotIn("Project 1", html)
        self.assertNotIn('class="studio-flow-list"', html)
        self.assertIn("Good to see you, User.", html)
        # The new theme is confined to the dashboard.
        self.assertNotIn('css/studio.css', self.client.get('/briefs').get_data(as_text=True))

    def test_provider_studio_empty_and_single_pending_brief(self):
        self.login(2)
        html = self.client.get('/dashboard/provider').get_data(as_text=True)
        self.assertIn('The Elunette Provider Studio', html)
        self.assertIn('No briefs awaiting review.', html)
        self.assertIn('Your next thoughtful decision starts here.', html)
        self.assertIn('id="provider-stat-pending">0', html)
        self.assertNotIn('class="studio-flow-list"', html)
        self.login(1)
        self.post('/briefs/1/submit', {'save_answers': '1', 'answer_1': 'No'})
        self.login(2)
        html = self.client.get('/dashboard/provider').get_data(as_text=True)
        self.assertIn('id="provider-stat-pending">1', html)
        self.assertIn('Project 1', html)
        self.assertIn('User 1', html)
        self.assertIn('/provider/briefs/1/review', html)
        self.assertNotIn('Project 2', html)  # Other client drafts stay private.

    def test_provider_studio_real_metrics_activity_and_navigation(self):
        for brief_id, status in ((1, 'submitted'), (2, 'under_review'), (3, 'revision_requested'), (4, 'approved')):
            self.db.execute('UPDATE project_briefs SET status=? WHERE id=?', (status, brief_id))
        self.db.execute("INSERT INTO brief_reviews (brief_id,reviewer_id,decision,comment) VALUES (3,2,'revision_requested','Clarify scope')")
        self.db.execute("INSERT INTO brief_reviews (brief_id,reviewer_id,decision,comment) VALUES (4,2,'approved','Approved for delivery')")
        self.db.commit()
        self.login(2)
        html = self.client.get('/dashboard/provider').get_data(as_text=True)
        for metric, count in (('total', 4), ('pending', 2), ('approved', 1), ('revision', 1)):
            self.assertRegex(html, rf'id="provider-stat-{metric}"[^>]*>{count}</strong>')
        self.assertIn('id="provider-questionnaire-active">1', html)
        self.assertIn('id="provider-questionnaire-total">1', html)
        self.assertIn('Revision Requested', html)
        self.assertIn('Approved', html)
        self.assertIn('User 1', html)
        elements = Page(html).elements
        for link in [a['href'] for tag, a in elements if tag == 'a' and a.get('href', '').startswith('/')]:
            self.assertLess(self.client.get(link).status_code, 400, link)
            self.assertNotIn('/admin/', link)
        self.assertEqual(sum(tag == 'progress' and a.get('max') == '4' for tag, a in elements), 4)
        for token in (None, 'invalid'):
            self.assertEqual(self.client.post('/logout', data={} if token is None else {'csrf_token': token}).status_code, 400)
        self.assertEqual(self.post('/logout').status_code, 302)

    def test_provider_studio_does_not_leak_other_providers_data(self):
        self.db.execute("UPDATE project_briefs SET status='approved' WHERE id=1")
        self.db.execute("INSERT INTO brief_reviews (brief_id,reviewer_id,decision) VALUES (1,2,'approved')")
        self.db.commit()
        self.login(4)
        html = self.client.get('/dashboard/provider').get_data(as_text=True)
        self.assertIn('id="provider-stat-total" class="overview-number">0', html)
        self.assertIn('id="provider-questionnaire-total">0', html)
        self.assertNotIn('Project 1', html)
        self.assertNotIn('Design', html)
        self.assertNotIn('/provider/briefs/1/review', html)
        self.login(1)
        self.assertEqual(self.client.get('/dashboard/provider').status_code, 403)
        self.login(5)
        self.assertEqual(self.client.get('/dashboard/provider').status_code, 403)
        self.post('/logout')
        self.assertEqual(self.client.get('/dashboard/provider').status_code, 302)

    def test_provider_studio_queue_limit_does_not_limit_overview_counts(self):
        self.db.execute("UPDATE project_briefs SET status='submitted'")
        self.db.commit()
        self.login(2)
        html = self.client.get('/dashboard/provider').get_data(as_text=True)
        self.assertIn('id="provider-stat-pending">8', html)
        elements = Page(html).elements
        self.assertEqual(sum(tag == 'article' and a.get('class') == 'project-brief-card' for tag, a in elements), 6)

    def prepare_review_library(self):
        for brief_id, status in ((1, 'submitted'), (2, 'under_review'), (3, 'revision_requested'), (4, 'approved')):
            self.db.execute('UPDATE project_briefs SET status=? WHERE id=?', (status, brief_id))
        self.db.commit()
        self.login(2)

    def test_review_library_filters_search_tabs_and_record_links(self):
        self.prepare_review_library()
        html = self.client.get('/provider/briefs').get_data(as_text=True)
        self.assertIn('Review <em>Library.</em>', html)
        self.assertIn('THE ELUNETTE EDIT', html)
        self.assertEqual(html.count('class="edit-file-number"'), 4)
        self.assertIn('PROJECT FILE 001', html)
        self.assertIn('Brief #4', html)
        self.assertIn('Review Brief', html)
        self.assertIn('View Brief', html)
        for status in ('submitted', 'under_review', 'revision_requested', 'approved'):
            filtered = self.client.get('/provider/briefs', query_string={'status': status}).get_data(as_text=True)
            self.assertEqual(filtered.count('class="edit-file-number"'), 1)
            active = [a for tag, a in Page(filtered).elements if tag == 'a' and a.get('aria-current') == 'page']
            self.assertTrue(any('status='+status in a['href'] for a in active))
        filtered = self.client.get('/provider/briefs?search=Project+2&status=under_review').get_data(as_text=True)
        self.assertIn('Project 2', filtered)
        self.assertNotIn('Project 1', filtered)
        self.assertIn('PROJECT FILE 003', filtered)  # Same collection ordinal after filtering.
        links = [a['href'] for tag, a in Page(filtered).elements if tag == 'a']
        folder_links = [link for link in links if 'status=' in link and 'search=' in link]
        self.assertEqual(len(folder_links), 5)
        self.assertTrue(all('search=Project+2' in link for link in folder_links))
        for link in [link for link in links if link.startswith('/')]:
            self.assertLess(self.client.get(link).status_code, 400, link)
        fields = [a for tag, a in Page(filtered).elements if tag == 'input']
        self.assertTrue(any(a.get('name') == 'status' and a.get('value') == 'under_review' for a in fields))
        self.assertEqual(self.client.get('/provider/briefs?search=uSeR+1').get_data(as_text=True).count('class="edit-file-number"'), 4)

    def test_review_library_empty_states_scope_and_read_only_requests(self):
        self.prepare_review_library()
        tables = ('project_briefs', 'brief_responses', 'brief_reviews', 'brief_revision_cycles')
        before = {table: [tuple(row) for row in self.db.execute(f'SELECT * FROM {table} ORDER BY id')] for table in tables}
        html = self.client.get('/provider/briefs?search=no-match&status=approved').get_data(as_text=True)
        self.assertIn('Nothing in this folder', html)
        self.assertIn('View all project files', html)
        self.assertNotIn('class="edit-file-number"', html)
        unsafe = self.client.get('/provider/briefs', query_string={'search': '<script>alert(1)</script>'}).get_data(as_text=True)
        self.assertNotIn('<script>alert(1)</script>', unsafe)
        self.assertIn('&lt;script&gt;', unsafe)
        self.assertEqual(self.client.get('/provider/briefs?status=not-a-status').get_data(as_text=True).count('class="edit-file-number"'), 4)
        self.login(4)
        html = self.client.get('/provider/briefs').get_data(as_text=True)
        self.assertIn('Your next collaboration starts here.', html)
        self.assertNotIn('Project 1', html)
        self.assertNotIn('class="edit-file-number"', html)
        self.assertEqual({table: [tuple(row) for row in self.db.execute(f'SELECT * FROM {table} ORDER BY id')] for table in tables}, before)
        self.login(1)
        self.assertEqual(self.client.get('/provider/briefs').status_code, 403)
        self.login(5)
        self.assertEqual(self.client.get('/provider/briefs').status_code, 403)
        self.post('/logout')
        self.assertEqual(self.client.get('/provider/briefs').status_code, 302)

    def prepare_atelier(self):
        self.db.execute("INSERT INTO questionnaires (id,title,description,created_by,status) VALUES (2,'Brand workshop','Explore the details of a thoughtful identity.',2,'inactive')")
        self.db.execute("INSERT INTO questionnaire_versions (id,questionnaire_id,version_number) VALUES (2,2,1)")
        for qid, text in ((5, 'Your audience'), (6, 'Your priorities')):
            self.db.execute("INSERT INTO questions (id,questionnaire_version_id,question_text,question_type,position) VALUES (?,2,?,'text',?)", (qid, text, qid-4))
        self.db.commit()
        self.login(2)

    def test_atelier_real_cards_counts_filters_and_actions(self):
        self.prepare_atelier()
        response = self.client.get('/provider/questionnaires')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('THE QUESTION ATELIER', html)
        self.assertIn('Thoughtful questions. Beautiful beginnings.', html)
        self.assertIn('class="atelier-question-count">4', html)
        self.assertIn('class="atelier-question-count">2', html)
        self.assertIn('Explore the details of a thoughtful identity.', html)
        self.assertIn('VERSION 1', html)
        self.assertIn('>Activate</button>', html)
        self.assertIn('>Deactivate</button>', html)
        self.assertEqual(html.count('data-questionnaire-id='), 2)
        for link in [a['href'] for tag, a in Page(html).elements if tag == 'a' and a.get('href', '').startswith('/')]:
            self.assertLess(self.client.get(link).status_code, 400, link)
        filtered = self.client.get('/provider/questionnaires?search=Brand&status=inactive').get_data(as_text=True)
        self.assertIn('Brand workshop', filtered)
        self.assertNotIn('id="questionnaire-title-1"', filtered)
        self.assertEqual(filtered.count('data-questionnaire-id='), 1)
        self.assertIn('search=Brand', filtered)
        self.assertIn('name="status" value="inactive"', filtered)
        self.assertEqual(self.client.post('/provider/questionnaires/2/activate').status_code, 400)
        self.assertEqual(self.post('/provider/questionnaires/2/activate').status_code, 302)
        self.assertEqual(self.db.execute('SELECT status FROM questionnaires WHERE id=2').fetchone()[0], 'active')
        self.assertEqual(self.post('/provider/questionnaires/2/deactivate').status_code, 302)
        self.login(4)
        self.assertNotIn('Brand workshop', self.client.get('/provider/questionnaires').get_data(as_text=True))
        self.assertEqual(self.post('/provider/questionnaires/2/activate').status_code, 404)
        self.login(1)
        self.assertEqual(self.client.get('/provider/questionnaires').status_code, 403)

    def test_atelier_create_edit_adaptive_rules_and_publication_workflow(self):
        self.login(2)
        self.assertEqual(self.post('/provider/questionnaires/new', {'form_action':'save_template', 'title':'New creative brief', 'description':'Thoughtful project questions.'}).status_code, 302)
        qid = self.db.execute('SELECT MAX(id) FROM questionnaires').fetchone()[0]
        version_id = self.db.execute('SELECT id FROM questionnaire_versions WHERE questionnaire_id=?', (qid,)).fetchone()[0]
        self.post(f'/provider/questionnaires/{qid}/edit', {'form_action':'save_template', 'title':'Edited creative brief', 'description':'Clarified project questions.'})
        self.post(f'/provider/questionnaires/{qid}/questions/add', {'question_text':'Need an online shop?', 'question_type':'multiple_choice', 'option_one':'Yes', 'option_two':'No', 'is_required':'1'})
        self.post(f'/provider/questionnaires/{qid}/questions/add', {'question_text':'Describe the products', 'question_type':'text', 'is_required':'1'})
        questions = self.db.execute('SELECT id FROM questions WHERE questionnaire_version_id=? ORDER BY position', (version_id,)).fetchall()
        self.assertEqual(len(questions), 2)
        self.assertEqual(self.client.get(f'/provider/questionnaires/{qid}/questions/{questions[1][0]}/edit').status_code, 200)
        self.assertEqual(self.post(f'/provider/questionnaires/{qid}/rules', {'source_question_id':str(questions[0][0]), 'target_question_id':str(questions[1][0]), 'expected_answer':'Yes'}).status_code, 302)
        self.assertEqual(self.db.execute('SELECT count(*) FROM adaptive_rules WHERE questionnaire_version_id=?', (version_id,)).fetchone()[0], 1)
        self.assertEqual(self.post(f'/provider/questionnaires/{qid}/activate').status_code, 302)
        self.assertEqual(self.db.execute('SELECT count(*) FROM questionnaire_publications WHERE questionnaire_version_id=?', (version_id,)).fetchone()[0], 1)
        html = self.client.get('/provider/questionnaires?search=Edited').get_data(as_text=True)
        self.assertIn('Edited creative brief', html)
        self.assertIn('class="atelier-question-count">2', html)
        self.assertEqual(self.post(f'/provider/questionnaires/{qid}/deactivate').status_code, 302)
        self.assertEqual(self.post(f'/provider/questionnaires/{qid}/versions/new').status_code, 302)
        self.assertEqual(self.db.execute('SELECT MAX(version_number) FROM questionnaire_versions WHERE questionnaire_id=?', (qid,)).fetchone()[0], 2)

    def test_signature_footer_once_on_client_and_provider_pages(self):
        # Provide a real review page and an editable question for route coverage.
        self.post('/briefs/1/submit', {'save_answers':'1', 'answer_1':'No'})
        client_pages = ('/dashboard/client', '/briefs', '/briefs/new', '/client/questionnaires/1?brief_id=1',
                        '/briefs/2/delete', '/questionnaire-preview', '/brief-preview', '/brief-details-preview',
                        '/revision-history-preview', '/notifications')
        provider_pages = ('/dashboard/provider', '/provider/briefs', '/provider/briefs/1/review',
                          '/provider/questionnaires', '/provider/questionnaires/new', '/provider/questionnaires/1/edit',
                          '/provider/questionnaires/1/rules', '/provider/questionnaires/2/questions/5/edit',
                          '/provider/briefs/review-preview', '/notifications')
        for role_id, pages in ((1, client_pages), (2, provider_pages)):
            if role_id == 2:
                self.prepare_atelier()
            else:
                self.login(role_id)
            for url in pages:
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, url)
                html = response.get_data(as_text=True)
                footers = [a for tag, a in Page(html).elements if tag == 'footer' and a.get('class') == 'signature-footer']
                self.assertEqual(len(footers), 1, url)
                self.assertNotIn('<footer class="dashboard-footer"', html, url)
                self.assertNotIn('<footer class="studio-footer"', html, url)
                self.assertIn('css/signature-footer.css', html, url)
                self.assertIn('aria-label="Footer navigation"', html, url)
                self.assertIn('>Home</a>', html, url)
                self.assertIn('>About</a>', html, url)
        for url in ('/', '/about', '/login', '/register', '/forgot-password', '/reset-password-preview'):
            html = self.client.get(url).get_data(as_text=True)
            self.assertNotIn('signature-footer', html, url)
        with patch('app.datetime') as clock:
            clock.now.return_value.year = 2031
            html = self.client.get('/notifications').get_data(as_text=True)
            self.assertIn('&copy; 2031 elunette.', html)


if __name__ == "__main__":
    unittest.main()
