
import os
import re
import secrets

from functools import wraps
from sqlite3 import IntegrityError
from flask_wtf.csrf import CSRFProtect

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for
)

from werkzeug.security import (
    check_password_hash,
    generate_password_hash
)

from database import get_db, init_app


# ==========================================
# ELUNETTE WEB APPLICATION
# ==========================================

app = Flask(__name__)

# Flask session configuration
app.config["SECRET_KEY"] = (
    os.environ.get("ELUNETTE_SECRET_KEY")
    or secrets.token_hex(32)
)


app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

# Enable CSRF protection for form submissions
csrf = CSRFProtect(app)

# Connect SQLite database
init_app(app)


# Connect SQLite database
init_app(app)


# ==========================================
# AUTHENTICATION HELPERS
# ==========================================

def current_user():

    user_id = session.get("user_id")

    if user_id is None:
        return None

    db = get_db()

    user = db.execute(
        """
        SELECT id, full_name, email, role, status
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    ).fetchone()

    if user is None or user["status"] != "active":
        session.clear()
        return None

    return user


# ==========================================
# LOGIN REQUIRED
# ==========================================

def login_required(view):

    @wraps(view)
    def protected_view(*args, **kwargs):

        user = current_user()

        if user is None:
            flash(
                "Please log in to continue.",
                "error"
            )
            return redirect(url_for("login"))

        return view(*args, **kwargs)

    return protected_view


# ==========================================
# ROLE-BASED ACCESS CONTROL
# ==========================================

def role_required(required_role):

    def decorator(view):

        @wraps(view)
        def protected_view(*args, **kwargs):

            user = current_user()

            if user is None:
                flash(
                    "Please log in to continue.",
                    "error"
                )
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
        db,
        questionnaire["id"]
    )

    if version is None:
        return False

    return not version_is_published(
        db,
        version["id"]
    )


# ==========================================
# PUBLIC PAGES
# ==========================================

# HOME PAGE

@app.route("/")
def home():
    return render_template("index.html")


# ABOUT PAGE

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

    full_name = request.form.get(
        "full_name", ""
    ).strip()

    email = request.form.get(
        "email", ""
    ).strip().lower()

    password = request.form.get(
        "password", ""
    )

    confirm_password = request.form.get(
        "confirm_password", ""
    )

    # Required fields
    if not all((
        full_name,
        email,
        password,
        confirm_password
    )):
        flash(
            "Please complete all fields.",
            "error"
        )
        return redirect(url_for("register"))

    # Full name validation
    if not 2 <= len(full_name) <= 100:
        flash(
            "Enter a valid full name.",
            "error"
        )
        return redirect(url_for("register"))

    # Email validation
    valid_email = re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+",
        email
    )

    if len(email) > 254 or not valid_email:
        flash(
            "Enter a valid email address.",
            "error"
        )
        return redirect(url_for("register"))

    # Password validation
    if len(password) < 12:
        flash(
            "Password must contain at least 12 characters.",
            "error"
        )
        return redirect(url_for("register"))

    if password != confirm_password:
        flash(
            "Passwords do not match.",
            "error"
        )
        return redirect(url_for("register"))

    # Hash the password
    password_hash = generate_password_hash(password)

    db = get_db()

    try:
        db.execute(
            """
            INSERT INTO users (
                full_name,
                email,
                password_hash,
                role,
                status
            )
            VALUES (?, ?, ?, 'client', 'active')
            """,
            (
                full_name,
                email,
                password_hash
            )
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

    email = request.form.get(
        "email", ""
    ).strip().lower()

    password = request.form.get(
        "password", ""
    )

    db = get_db()

    user = db.execute(
        """
        SELECT *
        FROM users
        WHERE email = ?
        """,
        (email,)
    ).fetchone()

    # Verify login credentials
    if user is None or not check_password_hash(
        user["password_hash"],
        password
    ):
        flash(
            "Invalid email or password.",
            "error"
        )
        return redirect(url_for("login"))

    # Check whether account is active
    if user["status"] != "active":
        flash(
            "This account is inactive.",
            "error"
        )
        return redirect(url_for("login"))

    # Create user session
    session.clear()

    session["user_id"] = user["id"]
    session["user_role"] = user["role"]

    # Redirect according to role
    if user["role"] == "client":
        return redirect(
            url_for("client_dashboard")
        )

    elif user["role"] == "service_provider":
        return redirect(
            url_for("provider_dashboard")
        )

    elif user["role"] == "administrator":
        return redirect(
            url_for("admin_dashboard")
        )

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
# PASSWORD RECOVERY
# DESIGN PREVIEWS ONLY
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

# CLIENT DASHBOARD

@app.route("/dashboard/client")
@app.route("/dashboard/client-preview")
@role_required("client")
def client_dashboard():
    return render_template("client_dashboard.html")


# MY BRIEFS

@app.route("/briefs")
@app.route("/briefs-preview")
@role_required("client")
def my_briefs():
    return render_template("my_briefs.html")



# ==========================================
# CREATE NEW PROJECT BRIEF
# ==========================================


# ==========================================
# STEP 82.4 - CREATE CLIENT PROJECT BRIEF
# ==========================================

@app.route("/briefs/new", methods=["GET", "POST"])
@role_required("client")
def new_brief():

    db = get_db()

    # --------------------------------------
    # CREATE AND SAVE A NEW DRAFT
    # --------------------------------------

    if request.method == "POST":

        user = current_user()

        title = request.form.get(
            "project_title", ""
        ).strip()

        questionnaire_id = request.form.get(
            "questionnaire_id", "",
            type=int
        )

        # Validate the project title
        if not title or len(title) > 150:

            flash(
                "Enter a project title of up to 150 characters.",
                "error"
            )

            return redirect(url_for("new_brief"))

        # Validate the selected questionnaire
        if questionnaire_id is None:

            flash(
                "Please select a questionnaire.",
                "error"
            )

            return redirect(url_for("new_brief"))

        # Get the latest published version
        # of the selected active questionnaire

        questionnaire = db.execute(
            """
            SELECT
                q.id,
                q.title,
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

        # Create the project brief

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

        # Open the questionnaire.
        # The brief ID will be used when we
        # implement response saving.

        return redirect(
            url_for(
                "client_questionnaire",
                questionnaire_id=questionnaire_id,
                brief_id=brief_id
            )
        )

    # --------------------------------------
    # DISPLAY AVAILABLE QUESTIONNAIRES
    # --------------------------------------

    questionnaires = db.execute(
        """
        SELECT
            q.id,
            q.title,
            v.version_number

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


    db = get_db()

    # Retrieve active questionnaires with
    # their latest published versions.

    questionnaires = db.execute(
        """
        SELECT
            q.id,
            q.title,
            v.version_number

        FROM questionnaires AS q

        JOIN questionnaire_versions AS v
            ON v.questionnaire_id = q.id

        JOIN questionnaire_publications AS p
            ON p.questionnaire_version_id = v.id

        WHERE q.status = 'active'

          AND v.version_number = (
              SELECT MAX(v2.version_number)
              FROM questionnaire_versions AS v2

              JOIN questionnaire_publications AS p2
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



# QUESTIONNAIRE PREVIEW

@app.route("/questionnaire-preview")
@role_required("client")
def questionnaire_preview():
    return render_template("questionnaire.html")


# BRIEF PREVIEW

@app.route("/brief-preview")
@role_required("client")
def brief_preview_design():
    return render_template("brief_preview.html")


# BRIEF DETAILS

@app.route("/brief-details-preview")
@role_required("client")
def brief_details_preview():
    return render_template("brief_details.html")


# REVISION HISTORY

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
    return render_template("notifications.html")


# ==========================================
# SERVICE PROVIDER WORKSPACE
# ==========================================

# SERVICE PROVIDER DASHBOARD

@app.route("/dashboard/provider")
@app.route("/dashboard/provider-preview")
@role_required("service_provider")
def provider_dashboard():
    return render_template("provider_dashboard.html")



# ==========================================
# STEP 83 - PROVIDER CLIENT BRIEFS
# ==========================================

@app.route("/provider/briefs")
@role_required("service_provider")
def provider_briefs():

    user = current_user()
    db = get_db()

    # Retrieve briefs submitted to this provider.
    # A provider only sees projects associated
    # with questionnaires they created.

    briefs = db.execute(
        """
        SELECT
            pb.id,
            pb.title,
            pb.status,
            pb.completeness_percentage,
            pb.created_at,
            pb.updated_at,

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
        (user["id"],)
    ).fetchall()

    return render_template(
        "provider_briefs.html",
        briefs=briefs
    )


# REVIEW BRIEF PREVIEW

@app.route("/provider/briefs/review-preview")
@role_required("service_provider")
def review_brief_preview():
    return render_template("review_brief.html")


# QUESTIONNAIRE MANAGEMENT

# ==========================================
# QUESTIONNAIRE MANAGEMENT
# ==========================================

@app.route("/provider/questionnaires")
@role_required("service_provider")
def questionnaire_management():

    user = current_user()
    db = get_db()

    # Get search and filter values
    search_query = request.args.get(
        "search", ""
    ).strip()[:150]

    status_filter = request.args.get(
        "status", ""
    ).strip()

    if status_filter not in (
        "",
        "active",
        "inactive"
    ):
        status_filter = ""

    # Count the provider's questionnaires
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
        WHERE created_by = ?
        """,
        (user["id"],)
    ).fetchone()

    # Retrieve saved questionnaires
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
        status_filter=status_filter
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

    # Display the questionnaire editor
    if request.method == "GET":
        return render_template(
            "questionnaire_editor.html"
        )

    # Process questionnaire creation
    form_action = request.form.get("form_action")

    if form_action != "save_template":
        abort(400)

    title = request.form.get(
        "title", ""
    ).strip()

    description = request.form.get(
        "description", ""
    ).strip()

    # Validate questionnaire information
    if not title or not description:

        flash(
            "Please complete all questionnaire fields.",
            "error"
        )

        return redirect(
            url_for("create_questionnaire")
        )

    if len(title) > 150:

        flash(
            "Questionnaire title cannot exceed 150 characters.",
            "error"
        )

        return redirect(
            url_for("create_questionnaire")
        )

    if len(description) > 1000:

        flash(
            "Description cannot exceed 1000 characters.",
            "error"
        )

        return redirect(
            url_for("create_questionnaire")
        )

    # Identify the logged-in service provider
    user = current_user()

    db = get_db()

    try:

        # Save the questionnaire
        cursor = db.execute(
            """
            INSERT INTO questionnaires (
                title,
                description,
                created_by,
                status
            )
            VALUES (?, ?, ?, 'inactive')
            """,
            (
                title,
                description,
                user["id"]
            )
        )

        questionnaire_id = cursor.lastrowid

        # Create the first questionnaire version
        db.execute(
            """
            INSERT INTO questionnaire_versions (
                questionnaire_id,
                version_number
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

    return redirect(
        url_for("create_questionnaire")
    )



# ADAPTIVE RULES PREVIEW

@app.route("/provider/questionnaires/rules-preview")
@role_required("service_provider")
def adaptive_rules_preview():
    return render_template("adaptive_rules.html")


# ==========================================
# ADMINISTRATOR WORKSPACE
# ==========================================

# ADMIN DASHBOARD

@app.route("/dashboard/admin")
@app.route("/dashboard/admin-preview")
@role_required("administrator")
def admin_dashboard():
    return render_template("admin_dashboard.html")


# USER MANAGEMENT

@app.route("/admin/users")
@role_required("administrator")
def user_management():
    return render_template("user_management.html")


# CREATE USER ACCOUNT

@app.route("/admin/users/new", methods=["GET"])
@role_required("administrator")
def create_user():
    return render_template("create_user.html")


# EDIT USER ACCOUNT PREVIEW

@app.route("/admin/users/edit-preview", methods=["GET"])
@role_required("administrator")
def edit_user_preview():
    return render_template("edit_user.html")


# ==========================================
# RUN ELUNETTE
# ==========================================

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

    # Retrieve only questionnaires owned by this provider
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


    # LOAD SAVED QUESTIONNAIRE QUESTIONS

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


    # Check whether the questionnaire can be edited
    can_edit = questionnaire_is_editable(
        db,
        questionnaire
    )

    return render_template(
        "questionnaire_editor.html",
        questionnaire=questionnaire,
        questions=questions,
        can_edit=can_edit
    )



# ==========================================
# ADD A QUESTION TO A QUESTIONNAIRE
# ==========================================

@app.route(
    "/provider/questionnaires/<int:questionnaire_id>/questions/add",
    methods=["POST"]
)
@role_required("service_provider")
def add_question(questionnaire_id):

    user = current_user()
    db = get_db()

    # Check questionnaire ownership
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

    # Only inactive questionnaires can be edited
    
        if not questionnaire_is_editable(db, questionnaire):
            abort(409)


    # Get the latest questionnaire version
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

    # Collect question details
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

    # Validate question
    allowed_types = (
        "text",
        "multiple_choice",
        "number",
        "date"
    )

    if (
        not question_text
        or len(question_text) > 500
        or question_type not in allowed_types
    ):

        flash(
            "Enter valid question details.",
            "error"
        )

        return redirect(
            url_for(
                "edit_questionnaire",
                questionnaire_id=questionnaire_id
            )
        )

    # Validate multiple-choice options
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

        if len(option_one) > 150 or len(option_two) > 150:
            flash(
                "Each option must be 150 characters or fewer.",
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

    # Determine question order
    next_position = db.execute(
        """
        SELECT COALESCE(MAX(position), 0) + 1
        FROM questions
        WHERE questionnaire_version_id = ?
        """,
        (version["id"],)
    ).fetchone()[0]

    # Save the question
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

    # Update questionnaire timestamp
    db.execute(
        """
        UPDATE questionnaires
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (questionnaire_id,)
    )

    db.commit()

    flash(
        "Question added successfully!",
        "success"
    )

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

    # Confirm questionnaire ownership
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

    # Active questionnaires cannot be edited

    if not questionnaire_is_editable(db, questionnaire):
        abort(409)


    # Get the latest questionnaire version
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

    # Retrieve the selected question
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

    # Display editing form
    if request.method == "GET":
        return render_template(
            "edit_question.html",
            questionnaire=questionnaire,
            question=question
        )

    # Collect updated information
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
        "text",
        "multiple_choice",
        "number",
        "date"
    )

    # Validate question details
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

    # Validate multiple-choice options
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

    # Save updated question
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

    flash(
        "Question updated successfully!",
        "success"
    )

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

    # Confirm questionnaire ownership
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

    # Prevent changes to active questionnaires

    if not questionnaire_is_editable(db, questionnaire):
        abort(409)


    # Retrieve the latest version
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

    # Confirm that the question belongs to this version
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
        # Delete the selected question
        db.execute(
            """
            DELETE FROM questions
            WHERE id = ?
              AND questionnaire_version_id = ?
            """,
            (question_id, version["id"])
        )

        # Recalculate remaining question positions
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

        # Record when the questionnaire was modified
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
        db,
        questionnaire_id
    )

    if version is None:
        abort(409)

    # A questionnaire needs at least one question
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

    # Check multiple-choice answers
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

    # Preserve this version on first publication
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

    return redirect(
        url_for("questionnaire_management")
    )


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

    return redirect(
        url_for("questionnaire_management")
    )

# ==========================================
# CREATE A NEW QUESTIONNAIRE VERSION
# ==========================================

@app.route(
    "/provider/questionnaires/<int:questionnaire_id>/versions/new",
    methods=["POST"]
)
@role_required("service_provider")
def create_new_questionnaire_version(questionnaire_id):

    db = get_db()
    user = current_user()

    # Confirm questionnaire ownership
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

    # A new version can only be created
    # after deactivating the questionnaire
    if questionnaire["status"] != "inactive":
        abort(409)

    latest = latest_questionnaire_version(
        db,
        questionnaire_id
    )

    if latest is None:
        abort(409)

    # Prevent creating multiple unfinished drafts
    if not version_is_published(db, latest["id"]):
        abort(409)

    new_version_number = latest["version_number"] + 1

    try:

        # Create the new draft version
        cursor = db.execute(
            """
            INSERT INTO questionnaire_versions (
                questionnaire_id,
                version_number
            )
            VALUES (?, ?)
            """,
            (
                questionnaire_id,
                new_version_number
            )
        )

        new_version_id = cursor.lastrowid

        # Copy questions from the previous version
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
            (
                new_version_id,
                latest["id"]
            )
        )

        # Update modification date
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
# ELUNETTE - ADAPTIVE RULE MANAGEMENT
# ==========================================

@app.route(
    "/provider/questionnaires/<int:questionnaire_id>/rules",
    methods=["GET", "POST"]
)
@role_required("service_provider")
def manage_adaptive_rules(questionnaire_id):

    db = get_db()
    user = current_user()

    # Find questionnaire belonging to this provider
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

    # Retrieve latest questionnaire version
    version = latest_questionnaire_version(
        db, questionnaire_id
    )

    if version is None:
        abort(404)

    can_edit = questionnaire_is_editable(
        db, questionnaire
    )

    # Retrieve questions for this version
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

    # ======================================
    # SAVE NEW ADAPTIVE RULE
    # ======================================

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

        # Find the selected questions
        source = next(
            (q for q in questions if q["id"] == source_id),
            None
        )

        target = next(
            (q for q in questions if q["id"] == target_id),
            None
        )

        # Both questions must belong to this version
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

        # Source must be multiple choice
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

        # Follow-up must come after source
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

        # Answer must match an existing option
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

        # Store rule in SQLite
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
                "This follow-up question already has "
                "an adaptive rule.",
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

    # ======================================
    # LOAD EXISTING RULES
    # ======================================

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

@app.route("/provider/questionnaires/<int:questionnaire_id>")
@role_required("service_provider")
def questionnaire_detail(questionnaire_id):

    return redirect(
        url_for(
            "edit_questionnaire",
            questionnaire_id=questionnaire_id
        )
    )

# ==========================================
# CLIENT QUESTIONNAIRE
# ==========================================

@app.route(
    "/client/questionnaires/<int:questionnaire_id>",
    methods=["GET"]
)
@role_required("client")
def client_questionnaire(questionnaire_id):

    db = get_db()

    # Retrieve the latest published version
    # of an active questionnaire.
    questionnaire = db.execute(
        """
        SELECT
            q.id,
            q.title,
            q.description,
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
        abort(404)

    # Load questions belonging to this version
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

    # Load adaptive conditions
    rules = db.execute(
        """
        SELECT
            r.source_question_id,
            r.target_question_id,
            r.expected_answer

        FROM adaptive_rules r

        JOIN questions source
            ON source.id = r.source_question_id

        JOIN questions target
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


    return render_template(
        "client_questionnaire.html",
        questionnaire=questionnaire,
        questions=questions,
        adaptive_rules=[dict(rule) for rule in rules]
    )


if __name__ == "__main__":
    app.run(debug=True)
