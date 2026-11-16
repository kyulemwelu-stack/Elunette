
import os
import sqlite3
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path

from flask import current_app, g


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"]
        )

        g.db.row_factory = sqlite3.Row

        g.db.execute("PRAGMA foreign_keys = ON")

    return g.db


def close_db(error=None):
    db = g.pop("db", None)

    if db is not None:
        db.close()


def init_app(app):
    # Create the database directory
    Path(app.instance_path).mkdir(
        parents=True,
        exist_ok=True
    )

    # Configure the database location
    app.config["DATABASE"] = str(
        os.environ.get("ELUNETTE_DATABASE")
        or Path(app.instance_path) / "elunette.db"
    )

    # Close database connections after requests
    app.teardown_appcontext(close_db)

    # Create the initial database tables
    with app.app_context():
        db = get_db()

        # Existing databases require an explicit, backed-up migration first.
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_briefs'").fetchone():
            columns = {row[1] for row in db.execute('PRAGMA table_info(project_briefs)')}
            if 'assigned_provider_id' not in columns:
                raise RuntimeError('Provider assignment migration required. Stop Elunette and run: python migrate_provider_assignment.py --database <database path>. This creates a backup before migrating.')

        schema_path = (
            Path(app.root_path) / "schema.sql"
        )

        schema = schema_path.read_text(
            encoding="utf-8"
        )

        # Back up populated databases before the additive catalog extension.
        adaptive_exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='adaptive_definitions'").fetchone()
        populated = db.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone()
        if populated and not adaptive_exists:
            backup = Path(app.config['DATABASE']).with_suffix('.pre-adaptive-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f') + '.db')
            with closing(sqlite3.connect(str(backup))) as destination:
                db.backup(destination)
        db.executescript(schema)
        db.commit()
