
import os
import sqlite3
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

        schema_path = (
            Path(app.root_path) / "schema.sql"
        )

        schema = schema_path.read_text(
            encoding="utf-8"
        )

        db.executescript(schema)
        db.commit()
