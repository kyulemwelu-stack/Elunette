
import os
import json
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps
from sqlite3 import IntegrityError

from flask import (
    Flask, abort, flash, redirect, render_template,
    request, session, url_for
)
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash
from database import get_db, init_app


# ==========================================
# ELUNETTE WEB APPLICATION
# ==========================================

app = Flask(__name__)

app.config["SECRET_KEY"] = (
    os.environ.get("ELUNETTE_SECRET_KEY")
    or secrets.token_hex(32)
)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

csrf = CSRFProtect(app)
init_app(app)


@app.context_processor
def signature_footer_context():
    # Elunette's local calendar year (East Africa Time, UTC+3).
    return {"current_year": datetime.now(timezone(timedelta(hours=3))).year}


# ==========================================
# AUTHENTICATION HELPERS
# ==========================================

def current_user():
    user_id = session.get("user_id")
    if user_id is None:
        return None

    db = get_db()
    user = db.execute(
        "SELECT id, full_name, email, role, status "
        "FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    if user is None or user["status"] != "active":
        session.clear()
        return None

    return user


def login_required(view):
    @wraps(view)
    def protected_view(*args, **kwargs):
        user = current_user()
        if user is None:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return protected_view


def role_required(required_role):
    def decorator(view):
        @wraps(view)
        def protected_view(*args, **kwargs):
            user = current_user()
            if user is None:
                flash("Please log in to continue.", "error")
                return redirect(url_for("login"))
            if user["role"] != required_role:
                abort(403)
            return view(*args, **kwargs)
        return protected_view
    return decorator


# ==========================================
# QUESTIONNAIRE VERSION HELPERS
# ==========================================

def latest_questionnaire_version(db, questionnaire_id):
    return db.execute(
        """
        SELECT id, version_number
        FROM questionnaire_versions
        WHERE questionnaire_id = ?
        ORDER BY version_number DESC
        LIMIT 1
        """,
        (questionnaire_id,)
    ).fetchone()


def version_is_published(db, version_id):
    record = db.execute(
        """
        SELECT id
        FROM questionnaire_publications
        WHERE questionnaire_version_id = ?
        """,
        (version_id,)
    ).fetchone()
    return record is not None


def questionnaire_is_editable(db, questionnaire):
    if questionnaire["status"] != "inactive":
        return False

    version = latest_questionnaire_version(
        db, questionnaire["id"]
    )

    if version is None:
        return False

    return not version_is_published(db, version["id"])


# ==========================================
# PUBLIC PAGES
# ==========================================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/about")
def about():
    return render_template("about.html")


# ==========================================
# CLIENT REGISTRATION
# ==========================================

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not all((full_name, email, password, confirm_password)):
        flash("Please complete all fields.", "error")
        return redirect(url_for("register"))

    if not 2 <= len(full_name) <= 100:
        flash("Enter a valid full name.", "error")
        return redirect(url_for("register"))

    valid_email = re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+", email
    )

    if len(email) > 254 or not valid_email:
        flash("Enter a valid email address.", "error")
        return redirect(url_for("register"))

    if len(password) < 12:
        flash(
            "Password must contain at least 12 characters.",
            "error"
        )
        return redirect(url_for("register"))

    if password != confirm_password:
        flash("Passwords do not match.", "error")
        return redirect(url_for("register"))

    password_hash = generate_password_hash(password)
    db = get_db()

    try:
        db.execute(
            """
            INSERT INTO users (
                full_name, email, password_hash, role, status
            )
            VALUES (?, ?, ?, 'client', 'active')
            """,
            (full_name, email, password_hash)
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        flash(
            "This email address is already registered.",
            "error"
        )
        return redirect(url_for("register"))

    flash(
        "Account created successfully. Please log in.",
        "success"
    )
    return redirect(url_for("login"))


# ==========================================
# USER LOGIN
# ==========================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE email = ?",
        (email,)
    ).fetchone()

    if user is None or not check_password_hash(
        user["password_hash"], password
    ):
        flash("Invalid email or password.", "error")
        return redirect(url_for("login"))

    if user["status"] != "active":
        flash("This account is inactive.", "error")
        return redirect(url_for("login"))

    session.clear()
    session["user_id"] = user["id"]
    session["user_role"] = user["role"]

    if user["role"] == "client":
        return redirect(url_for("client_dashboard"))
    elif user["role"] == "service_provider":
        return redirect(url_for("provider_dashboard"))
    elif user["role"] == "administrator":
        return redirect(url_for("admin_dashboard"))

    session.clear()
    abort(403)


# ==========================================
# USER LOGOUT
# ==========================================

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash(
        "You have been logged out successfully.",
        "success"
    )
    return redirect(url_for("login"))


# ==========================================
# PASSWORD RECOVERY PREVIEWS
# ==========================================

@app.route("/forgot-password")
def forgot_password():
    return render_template("forgot_password.html")


@app.route("/reset-password-preview")
def reset_password_preview():
    return render_template("reset_password.html")


# ==========================================
# CLIENT WORKSPACE
# ==========================================

@app.route("/dashboard/client")
@app.route("/dashboard/client-preview")
@role_required("client")
def client_dashboard():
    briefs = client_briefs()
    status_counts = {status: sum(b["status"] == status for b in briefs)
                     for status in ("draft", "submitted", "under_review", "revision_requested", "approved")}
    return render_template(
        "client_dashboard.html", briefs=briefs[:6],
        total=len(briefs),
        pending=status_counts["submitted"] + status_counts["under_review"],
        approved=status_counts["approved"], revision=status_counts["revision_requested"],
        status_counts=status_counts, user=current_user(),
        revision_briefs=[b for b in briefs if b["status"] == "revision_requested"][:3],
        latest_draft=next((b for b in briefs if b["status"] == "draft"), None)
    )


@app.route("/briefs")
@app.route("/briefs-preview")
@role_required("client")
def my_briefs():
    search = request.args.get("search", "").strip()[:150]
    status = request.args.get("status", "").strip()
    if status not in ("draft", "submitted", "under_review", "revision_requested", "approved"):
        status = ""
    briefs = [b for b in client_briefs()
              if search.casefold() in b["title"].casefold()
              and (not status or b["status"] == status)]
    return render_template("my_briefs.html", briefs=briefs,
                           search_query=search, status_filter=status)


def client_briefs():
    return get_db().execute(
        """
        SELECT pb.*, v.questionnaire_id, v.version_number,
               p.title_snapshot AS questionnaire_title
        FROM project_briefs pb
        JOIN questionnaire_versions v ON v.id = pb.questionnaire_version_id
        JOIN questionnaire_publications p ON p.questionnaire_version_id = v.id
        WHERE pb.client_id = ?
        ORDER BY pb.updated_at DESC, pb.id DESC
        """, (current_user()["id"],)
    ).fetchall()


@app.route("/briefs/<int:brief_id>/delete", methods=["GET", "POST"])
@role_required("client")
def delete_draft_brief(brief_id):
    db = get_db()
    client = current_user()
    if request.method == "POST":
        # Serialize against saving/submission before checking the current status.
        db.execute("BEGIN IMMEDIATE")

    brief = db.execute(
        "SELECT id, title, status FROM project_briefs WHERE id = ? AND client_id = ?",
        (brief_id, client["id"])
    ).fetchone()
    if brief is None:
        abort(404)
    if brief["status"] != "draft":
        abort(409, "Only draft briefs can be deleted.")

    if request.method == "GET":
        return render_template("delete_draft.html", brief=brief)
    if request.form.get("confirm_delete") != "delete":
        abort(400, "Please confirm draft deletion.")

    try:
        deleted = db.execute(
            "DELETE FROM project_briefs WHERE id = ? AND client_id = ? AND status = 'draft'",
            (brief_id, client["id"])
        )
        if deleted.rowcount != 1:
            abort(409, "This brief can no longer be deleted.")
        # Saved responses are removed by the existing ON DELETE CASCADE constraint.
        db.commit()
    except IntegrityError:
        db.rollback()
        abort(409, "This draft has review history and cannot be deleted.")

    flash("Your draft brief has been deleted.", "success")
    if request.form.get("return_to") == "dashboard":
        return redirect(url_for("client_dashboard"))
    return redirect(url_for("my_briefs",
                            search=request.form.get("search", "").strip()[:150],
                            status=request.form.get("status", "").strip()[:30]))


# ==========================================
# CREATE NEW PROJECT BRIEF
# ==========================================

@app.route("/briefs/new", methods=["GET", "POST"])
@role_required("client")
def new_brief():
    db = get_db()

    if request.method == "POST":
        user = current_user()
        title = request.form.get(
            "project_title", ""
        ).strip()
        questionnaire_id = request.form.get(
            "questionnaire_id", "", type=int
        )

        if not title or len(title) > 150:
            flash(
                "Enter a project title of up to 150 characters.",
                "error"
            )
            return redirect(url_for("new_brief"))

        if questionnaire_id is None:
            flash(
                "Please select a questionnaire.",
                "error"
            )
            return redirect(url_for("new_brief"))

        questionnaire = db.execute(
            """
            SELECT q.id, q.title,
                   v.id AS version_id,
                   v.version_number
            FROM questionnaires q
            JOIN questionnaire_versions v
                ON v.questionnaire_id = q.id
            JOIN questionnaire_publications p
                ON p.questionnaire_version_id = v.id
            WHERE q.id = ?
              AND q.status = 'active'
            ORDER BY v.version_number DESC
            LIMIT 1
            """,
            (questionnaire_id,)
        ).fetchone()

        if questionnaire is None:
            flash(
                "The selected questionnaire is not available.",
                "error"
            )
            return redirect(url_for("new_brief"))

        cursor = db.execute(
            """
            INSERT INTO project_briefs (
                client_id,
                questionnaire_version_id,
                title,
                status,
                completeness_percentage
            )
            VALUES (?, ?, ?, 'draft', 0)
            """,
            (
                user["id"],
                questionnaire["version_id"],
                title
            )
        )
        db.commit()

        brief_id = cursor.lastrowid

        return redirect(
            url_for(
                "client_questionnaire",
                questionnaire_id=questionnaire_id,
                brief_id=brief_id
            )
        )

    questionnaires = db.execute(
        """
        SELECT q.id, q.title, v.version_number
        FROM questionnaires q
        JOIN questionnaire_versions v
            ON v.questionnaire_id = q.id
        JOIN questionnaire_publications p
            ON p.questionnaire_version_id = v.id
        WHERE q.status = 'active'
          AND v.version_number = (
              SELECT MAX(v2.version_number)
              FROM questionnaire_versions v2
              JOIN questionnaire_publications p2
                  ON p2.questionnaire_version_id = v2.id
              WHERE v2.questionnaire_id = q.id
          )
        ORDER BY q.title COLLATE NOCASE ASC
        """
    ).fetchall()

    return render_template(
        "new_brief.html",
        questionnaires=questionnaires
    )


# ==========================================
# CLIENT DESIGN PREVIEWS
# ==========================================

@app.route("/questionnaire-preview")
@role_required("client")
def questionnaire_preview():
    return render_template("questionnaire.html")


@app.route("/brief-preview")
@role_required("client")
def brief_preview_design():
    return render_template("brief_preview.html")


@app.route("/brief-details-preview")
@role_required("client")
def brief_details_preview():
    return render_template("brief_details.html")


@app.route("/revision-history-preview")
@role_required("client")
def revision_history_preview():
    return render_template("revision_history.html")


# ==========================================
# SHARED NOTIFICATIONS
# ==========================================

@app.route("/notifications")
@login_required
def notifications():
    return render_template("notifications.html", user=current_user())


# ==========================================
# SERVICE PROVIDER DASHBOARD
# ==========================================

@app.route("/dashboard/provider")
@app.route("/dashboard/provider-preview")
@role_required("service_provider")
def provider_dashboard():
    briefs = provider_brief_records()
    provider = current_user()
    db = get_db()
    questionnaires = db.execute(
        "SELECT COUNT(*) AS total, COALESCE(SUM(status = 'active'), 0) AS active "
        "FROM questionnaires WHERE created_by = ?", (provider["id"],)
    ).fetchone()
    activity = db.execute(
        """
        SELECT br.id, br.decision, br.comment, br.created_at, pb.id AS brief_id,
               pb.title, u.full_name AS client_name
        FROM brief_reviews br
        JOIN project_briefs pb ON pb.id = br.brief_id
        JOIN questionnaire_versions v ON v.id = pb.questionnaire_version_id
        JOIN questionnaires q ON q.id = v.questionnaire_id
        JOIN users u ON u.id = pb.client_id
        WHERE q.created_by = ? AND br.reviewer_id = ? AND pb.status != 'draft'
        ORDER BY br.created_at DESC, br.id DESC LIMIT 5
        """, (provider["id"], provider["id"])
    ).fetchall()
    return render_template(
        "provider_dashboard.html", overview=brief_overview(briefs), user=provider,
        briefs=[b for b in briefs if b["status"] in ("submitted", "under_review")][:6],
        following_up=[b for b in briefs if b["status"] in ("revision_requested", "approved")][:3],
        status_counts={status: sum(b["status"] == status for b in briefs)
                       for status in ("submitted", "under_review", "revision_requested", "approved")},
        questionnaires=questionnaires, recent_activity=activity
    )


# ==========================================
# PROVIDER CLIENT BRIEFS
# ==========================================

@app.route("/provider/briefs")
@role_required("service_provider")
def provider_briefs():
    records = provider_brief_records()
    search = request.args.get("search", "").strip()[:150]
    status = request.args.get("status", "").strip()
    if status not in ("submitted", "under_review", "revision_requested", "approved"):
        status = ""
    matching = [b for b in records
                if search.casefold() in b["title"].casefold()
                or search.casefold() in b["client_name"].casefold()]
    briefs = [b for b in matching if not status or b["status"] == status]
    return render_template("provider_briefs.html", briefs=briefs,
                           overview=brief_overview(records),
                           search_query=search, status_filter=status, user=current_user(),
                           all_matching_count=len(matching),
                           tab_counts={s: sum(b["status"] == s for b in matching)
                                       for s in ("submitted", "under_review", "revision_requested", "approved")},
                           file_numbers={b["id"]: number for number, b in enumerate(records, 1)})


def brief_overview(briefs):
    return {
        "total": len(briefs),
        "pending": sum(b["status"] in ("submitted", "under_review") for b in briefs),
        "revision": sum(b["status"] == "revision_requested" for b in briefs),
        "approved": sum(b["status"] == "approved" for b in briefs),
    }


def provider_brief_records():
    return get_db().execute(
        """
        SELECT
            pb.id,
            pb.title,
            pb.status,
            pb.completeness_percentage,
            pb.created_at,
            pb.updated_at,
            pb.submitted_at,
            u.full_name AS client_name,
            q.title AS questionnaire_title,
            v.version_number
        FROM project_briefs AS pb
        JOIN users AS u
            ON u.id = pb.client_id
        JOIN questionnaire_versions AS v
            ON v.id = pb.questionnaire_version_id
        JOIN questionnaires AS q
            ON q.id = v.questionnaire_id
        WHERE q.created_by = ?
          AND pb.status IN (
              'submitted',
              'under_review',
              'revision_requested',
              'approved'
          )
        ORDER BY pb.updated_at DESC, pb.id DESC
        """,
        (current_user()["id"],)
    ).fetchall()



# ==========================================
# PROVIDER REVIEW PREVIEW
# ==========================================

@app.route("/provider/briefs/review-preview")
@role_required("service_provider")
def review_brief_preview():
    return render_template("review_brief.html")


# ==========================================
# PROVIDER REVIEW DECISIONS
# ==========================================

@app.route(
    "/provider/briefs/<int:brief_id>/review",
    methods=["GET", "POST"]
)
@role_required("service_provider")
def review_brief(brief_id):
    db = get_db()
    provider = current_user()
    if request.method == "POST":
        db.execute("BEGIN IMMEDIATE")

    brief = db.execute(
        """
        SELECT
            pb.*,
            u.full_name AS client_name,
            q.title AS questionnaire_title,
            v.version_number
        FROM project_briefs pb
        JOIN users u
            ON u.id = pb.client_id
        JOIN questionnaire_versions v
            ON v.id = pb.questionnaire_version_id
        JOIN questionnaires q
            ON q.id = v.questionnaire_id
        WHERE pb.id = ?
          AND q.created_by = ?
          AND pb.status != 'draft'
        """,
        (brief_id, provider["id"])
    ).fetchone()

    if brief is None:
        abort(404)

    if request.method == "POST":
        if brief["status"] not in (
            "submitted", "under_review"
        ):
            abort(409)

        decision = request.form.get("decision", "")

        if decision == "approve":
            comment = request.form.get(
                "approval_comment", ""
            ).strip()

            if brief["completeness_percentage"] != 100:
                abort(409, "The brief is not complete.")

            questions = db.execute(
                """
                SELECT *
                FROM questions
                WHERE questionnaire_version_id = ?
                  AND is_active = 1
                ORDER BY position ASC, id ASC
                """,
                (brief["questionnaire_version_id"],)
            ).fetchall()

            saved_answers = db.execute(
                """
                SELECT r.question_id, r.answer_text
                FROM brief_responses r
                JOIN questions q
                    ON q.id = r.question_id
                WHERE r.brief_id = ?
                  AND q.questionnaire_version_id = ?
                """,
                (
                    brief_id,
                    brief["questionnaire_version_id"]
                )
            ).fetchall()

            answers = {
                row["question_id"]: row["answer_text"].strip()
                for row in saved_answers
            }

            rules = db.execute(
                """
                SELECT
                    source_question_id,
                    target_question_id,
                    expected_answer
                FROM adaptive_rules
                WHERE questionnaire_version_id = ?
                """,
                (brief["questionnaire_version_id"],)
            ).fetchall()

            rules_by_target = {
                rule["target_question_id"]: rule
                for rule in rules
            }

            visible = {}

            if not questions:
                abort(409, "No questions available.")

            for question in questions:
                question_id = question["id"]
                rule = rules_by_target.get(question_id)
                applicable = True

                if rule is not None:
                    source_id = rule["source_question_id"]
                    applicable = (
                        visible.get(source_id, False)
                        and answers.get(source_id, "")
                        == rule["expected_answer"]
                    )

                visible[question_id] = applicable

                if applicable and question["is_required"]:
                    answer = answers.get(question_id, "")

                    if not answer:
                        abort(
                            409,
                            "Required answers are incomplete."
                        )

                    if question["question_type"] == "multiple_choice":
                        valid_options = (
                            question["option_one"],
                            question["option_two"]
                        )
                        if answer not in valid_options:
                            abort(
                                409,
                                "An answer is invalid."
                            )

            new_status = "approved"

        elif decision == "request_revision":
            comment = request.form.get(
                "revision_comments", ""
            ).strip()

            if not comment:
                abort(
                    400,
                    "Revision feedback is required."
                )

            new_status = "revision_requested"

        else:
            abort(400)

        cursor = db.execute(
            """
            UPDATE project_briefs
            SET status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND status IN (
                  'submitted', 'under_review'
              )
            """,
            (new_status, brief_id)
        )

        if cursor.rowcount != 1:
            db.rollback()
            abort(409)

        review_cursor = db.execute(
            """
            INSERT INTO brief_reviews (
                brief_id,
                reviewer_id,
                decision,
                comment
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                brief_id,
                provider["id"],
                new_status,
                comment
            )
        )

        if new_status == "revision_requested":
            ensure_revision_cycle(db, brief_id, review_cursor.lastrowid)
        db.commit()

        flash(
            "Review decision saved successfully.",
            "success"
        )

        return redirect(
            url_for("review_brief", brief_id=brief_id)
        )

    responses = db.execute(
        """
        SELECT q.question_text, r.answer_text
        FROM brief_responses r
        JOIN questions q
            ON q.id = r.question_id
        WHERE r.brief_id = ?
          AND q.questionnaire_version_id = ?
        ORDER BY q.position ASC, q.id ASC
        """,
        (
            brief_id,
            brief["questionnaire_version_id"]
        )
    ).fetchall()

    if brief["status"] == "revision_requested":
        pending = revision_request(db, brief_id)
        if pending and pending["cycle_id"]:
            cycle = db.execute("SELECT requested_answers_json FROM brief_revision_cycles WHERE id = ?",
                               (pending["cycle_id"],)).fetchone()
            responses = json.loads(cycle["requested_answers_json"])

    revision_cycles = revision_history_records(db, brief_id)
    review_history = db.execute(
        """
        SELECT
            br.decision,
            br.comment,
            br.created_at,
            u.full_name AS reviewer_name
        FROM brief_reviews br
        JOIN users u
            ON u.id = br.reviewer_id
        WHERE br.brief_id = ?
        ORDER BY br.created_at DESC, br.id DESC
        """,
        (brief_id,)
    ).fetchall()

    can_review = brief["status"] in (
        "submitted", "under_review"
    )

    return render_template(
        "review_brief.html",
        brief=brief,
        responses=responses,
        review_history=review_history,
        can_review=can_review,
        revision_cycles=revision_cycles
    )


# ==========================================
# QUESTIONNAIRE MANAGEMENT
# ==========================================

@app.route("/provider/questionnaires")
@role_required("service_provider")
def questionnaire_management():
    user = current_user()
    db = get_db()

    search_query = request.args.get(
        "search", ""
    ).strip()[:150]

    status_filter = request.args.get(
        "status", ""
    ).strip()

    if status_filter not in ("", "active", "inactive"):
        status_filter = ""

    overview = db.execute(
        """
        SELECT
            COUNT(*) AS total,
            COALESCE(SUM(
                CASE WHEN status = 'active'
                THEN 1 ELSE 0 END
            ), 0) AS active,
            COALESCE(SUM(
                CASE WHEN status = 'inactive'
                THEN 1 ELSE 0 END
            ), 0) AS inactive
        FROM questionnaires
        WHERE created_by = ? AND title LIKE ?
        """,
        (user["id"], f"%{search_query}%")
    ).fetchone()

    questionnaires = db.execute(
        """
        SELECT
            q.id,
            q.title,
            q.description,
            q.status,
            q.updated_at,
            COALESCE((
                SELECT MAX(v.version_number)
                FROM questionnaire_versions v
                WHERE v.questionnaire_id = q.id
            ), 1) AS version_number,
            (
                SELECT COUNT(*)
                FROM questions qs
                WHERE qs.questionnaire_version_id = (
                    SELECT v.id
                    FROM questionnaire_versions v
                    WHERE v.questionnaire_id = q.id
                    ORDER BY v.version_number DESC
                    LIMIT 1
                )
            ) AS question_count
        FROM questionnaires q
        WHERE q.created_by = ?
          AND q.title LIKE ?
          AND (? = '' OR q.status = ?)
        ORDER BY q.updated_at DESC, q.id DESC
        """,
        (
            user["id"],
            f"%{search_query}%",
            status_filter,
            status_filter
        )
    ).fetchall()

    return render_template(
        "questionnaire_management.html",
        questionnaires=questionnaires,
        overview=overview,
        search_query=search_query,
        status_filter=status_filter,
        user=user
    )


# ==========================================
# CREATE QUESTIONNAIRE
# ==========================================

@app.route(
    "/provider/questionnaires/new",
    methods=["GET", "POST"]
)
@role_required("service_provider")
def create_questionnaire():
    if request.method == "GET":
        return render_template("questionnaire_editor.html")

    if request.form.get("form_action") != "save_template":
        abort(400)

    title = request.form.get("title", "").strip()
    description = request.form.get(
        "description", ""
    ).strip()

    if not title or not description:
        flash(
            "Please complete all questionnaire fields.",
            "error"
        )
        return redirect(url_for("create_questionnaire"))

    if len(title) > 150:
        flash(
            "Questionnaire title cannot exceed 150 characters.",
            "error"
        )
        return redirect(url_for("create_questionnaire"))

    if len(description) > 1000:
        flash(
            "Description cannot exceed 1000 characters.",
            "error"
        )
        return redirect(url_for("create_questionnaire"))

    user = current_user()
    db = get_db()

    try:
        cursor = db.execute(
            """
            INSERT INTO questionnaires (
                title, description, created_by, status
            )
            VALUES (?, ?, ?, 'inactive')
            """,
            (title, description, user["id"])
        )

        questionnaire_id = cursor.lastrowid

        db.execute(
            """
            INSERT INTO questionnaire_versions (
                questionnaire_id, version_number
            )
            VALUES (?, 1)
            """,
            (questionnaire_id,)
        )
        db.commit()

    except Exception:
        db.rollback()
        raise

    flash(
        "Questionnaire created successfully as an inactive draft.",
        "success"
    )
    return redirect(url_for("create_questionnaire"))


@app.route("/provider/questionnaires/rules-preview")
@role_required("service_provider")
def adaptive_rules_preview():
    return render_template("adaptive_rules.html")


# ==========================================
# ADMINISTRATOR WORKSPACE
# ==========================================

@app.route("/dashboard/admin")
@app.route("/dashboard/admin-preview")
@role_required("administrator")
def admin_dashboard():
    return render_template("admin_dashboard.html")


@app.route("/admin/users")
@role_required("administrator")
def user_management():
    return render_template("user_management.html")


@app.route("/admin/users/new", methods=["GET"])
@role_required("administrator")
def create_user():
    return render_template("create_user.html")


@app.route("/admin/users/edit-preview", methods=["GET"])
@role_required("administrator")
def edit_user_preview():
    return render_template("edit_user.html")


# ==========================================
# EDIT EXISTING QUESTIONNAIRE
# ==========================================

@app.route(
    "/provider/questionnaires/<int:questionnaire_id>/edit",
    methods=["GET", "POST"]
)
@role_required("service_provider")
def edit_questionnaire(questionnaire_id):
    user = current_user()
    db = get_db()

    questionnaire = db.execute(
        """
        SELECT *
        FROM questionnaires
        WHERE id = ? AND created_by = ?
        """,
        (questionnaire_id, user["id"])
    ).fetchone()

    if questionnaire is None:
        abort(404)

    if request.method == "POST":
        if not questionnaire_is_editable(db, questionnaire):
            abort(409)

        if request.form.get("form_action") != "save_template":
            abort(400)

        title = request.form.get("title", "").strip()
        description = request.form.get(
            "description", ""
        ).strip()

        if (
            not title
            or not description
            or len(title) > 150
            or len(description) > 1000
        ):
            flash(
                "Please enter valid questionnaire details.",
                "error"
            )
            return redirect(
                url_for(
                    "edit_questionnaire",
                    questionnaire_id=questionnaire_id
                )
            )

        db.execute(
            """
            UPDATE questionnaires
            SET title = ?,
                description = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND created_by = ?
            """,
            (
                title,
                description,
                questionnaire_id,
                user["id"]
            )
        )
        db.commit()

        flash(
            "Questionnaire updated successfully.",
            "success"
        )
        return redirect(
            url_for(
                "edit_questionnaire",
                questionnaire_id=questionnaire_id
            )
        )

    questions = db.execute(
        """
        SELECT
            id, question_text, question_type,
            position, is_required, option_one, option_two
        FROM questions
        WHERE questionnaire_version_id = (
            SELECT id
            FROM questionnaire_versions
            WHERE questionnaire_id = ?
            ORDER BY version_number DESC
            LIMIT 1
        )
        ORDER BY position ASC, id ASC
        """,
        (questionnaire_id,)
    ).fetchall()

    can_edit = questionnaire_is_editable(
        db, questionnaire
    )

    return render_template(
        "questionnaire_editor.html",
        questionnaire=questionnaire,
        questions=questions,
        can_edit=can_edit
    )


# ==========================================
# ADD A QUESTION
# ==========================================

@app.route(
    "/provider/questionnaires/<int:questionnaire_id>/questions/add",
    methods=["POST"]
)
@role_required("service_provider")
def add_question(questionnaire_id):
    user = current_user()
    db = get_db()

    questionnaire = db.execute(
        """
        SELECT *
        FROM questionnaires
        WHERE id = ? AND created_by = ?
        """,
        (questionnaire_id, user["id"])
    ).fetchone()

    if questionnaire is None:
        abort(404)

    if not questionnaire_is_editable(db, questionnaire):
        abort(409)

    version = db.execute(
        """
        SELECT id
        FROM questionnaire_versions
        WHERE questionnaire_id = ?
        ORDER BY version_number DESC
        LIMIT 1
        """,
        (questionnaire_id,)
    ).fetchone()

    if version is None:
        abort(409)

    question_text = request.form.get(
        "question_text", ""
    ).strip()
    question_type = request.form.get(
        "question_type", ""
    ).strip()
    option_one = request.form.get(
        "option_one", ""
    ).strip()
    option_two = request.form.get(
        "option_two", ""
    ).strip()

    is_required = (
        1 if request.form.get("is_required") == "1"
        else 0
    )

    allowed_types = (
        "text", "multiple_choice", "number", "date"
    )

    if (
        not question_text
        or len(question_text) > 500
        or question_type not in allowed_types
    ):
        flash("Enter valid question details.", "error")
        return redirect(
            url_for(
                "edit_questionnaire",
                questionnaire_id=questionnaire_id
            )
        )

    if question_type == "multiple_choice":
        if not option_one or not option_two:
            flash(
                "Multiple-choice questions need two options.",
                "error"
            )
            return redirect(
                url_for(
                    "edit_questionnaire",
                    questionnaire_id=questionnaire_id
                )
            )

        if (
            len(option_one) > 150
            or len(option_two) > 150
            or option_one == option_two
        ):
            flash(
                "Provide two different options of up to 150 characters.",
                "error"
            )
            return redirect(
                url_for(
                    "edit_questionnaire",
                    questionnaire_id=questionnaire_id
                )
            )
    else:
        option_one = None
        option_two = None

    next_position = db.execute(
        """
        SELECT COALESCE(MAX(position), 0) + 1
        FROM questions
        WHERE questionnaire_version_id = ?
        """,
        (version["id"],)
    ).fetchone()[0]

    db.execute(
        """
        INSERT INTO questions (
            questionnaire_version_id,
            question_text,
            question_type,
            position,
            is_required,
            is_active,
            option_one,
            option_two
        )
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (
            version["id"],
            question_text,
            question_type,
            next_position,
            is_required,
            option_one,
            option_two
        )
    )

    db.execute(
        """
        UPDATE questionnaires
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (questionnaire_id,)
    )
    db.commit()

    flash("Question added successfully!", "success")
    return redirect(
        url_for(
            "edit_questionnaire",
            questionnaire_id=questionnaire_id
        )
    )


# ==========================================
# EDIT AN EXISTING QUESTION
# ==========================================

@app.route(
    "/provider/questionnaires/<int:questionnaire_id>/questions/<int:question_id>/edit",
    methods=["GET", "POST"]
)
@role_required("service_provider")
def edit_question(questionnaire_id, question_id):
    user = current_user()
    db = get_db()

    questionnaire = db.execute(
        """
        SELECT *
        FROM questionnaires
        WHERE id = ? AND created_by = ?
        """,
        (questionnaire_id, user["id"])
    ).fetchone()

    if questionnaire is None:
        abort(404)

    if not questionnaire_is_editable(db, questionnaire):
        abort(409)

    version = db.execute(
        """
        SELECT id
        FROM questionnaire_versions
        WHERE questionnaire_id = ?
        ORDER BY version_number DESC
        LIMIT 1
        """,
        (questionnaire_id,)
    ).fetchone()

    if version is None:
        abort(404)

    question = db.execute(
        """
        SELECT *
        FROM questions
        WHERE id = ?
          AND questionnaire_version_id = ?
        """,
        (question_id, version["id"])
    ).fetchone()

    if question is None:
        abort(404)

    if request.method == "GET":
        return render_template(
            "edit_question.html",
            questionnaire=questionnaire,
            question=question
        )

    question_text = request.form.get(
        "question_text", ""
    ).strip()
    question_type = request.form.get(
        "question_type", ""
    ).strip()
    option_one = request.form.get(
        "option_one", ""
    ).strip()
    option_two = request.form.get(
        "option_two", ""
    ).strip()

    is_required = (
        1 if request.form.get("is_required") == "1"
        else 0
    )

    allowed_types = (
        "text", "multiple_choice", "number", "date"
    )

    if (
        not question_text
        or len(question_text) > 500
        or question_type not in allowed_types
    ):
        flash(
            "Please enter valid question details.",
            "error"
        )
        return redirect(
            url_for(
                "edit_question",
                questionnaire_id=questionnaire_id,
                question_id=question_id
            )
        )

    if question_type == "multiple_choice":
        if (
            not option_one
            or not option_two
            or len(option_one) > 150
            or len(option_two) > 150
            or option_one == option_two
        ):
            flash(
                "Enter two different options, each under 151 characters.",
                "error"
            )
            return redirect(
                url_for(
                    "edit_question",
                    questionnaire_id=questionnaire_id,
                    question_id=question_id
                )
            )
    else:
        option_one = None
        option_two = None

    db.execute(
        """
        UPDATE questions
        SET question_text = ?,
            question_type = ?,
            is_required = ?,
            option_one = ?,
            option_two = ?
        WHERE id = ?
          AND questionnaire_version_id = ?
        """,
        (
            question_text,
            question_type,
            is_required,
            option_one,
            option_two,
            question_id,
            version["id"]
        )
    )

    db.execute(
        """
        UPDATE questionnaires
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND created_by = ?
        """,
        (questionnaire_id, user["id"])
    )
    db.commit()

    flash("Question updated successfully!", "success")
    return redirect(
        url_for(
            "edit_questionnaire",
            questionnaire_id=questionnaire_id
        )
    )


# ==========================================
# DELETE QUESTION
# ==========================================

@app.route(
    "/provider/questionnaires/<int:questionnaire_id>/questions/<int:question_id>/delete",
    methods=["POST"]
)
@role_required("service_provider")
def delete_question(questionnaire_id, question_id):
    user = current_user()
    db = get_db()

    questionnaire = db.execute(
        """
        SELECT *
        FROM questionnaires
        WHERE id = ? AND created_by = ?
        """,
        (questionnaire_id, user["id"])
    ).fetchone()

    if questionnaire is None:
        abort(404)

    if not questionnaire_is_editable(db, questionnaire):
        abort(409)

    version = db.execute(
        """
        SELECT id
        FROM questionnaire_versions
        WHERE questionnaire_id = ?
        ORDER BY version_number DESC
        LIMIT 1
        """,
        (questionnaire_id,)
    ).fetchone()

    if version is None:
        abort(404)

    question = db.execute(
        """
        SELECT id
        FROM questions
        WHERE id = ?
          AND questionnaire_version_id = ?
        """,
        (question_id, version["id"])
    ).fetchone()

    if question is None:
        abort(404)

    try:
        db.execute(
            """
            DELETE FROM questions
            WHERE id = ?
              AND questionnaire_version_id = ?
            """,
            (question_id, version["id"])
        )

        remaining = db.execute(
            """
            SELECT id
            FROM questions
            WHERE questionnaire_version_id = ?
            ORDER BY position ASC, id ASC
            """,
            (version["id"],)
        ).fetchall()

        for position, row in enumerate(remaining, start=1):
            db.execute(
                """
                UPDATE questions
                SET position = ?
                WHERE id = ?
                """,
                (position, row["id"])
            )

        db.execute(
            """
            UPDATE questionnaires
            SET updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND created_by = ?
            """,
            (questionnaire_id, user["id"])
        )
        db.commit()

    except Exception:
        db.rollback()
        raise

    flash(
        "Question deleted successfully.",
        "success"
    )
    return redirect(
        url_for(
            "edit_questionnaire",
            questionnaire_id=questionnaire_id
        )
    )


# ==========================================
# ACTIVATE QUESTIONNAIRE
# ==========================================

@app.route(
    "/provider/questionnaires/<int:questionnaire_id>/activate",
    methods=["POST"]
)
@role_required("service_provider")
def activate_questionnaire(questionnaire_id):
    db = get_db()
    user = current_user()

    questionnaire = db.execute(
        """
        SELECT *
        FROM questionnaires
        WHERE id = ? AND created_by = ?
        """,
        (questionnaire_id, user["id"])
    ).fetchone()

    if questionnaire is None:
        abort(404)

    if questionnaire["status"] == "active":
        return redirect(
            url_for("questionnaire_management")
        )

    version = latest_questionnaire_version(
        db, questionnaire_id
    )

    if version is None:
        abort(409)

    question_count = db.execute(
        """
        SELECT COUNT(*)
        FROM questions
        WHERE questionnaire_version_id = ?
          AND is_active = 1
        """,
        (version["id"],)
    ).fetchone()[0]

    if question_count == 0:
        flash(
            "Add at least one question before activation.",
            "error"
        )
        return redirect(
            url_for(
                "edit_questionnaire",
                questionnaire_id=questionnaire_id
            )
        )

    invalid_options = db.execute(
        """
        SELECT COUNT(*)
        FROM questions
        WHERE questionnaire_version_id = ?
          AND is_active = 1
          AND question_type = 'multiple_choice'
          AND (
              TRIM(COALESCE(option_one, '')) = ''
              OR TRIM(COALESCE(option_two, '')) = ''
              OR LOWER(TRIM(option_one)) =
                 LOWER(TRIM(option_two))
          )
        """,
        (version["id"],)
    ).fetchone()[0]

    if invalid_options:
        flash(
            "Check the multiple-choice options before activation.",
            "error"
        )
        return redirect(
            url_for(
                "edit_questionnaire",
                questionnaire_id=questionnaire_id
            )
        )

    if not version_is_published(db, version["id"]):
        db.execute(
            """
            INSERT INTO questionnaire_publications (
                questionnaire_id,
                questionnaire_version_id,
                title_snapshot,
                description_snapshot
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                questionnaire_id,
                version["id"],
                questionnaire["title"],
                questionnaire["description"]
            )
        )

    db.execute(
        """
        UPDATE questionnaires
        SET status = 'active',
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND created_by = ?
        """,
        (questionnaire_id, user["id"])
    )
    db.commit()

    flash(
        "Questionnaire activated successfully.",
        "success"
    )
    return redirect(url_for("questionnaire_management"))


# ==========================================
# DEACTIVATE QUESTIONNAIRE
# ==========================================

@app.route(
    "/provider/questionnaires/<int:questionnaire_id>/deactivate",
    methods=["POST"]
)
@role_required("service_provider")
def deactivate_questionnaire(questionnaire_id):
    db = get_db()
    user = current_user()

    questionnaire = db.execute(
        """
        SELECT id
        FROM questionnaires
        WHERE id = ? AND created_by = ?
        """,
        (questionnaire_id, user["id"])
    ).fetchone()

    if questionnaire is None:
        abort(404)

    db.execute(
        """
        UPDATE questionnaires
        SET status = 'inactive',
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND created_by = ?
        """,
        (questionnaire_id, user["id"])
    )
    db.commit()

    flash(
        "Questionnaire deactivated successfully.",
        "success"
    )
    return redirect(url_for("questionnaire_management"))


# ==========================================
# CREATE NEW QUESTIONNAIRE VERSION
# ==========================================

@app.route(
    "/provider/questionnaires/<int:questionnaire_id>/versions/new",
    methods=["POST"]
)
@role_required("service_provider")
def create_new_questionnaire_version(questionnaire_id):
    db = get_db()
    user = current_user()

    questionnaire = db.execute(
        """
        SELECT *
        FROM questionnaires
        WHERE id = ? AND created_by = ?
        """,
        (questionnaire_id, user["id"])
    ).fetchone()

    if questionnaire is None:
        abort(404)

    if questionnaire["status"] != "inactive":
        abort(409)

    latest = latest_questionnaire_version(
        db, questionnaire_id
    )

    if latest is None:
        abort(409)

    if not version_is_published(db, latest["id"]):
        abort(409)

    new_version_number = latest["version_number"] + 1

    try:
        cursor = db.execute(
            """
            INSERT INTO questionnaire_versions (
                questionnaire_id, version_number
            )
            VALUES (?, ?)
            """,
            (questionnaire_id, new_version_number)
        )

        new_version_id = cursor.lastrowid

        db.execute(
            """
            INSERT INTO questions (
                questionnaire_version_id,
                question_text,
                question_type,
                position,
                is_required,
                is_active,
                option_one,
                option_two
            )
            SELECT
                ?,
                question_text,
                question_type,
                position,
                is_required,
                is_active,
                option_one,
                option_two
            FROM questions
            WHERE questionnaire_version_id = ?
            ORDER BY position ASC
            """,
            (new_version_id, latest["id"])
        )

        db.execute(
            """
            UPDATE questionnaires
            SET updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND created_by = ?
            """,
            (questionnaire_id, user["id"])
        )
        db.commit()

    except Exception:
        db.rollback()
        raise

    flash(
        f"Version {new_version_number} created successfully. "
        "You can now edit its questions.",
        "success"
    )
    return redirect(
        url_for(
            "edit_questionnaire",
            questionnaire_id=questionnaire_id
        )
    )


# ==========================================
# ADAPTIVE RULE MANAGEMENT
# ==========================================

@app.route(
    "/provider/questionnaires/<int:questionnaire_id>/rules",
    methods=["GET", "POST"]
)
@role_required("service_provider")
def manage_adaptive_rules(questionnaire_id):
    db = get_db()
    user = current_user()

    questionnaire = db.execute(
        """
        SELECT *
        FROM questionnaires
        WHERE id = ? AND created_by = ?
        """,
        (questionnaire_id, user["id"])
    ).fetchone()

    if questionnaire is None:
        abort(404)

    version = latest_questionnaire_version(
        db, questionnaire_id
    )

    if version is None:
        abort(404)

    can_edit = questionnaire_is_editable(
        db, questionnaire
    )

    questions = db.execute(
        """
        SELECT
            id,
            question_text,
            question_type,
            position,
            option_one,
            option_two
        FROM questions
        WHERE questionnaire_version_id = ?
          AND is_active = 1
        ORDER BY position ASC, id ASC
        """,
        (version["id"],)
    ).fetchall()

    if request.method == "POST":
        if not can_edit:
            abort(409)

        source_id = request.form.get(
            "source_question_id", type=int
        )
        target_id = request.form.get(
            "target_question_id", type=int
        )
        expected_answer = request.form.get(
            "expected_answer", ""
        ).strip()

        source = next(
            (
                q for q in questions
                if q["id"] == source_id
            ),
            None
        )
        target = next(
            (
                q for q in questions
                if q["id"] == target_id
            ),
            None
        )

        if source is None or target is None:
            flash(
                "Please select valid questions.",
                "error"
            )
            return redirect(
                url_for(
                    "manage_adaptive_rules",
                    questionnaire_id=questionnaire_id
                )
            )

        if source["question_type"] != "multiple_choice":
            flash(
                "The controlling question must be multiple choice.",
                "error"
            )
            return redirect(
                url_for(
                    "manage_adaptive_rules",
                    questionnaire_id=questionnaire_id
                )
            )

        if source["position"] >= target["position"]:
            flash(
                "The follow-up question must appear after "
                "the controlling question.",
                "error"
            )
            return redirect(
                url_for(
                    "manage_adaptive_rules",
                    questionnaire_id=questionnaire_id
                )
            )

        valid_answers = (
            source["option_one"],
            source["option_two"]
        )

        if expected_answer not in valid_answers:
            flash(
                "Select an answer belonging to the controlling question.",
                "error"
            )
            return redirect(
                url_for(
                    "manage_adaptive_rules",
                    questionnaire_id=questionnaire_id
                )
            )

        try:
            db.execute(
                """
                INSERT INTO adaptive_rules (
                    questionnaire_version_id,
                    source_question_id,
                    target_question_id,
                    expected_answer
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    version["id"],
                    source_id,
                    target_id,
                    expected_answer
                )
            )
            db.commit()

        except IntegrityError:
            db.rollback()
            flash(
                "This follow-up question already has an adaptive rule.",
                "error"
            )
            return redirect(
                url_for(
                    "manage_adaptive_rules",
                    questionnaire_id=questionnaire_id
                )
            )

        flash(
            "Adaptive rule created successfully!",
            "success"
        )
        return redirect(
            url_for(
                "manage_adaptive_rules",
                questionnaire_id=questionnaire_id
            )
        )

    rules = db.execute(
        """
        SELECT
            r.id,
            r.expected_answer,
            r.source_question_id,
            r.target_question_id,
            source.question_text AS source_question,
            target.question_text AS target_question
        FROM adaptive_rules r
        JOIN questions source
            ON source.id = r.source_question_id
        JOIN questions target
            ON target.id = r.target_question_id
        WHERE r.questionnaire_version_id = ?
        ORDER BY r.id DESC
        """,
        (version["id"],)
    ).fetchall()

    return render_template(
        "adaptive_rules.html",
        questionnaire=questionnaire,
        version=version,
        questions=questions,
        rules=rules,
        can_edit=can_edit
    )


# ==========================================
# QUESTIONNAIRE DETAILS REDIRECT
# ==========================================

@app.route(
    "/provider/questionnaires/<int:questionnaire_id>"
)
@role_required("service_provider")
def questionnaire_detail(questionnaire_id):
    return redirect(
        url_for(
            "edit_questionnaire",
            questionnaire_id=questionnaire_id
        )
    )


def answer_snapshot(db, brief_id):
    """Keep question labels alongside answers so history remains readable."""
    return [dict(row) for row in db.execute(
        """
        SELECT q.id AS question_id, q.position, q.question_text, r.answer_text
        FROM brief_responses r
        JOIN project_briefs pb ON pb.id = r.brief_id
        JOIN questions q ON q.id = r.question_id
        WHERE r.brief_id = ? AND q.questionnaire_version_id = pb.questionnaire_version_id
        ORDER BY q.position, q.id
        """, (brief_id,)
    ).fetchall()]


def revision_request(db, brief_id):
    return db.execute(
        """
        SELECT br.id AS review_id, br.comment, br.created_at,
               c.id AS cycle_id, COALESCE(c.response_text, '') AS response_text,
               c.resubmitted_at
        FROM brief_reviews br
        LEFT JOIN brief_revision_cycles c ON c.review_id = br.id AND c.brief_id = br.brief_id
        WHERE br.brief_id = ? AND br.id = (
            SELECT MAX(id) FROM brief_reviews WHERE brief_id = ?
        ) AND br.decision = 'revision_requested'
        """, (brief_id, brief_id)
    ).fetchone()


def ensure_revision_cycle(db, brief_id, review_id):
    # Caller holds the write transaction. Also supports existing revision requests
    # created before Step 85.3, before any new edits replace their saved answers.
    db.execute(
        """
        INSERT INTO brief_revision_cycles (brief_id, review_id, requested_answers_json)
        VALUES (?, ?, ?) ON CONFLICT(review_id) DO NOTHING
        """, (brief_id, review_id, json.dumps(answer_snapshot(db, brief_id)))
    )
    return db.execute(
        "SELECT * FROM brief_revision_cycles WHERE brief_id = ? AND review_id = ?",
        (brief_id, review_id)
    ).fetchone()


def editable_revision_cycle(db, brief_id):
    current = revision_request(db, brief_id)
    if (current is None or current['resubmitted_at'] is not None
            or request.form.get('revision_review_id', type=int) != current['review_id']):
        abort(409, "This revision request has changed. Reload the questionnaire before saving.")
    return ensure_revision_cycle(db, brief_id, current['review_id'])


def revision_history_records(db, brief_id, include_pending=False):
    rows = db.execute(
        """
        SELECT c.*, br.comment AS provider_feedback, br.created_at AS requested_at,
               u.full_name AS reviewer_name
        FROM brief_revision_cycles c
        JOIN brief_reviews br ON br.id = c.review_id AND br.brief_id = c.brief_id
        JOIN users u ON u.id = br.reviewer_id
        WHERE c.brief_id = ? AND (? OR c.resubmitted_at IS NOT NULL)
        ORDER BY c.review_id DESC
        """, (brief_id, include_pending)
    ).fetchall()
    return [dict(row, previous_answers=json.loads(row['requested_answers_json']),
                 revised_answers=json.loads(row['resubmitted_answers_json'] or '[]'))
            for row in rows]


# ==========================================
# CLIENT QUESTIONNAIRE
# LOAD PUBLISHED VERSION AND SAVED ANSWERS
# ==========================================

@app.route(
    "/client/questionnaires/<int:questionnaire_id>",
    methods=["GET"]
)
@role_required("client")
def client_questionnaire(questionnaire_id):
    db = get_db()
    client = current_user()
    brief_id = request.args.get("brief_id", type=int)
    saved_answers = {}

    if brief_id is not None:
        questionnaire = db.execute(
            """

    SELECT
        q.id,
        pb.status AS brief_status,
        pb.completeness_percentage,
        p.title_snapshot AS title,
        p.description_snapshot AS description,
        v.id AS version_id,
        v.version_number

            FROM project_briefs AS pb
            JOIN questionnaire_versions AS v
                ON v.id = pb.questionnaire_version_id
            JOIN questionnaires AS q
                ON q.id = v.questionnaire_id
            JOIN questionnaire_publications AS p
                ON p.questionnaire_version_id = v.id
            WHERE pb.id = ?
              AND pb.client_id = ?
              AND q.id = ?
            """,
            (brief_id, client["id"], questionnaire_id)
        ).fetchone()

        if questionnaire is None:
            abort(404)

        rows = db.execute(
            """
            SELECT r.question_id, r.answer_text
            FROM brief_responses AS r
            JOIN questions AS q
                ON q.id = r.question_id
            WHERE r.brief_id = ?
              AND q.questionnaire_version_id = ?
            """,
            (brief_id, questionnaire["version_id"])
        ).fetchall()

        saved_answers = {
            str(row["question_id"]): row["answer_text"]
            for row in rows
        }

    else:
        questionnaire = db.execute(
            """
            SELECT
                q.id,
                q.title,
                q.description,
                v.id AS version_id,
                v.version_number
            FROM questionnaires AS q
            JOIN questionnaire_versions AS v
                ON v.questionnaire_id = q.id
            JOIN questionnaire_publications AS p
                ON p.questionnaire_version_id = v.id
            WHERE q.id = ?
              AND q.status = 'active'
            ORDER BY v.version_number DESC
            LIMIT 1
            """,
            (questionnaire_id,)
        ).fetchone()

        if questionnaire is None:
            abort(404)

    questions = db.execute(
        """
        SELECT
            id,
            question_text,
            question_type,
            position,
            is_required,
            option_one,
            option_two
        FROM questions
        WHERE questionnaire_version_id = ?
          AND is_active = 1
        ORDER BY position ASC, id ASC
        """,
        (questionnaire["version_id"],)
    ).fetchall()

    rules = db.execute(
        """
        SELECT
            r.source_question_id,
            r.target_question_id,
            r.expected_answer
        FROM adaptive_rules AS r
        JOIN questions AS source
            ON source.id = r.source_question_id
        JOIN questions AS target
            ON target.id = r.target_question_id
        WHERE r.questionnaire_version_id = ?
          AND source.questionnaire_version_id = ?
          AND target.questionnaire_version_id = ?
          AND source.is_active = 1
          AND target.is_active = 1
        """,
        (
            questionnaire["version_id"],
            questionnaire["version_id"],
            questionnaire["version_id"]
        )
    ).fetchall()


    review_history = db.execute(
        "SELECT decision, comment, created_at FROM brief_reviews "
        "WHERE brief_id = ? ORDER BY created_at DESC, id DESC", (brief_id,)
    ).fetchall() if brief_id is not None else []

    return render_template(
        "client_questionnaire.html",
        questionnaire=questionnaire,
        questions=questions,
        adaptive_rules=[dict(rule) for rule in rules],
        brief_id=brief_id,
        saved_answers=saved_answers,
        review_history=review_history,
        revision_request=(revision_request(db, brief_id)
                          if brief_id is not None and questionnaire["brief_status"] == "revision_requested"
                          else None),
        revision_cycles=revision_history_records(db, brief_id)
                        if brief_id is not None else [],
        brief_status=(
            questionnaire["brief_status"]
            if brief_id is not None
            else None
        )
    )


# ==========================================
# STEP 84.6 - SAVE CLIENT QUESTIONNAIRE DRAFT
# ==========================================

@app.route(
    "/briefs/<int:brief_id>/answers",
    methods=["POST"]
)
@role_required("client")
def save_brief_answers(brief_id):
    questionnaire_id = persist_brief_answers(brief_id)
    is_revision = get_db().execute("SELECT status FROM project_briefs WHERE id = ?", (brief_id,)).fetchone()["status"] == "revision_requested"
    flash("Your changes and revision response have been saved." if is_revision
          else "Your questionnaire draft has been saved.", "success")
    return redirect(url_for("client_questionnaire",
                            questionnaire_id=questionnaire_id,
                            brief_id=brief_id))


def persist_brief_answers(brief_id, commit=True):
    db = get_db()
    client = current_user()

    # Serialize writers before reading answers or status.
    if not db.in_transaction:
        db.execute("BEGIN IMMEDIATE")

    # Verify that the client owns this draft.
    brief = db.execute(
        """
        SELECT id, questionnaire_version_id, status
        FROM project_briefs
        WHERE id = ?
          AND client_id = ?
          AND status IN ('draft', 'revision_requested')
        """,
        (brief_id, client["id"])
    ).fetchone()

    if brief is None:
        abort(404)

    cycle = None
    previous_answers = {}
    if brief["status"] == "revision_requested":
        cycle = editable_revision_cycle(db, brief_id)
        response_text = request.form.get("revision_response", cycle["response_text"]).strip()
        if len(response_text) > 5000:
            abort(400, "Your revision response must be at most 5000 characters.")
        previous_answers = {str(row["question_id"]): row["answer_text"]
                            for row in answer_snapshot(db, brief_id)}
    elif "revision_response" in request.form or "revision_review_id" in request.form:
        abort(409, "Revision responses can only be edited when revisions are requested.")

    version_id = brief["questionnaire_version_id"]

    version = db.execute(
        """
        SELECT questionnaire_id
        FROM questionnaire_versions
        WHERE id = ?
        """,
        (version_id,)
    ).fetchone()

    if version is None:
        abort(404)

    # Load active questions belonging to this version.
    questions = db.execute(
        """
        SELECT
            id,
            question_type,
            is_required,
            option_one,
            option_two
        FROM questions
        WHERE questionnaire_version_id = ?
          AND is_active = 1
        ORDER BY position ASC, id ASC
        """,
        (version_id,)
    ).fetchall()

    # Load adaptive rules for the same version.
    rules = db.execute(
        """
        SELECT
            source_question_id,
            target_question_id,
            expected_answer
        FROM adaptive_rules
        WHERE questionnaire_version_id = ?
        """,
        (version_id,)
    ).fetchall()

    rules_by_target = {
        rule["target_question_id"]: rule
        for rule in rules
    }

    answers = {}
    visible = {}

    required_total = 0
    required_completed = 0

    # Process questions in their saved display order.
    for question in questions:
        question_id = question["id"]
        rule = rules_by_target.get(question_id)
        applicable = True

        if rule is not None:
            source_id = rule["source_question_id"]
            applicable = (
                visible.get(source_id, False)
                and answers.get(source_id, "")
                == rule["expected_answer"]
            )

        visible[question_id] = applicable

        # Ignore answers belonging to hidden questions.
        if not applicable:
            continue

        answer = request.form.get(
            f"answer_{question_id}", previous_answers.get(str(question_id), "")
        ).strip()

        if len(answer) > 5000:
            abort(400, "An answer is too long.")

        # Validate multiple-choice answers.
        if (
            answer
            and question["question_type"] == "multiple_choice"
        ):
            if answer not in (
                question["option_one"],
                question["option_two"]
            ):
                abort(
                    400,
                    "Invalid multiple-choice answer."
                )

        # Validate numerical answers.
        elif (
            answer
            and question["question_type"] == "number"
        ):
            try:
                number = Decimal(answer)
            except InvalidOperation:
                abort(400, "Invalid number.")

            if not number.is_finite():
                abort(400, "Invalid number.")

        # Validate date answers.
        elif (
            answer
            and question["question_type"] == "date"
        ):
            try:
                date.fromisoformat(answer)
            except ValueError:
                abort(400, "Invalid date.")

        # Retain nonempty answers.
        if answer:
            answers[question_id] = answer

        # Calculate applicable required-question progress.
        if question["is_required"]:
            required_total += 1
            if answer:
                required_completed += 1

    completeness = (
        round(required_completed * 100 / required_total)
        if required_total
        else (100 if answers else 0)
    )

    # Save changes together in one transaction.
    try:
        updated = db.execute(
            """
            UPDATE project_briefs
            SET completeness_percentage = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND client_id = ?
              AND status IN ('draft', 'revision_requested')
            """,
            (
                completeness,
                brief_id,
                client["id"]
            )
        )

        if updated.rowcount != 1:
            db.rollback()
            abort(
                409,
                "This project brief can no longer be edited."
            )

        db.execute(
            """
            DELETE FROM brief_responses
            WHERE brief_id = ?
            """,
            (brief_id,)
        )

        for question_id, answer in answers.items():
            db.execute(
                """
                INSERT INTO brief_responses (
                    brief_id,
                    question_id,
                    answer_text
                )
                VALUES (?, ?, ?)
                """,
                (brief_id, question_id, answer)
            )

        if cycle is not None:
            changed = db.execute(
                "UPDATE brief_revision_cycles SET response_text = ?, response_updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND brief_id = ? AND resubmitted_at IS NULL",
                (response_text, cycle["id"], brief_id)
            )
            if changed.rowcount != 1:
                abort(409, "This revision cycle is already closed.")
        if commit:
            db.commit()

    except Exception:
        db.rollback()
        raise

    return version["questionnaire_id"]


# ==========================================
# STEP 84.9 - SUBMIT BRIEF FOR REVIEW
# ==========================================

@app.route(
    "/briefs/<int:brief_id>/submit",
    methods=["POST"]
)
@app.route("/briefs/<int:brief_id>/resubmit", methods=["POST"], endpoint="resubmit_brief")
@role_required("client")
def submit_brief(brief_id):

    db = get_db()
    client = current_user()

    db.execute("BEGIN IMMEDIATE")

    # Verify ownership and current status.

    brief = db.execute(
        """
        SELECT id, questionnaire_version_id, status
        FROM project_briefs
        WHERE id = ?
          AND client_id = ?
        """,
        (brief_id, client["id"])
    ).fetchone()

    if brief is None:
        abort(404)

    if brief["status"] not in ("draft", "revision_requested"):
        abort(409, "This brief cannot be submitted in its current status.")

    is_revision = brief["status"] == "revision_requested"
    if is_revision != (request.endpoint == "resubmit_brief"):
        abort(409, "Use the action matching this brief's current status.")
    cycle = None
    if is_revision:
        if request.form.get("confirm_resubmission") != "yes":
            abort(400, "Please confirm resubmission before sending your revised brief.")
        cycle = editable_revision_cycle(db, brief_id)
    elif "revision_response" in request.form or "revision_review_id" in request.form:
        abort(409, "An ordinary draft cannot contain a revision response.")

    # The questionnaire submits its current fields, including explicit blanks.
    # Save incomplete drafts too, then explain any missing required answers.
    if request.form.get("save_answers") == "1" or (is_revision and "revision_response" in request.form):
        persist_brief_answers(brief_id, commit=False)

    version_id = brief["questionnaire_version_id"]

    version = db.execute(
        """
        SELECT questionnaire_id
        FROM questionnaire_versions
        WHERE id = ?
        """,
        (version_id,)
    ).fetchone()

    if version is None:
        abort(404)

    questionnaire_url = url_for(
        "client_questionnaire",
        questionnaire_id=version["questionnaire_id"],
        brief_id=brief_id
    )

    if is_revision:
        cycle = db.execute("SELECT * FROM brief_revision_cycles WHERE id = ?", (cycle["id"],)).fetchone()
        if not cycle["response_text"].strip():
            flash("Explain how you addressed the provider's feedback before resubmitting.", "error")
            db.commit()
            return redirect(questionnaire_url)

    # Load the questions for this exact version.

    questions = db.execute(
        """
        SELECT
            id,
            question_type,
            is_required,
            option_one,
            option_two
        FROM questions
        WHERE questionnaire_version_id = ?
          AND is_active = 1
        ORDER BY position ASC, id ASC
        """,
        (version_id,)
    ).fetchall()

    if not questions:
        flash("This questionnaire has no active questions.", "error")
        db.commit()
        return redirect(questionnaire_url)

    # Use responses already saved in SQLite.

    rows = db.execute(
        """
        SELECT r.question_id, r.answer_text
        FROM brief_responses r
        JOIN questions q
            ON q.id = r.question_id
        WHERE r.brief_id = ?
          AND q.questionnaire_version_id = ?
        """,
        (brief_id, version_id)
    ).fetchall()

    answers = {
        row["question_id"]: (row["answer_text"] or "").strip()
        for row in rows
    }

    # Load the adaptive conditions.

    rules = db.execute(
        """
        SELECT
            source_question_id,
            target_question_id,
            expected_answer
        FROM adaptive_rules
        WHERE questionnaire_version_id = ?
        """,
        (version_id,)
    ).fetchall()

    rules_by_target = {
        rule["target_question_id"]: rule
        for rule in rules
    }

    visible = {}
    required_total = 0
    required_completed = 0
    visible_answer_count = 0

    # Validate the actual applicable questions.

    for question in questions:

        question_id = question["id"]
        answer = answers.get(question_id, "")
        rule = rules_by_target.get(question_id)

        applicable = True

        if rule is not None:
            source_id = rule["source_question_id"]

            applicable = (
                visible.get(source_id, False)
                and answers.get(source_id, "")
                == rule["expected_answer"]
            )

        visible[question_id] = applicable

        if not applicable:
            continue

        if question["is_required"]:
            required_total += 1

            if not answer:
                flash(
                    "Complete and save all required answers "
                    "before submitting.",
                    "error"
                )
                db.commit()
                return redirect(questionnaire_url)

            required_completed += 1

        if not answer:
            continue

        visible_answer_count += 1

        if len(answer) > 5000:
            abort(400, "An answer is too long.")

        question_type = question["question_type"]

        if question_type == "multiple_choice":
            if answer not in (
                question["option_one"],
                question["option_two"]
            ):
                abort(400, "Invalid multiple-choice answer.")

        elif question_type == "number":
            try:
                number = Decimal(answer)
            except InvalidOperation:
                abort(400, "Invalid numerical answer.")

            if not number.is_finite():
                abort(400, "Invalid numerical answer.")

        elif question_type == "date":
            try:
                date.fromisoformat(answer)
            except ValueError:
                abort(400, "Invalid date answer.")

    # Prevent empty submissions.

    if visible_answer_count == 0:
        flash(
            "Save your questionnaire answers before submitting.",
            "error"
        )
        db.commit()
        return redirect(questionnaire_url)

    if required_completed != required_total:
        abort(409, "Required answers are incomplete.")

    # Update the brief only if it is still a draft.
    # The status transition is performed atomically.

    try:
        cursor = db.execute(
            """
            UPDATE project_briefs
            SET status = 'submitted',
                completeness_percentage = 100,
                submitted_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
              AND client_id = ?
              AND status IN ('draft', 'revision_requested')
            """,
            (brief_id, client["id"])
        )

        if cursor.rowcount != 1:
            db.rollback()
            abort(409, "This brief cannot be submitted.")

        if is_revision:
            closed = db.execute(
                "UPDATE brief_revision_cycles SET resubmitted_answers_json = ?, "
                "resubmitted_at = CURRENT_TIMESTAMP WHERE id = ? AND brief_id = ? AND resubmitted_at IS NULL",
                (json.dumps(answer_snapshot(db, brief_id)), cycle["id"], brief_id)
            )
            if closed.rowcount != 1:
                abort(409, "This revision cycle has already been submitted.")
        db.commit()

    except Exception:
        db.rollback()
        raise

    flash("Your revised brief has been resubmitted for review." if is_revision
          else "Your brief has been submitted for review.", "success")

    return redirect(
        url_for(
            "client_questionnaire",
            questionnaire_id=version["questionnaire_id"],
            brief_id=brief_id,
            submitted=1
        )
    )

# ==========================================
# RUN ELUNETTE
# ==========================================

if __name__ == "__main__":
    app.run(debug=True)
