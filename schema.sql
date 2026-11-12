
-- ELUNETTE DATABASE
-- Step 79.1: User Accounts

CREATE TABLE IF NOT EXISTS users (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    full_name TEXT NOT NULL,

    email TEXT NOT NULL UNIQUE COLLATE NOCASE,

    password_hash TEXT NOT NULL,

    role TEXT NOT NULL DEFAULT 'client'
        CHECK (
            role IN (
                'client',
                'service_provider',
                'administrator'
            )
        ),

    status TEXT NOT NULL DEFAULT 'active'
        CHECK (
            status IN ('active', 'inactive')
        ),

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP

);

-- ==========================================
-- ELUNETTE QUESTIONNAIRE MANAGEMENT
-- ==========================================

-- QUESTIONNAIRES

CREATE TABLE IF NOT EXISTS questionnaires (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    title TEXT NOT NULL,

    description TEXT NOT NULL,

    created_by INTEGER NOT NULL,

    status TEXT NOT NULL DEFAULT 'inactive'
        CHECK (
            status IN ('active', 'inactive')
        ),

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    updated_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (created_by)
        REFERENCES users(id)
);


-- QUESTIONNAIRE VERSIONS

CREATE TABLE IF NOT EXISTS questionnaire_versions (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    questionnaire_id INTEGER NOT NULL,

    version_number INTEGER NOT NULL DEFAULT 1,

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (questionnaire_id)
        REFERENCES questionnaires(id),

    UNIQUE (questionnaire_id, version_number)
);


-- QUESTIONNAIRE QUESTIONS

CREATE TABLE IF NOT EXISTS questions (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    questionnaire_version_id INTEGER NOT NULL,

    question_text TEXT NOT NULL,

    question_type TEXT NOT NULL
        CHECK (
            question_type IN (
                'text',
                'multiple_choice',
                'number',
                'date'
            )
        ),

    position INTEGER NOT NULL,

    is_required INTEGER NOT NULL DEFAULT 0
        CHECK (is_required IN (0, 1)),

    is_active INTEGER NOT NULL DEFAULT 1
        CHECK (is_active IN (0, 1)),

    option_one TEXT,

    option_two TEXT,

    FOREIGN KEY (questionnaire_version_id)
        REFERENCES questionnaire_versions(id)
);

-- ==========================================
-- QUESTIONNAIRE PUBLICATION HISTORY
-- ==========================================

CREATE TABLE IF NOT EXISTS questionnaire_publications (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    questionnaire_id INTEGER NOT NULL,

    questionnaire_version_id INTEGER NOT NULL UNIQUE,

    title_snapshot TEXT NOT NULL,

    description_snapshot TEXT NOT NULL,

    published_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (questionnaire_id)
        REFERENCES questionnaires(id),

    FOREIGN KEY (questionnaire_version_id)
        REFERENCES questionnaire_versions(id)
);


-- ==========================================
-- PROTECT PUBLISHED QUESTIONS
-- ==========================================

CREATE TRIGGER IF NOT EXISTS
prevent_published_question_insert

BEFORE INSERT ON questions

WHEN EXISTS (
    SELECT 1
    FROM questionnaire_publications
    WHERE questionnaire_version_id =
          NEW.questionnaire_version_id
)

BEGIN
    SELECT RAISE(
        ABORT,
        'Cannot add questions to a published version'
    );
END;


CREATE TRIGGER IF NOT EXISTS
prevent_published_question_update

BEFORE UPDATE ON questions

WHEN EXISTS (
    SELECT 1
    FROM questionnaire_publications
    WHERE questionnaire_version_id =
          OLD.questionnaire_version_id
)
OR EXISTS (
    SELECT 1
    FROM questionnaire_publications
    WHERE questionnaire_version_id =
          NEW.questionnaire_version_id
)

BEGIN
    SELECT RAISE(
        ABORT,
        'Cannot edit questions in a published version'
    );
END;


CREATE TRIGGER IF NOT EXISTS
prevent_published_question_delete

BEFORE DELETE ON questions

WHEN EXISTS (
    SELECT 1
    FROM questionnaire_publications
    WHERE questionnaire_version_id =
          OLD.questionnaire_version_id
)

BEGIN
    SELECT RAISE(
        ABORT,
        'Cannot delete questions from a published version'
    );
END;

-- ==========================================
-- ELUNETTE ADAPTIVE QUESTIONNAIRE RULES
-- ==========================================

CREATE TABLE IF NOT EXISTS adaptive_rules (

    id INTEGER PRIMARY KEY AUTOINCREMENT,

    questionnaire_version_id INTEGER NOT NULL,

    source_question_id INTEGER NOT NULL,

    target_question_id INTEGER NOT NULL,

    expected_answer TEXT NOT NULL,

    created_at TEXT NOT NULL
        DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (questionnaire_version_id)
        REFERENCES questionnaire_versions(id),

    FOREIGN KEY (source_question_id)
        REFERENCES questions(id),

    FOREIGN KEY (target_question_id)
        REFERENCES questions(id),

    CHECK (source_question_id != target_question_id),

    CHECK (LENGTH(TRIM(expected_answer)) > 0),

    UNIQUE (
        questionnaire_version_id,
        target_question_id
    )

);


-- ==========================================
-- PROTECT PUBLISHED ADAPTIVE RULES
-- ==========================================

CREATE TRIGGER IF NOT EXISTS
prevent_published_rule_insert

BEFORE INSERT ON adaptive_rules

WHEN EXISTS (
    SELECT 1
    FROM questionnaire_publications
    WHERE questionnaire_version_id =
          NEW.questionnaire_version_id
)

BEGIN
    SELECT RAISE(
        ABORT,
        'Cannot add rules to a published version'
    );
END;


CREATE TRIGGER IF NOT EXISTS
prevent_published_rule_update

BEFORE UPDATE ON adaptive_rules

WHEN EXISTS (
    SELECT 1
    FROM questionnaire_publications
    WHERE questionnaire_version_id =
          OLD.questionnaire_version_id
)
OR EXISTS (
    SELECT 1
    FROM questionnaire_publications
    WHERE questionnaire_version_id =
          NEW.questionnaire_version_id
)

BEGIN
    SELECT RAISE(
        ABORT,
        'Cannot edit published adaptive rules'
    );
END;


CREATE TRIGGER IF NOT EXISTS
prevent_published_rule_delete

BEFORE DELETE ON adaptive_rules

WHEN EXISTS (
    SELECT 1
    FROM questionnaire_publications
    WHERE questionnaire_version_id =
          OLD.questionnaire_version_id
)

BEGIN
    SELECT RAISE(
        ABORT,
        'Cannot delete published adaptive rules'
    );
END;
