"""Explicit, additive Provider assignment migration. Never imports the Flask app."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sqlite3


def migrate(db):
    """Backfill only a valid questionnaire owner's Provider identity, atomically."""
    db.execute('BEGIN IMMEDIATE')
    try:
        columns = {row[1] for row in db.execute('PRAGMA table_info(project_briefs)')}
        if 'assigned_provider_id' not in columns:
            db.execute('ALTER TABLE project_briefs ADD COLUMN assigned_provider_id INTEGER REFERENCES users(id)')
        db.execute('''UPDATE project_briefs SET assigned_provider_id = (
            SELECT u.id FROM questionnaire_versions v
            JOIN questionnaires q ON q.id=v.questionnaire_id
            JOIN users u ON u.id=q.created_by AND u.role='service_provider'
            WHERE v.id=project_briefs.questionnaire_version_id
        ) WHERE assigned_provider_id IS NULL''')
        db.execute('CREATE INDEX IF NOT EXISTS idx_briefs_assigned_provider ON project_briefs(assigned_provider_id,status)')
        unresolved = [row[0] for row in db.execute('SELECT id FROM project_briefs WHERE assigned_provider_id IS NULL ORDER BY id')]
        db.commit()
        return unresolved
    except Exception:
        db.rollback()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True, type=Path)
    args = parser.parse_args()
    path = args.database.resolve(strict=True)
    backup = path.with_name(path.name + '.backup-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    with sqlite3.connect(path) as db:
        with sqlite3.connect(backup) as copy:
            db.backup(copy)
        print('Backup:', backup)
        db.execute('PRAGMA foreign_keys=ON')
        unresolved = migrate(db)
        print('Migration complete. Brief IDs requiring administrator reconciliation:', unresolved)


if __name__ == '__main__':
    main()
