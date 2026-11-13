# Step 91: Provider assignment migration

Public registration now supports Clients and Service Providers. Administrators cannot be registered publicly. New briefs require an active selected Provider and one of that Provider's active, published questionnaires. The assignment is fixed at creation; no Provider-changing workflow is introduced.

## Before starting the updated application

**Stop all Elunette processes first.** Do not migrate while a development reloader or another worker is running. Preserve a separate copy of your database as an additional precaution. The command below automatically creates a timestamped, consistent SQLite backup beside the database **before** making any changes. It uses SQLite's backup API rather than copying an open database file.

From the project directory, run:

```powershell
.\.venv\Scripts\python.exe migrate_provider_assignment.py --database instance/elunette.db
```

This command has **not** been run on the live database during development. Tests used temporary SQLite databases only.

The migration adds nullable `project_briefs.assigned_provider_id`, a foreign key to `users(id)`, and an index on assignment/status. It backfills only through the brief's existing questionnaire version, questionnaire owner and a user whose role is `service_provider`. It preserves inactive historical Provider identities. It does not modify users, questionnaire ownership, answers, statuses, timestamps, review decisions or revision history. It is transactional and safe to rerun; existing non-null assignments are retained. A fresh database receives the column through `schema.sql`.

Existing databases without this column are refused at startup, with instructions to run the explicit backup/migration command. No live migration is silently performed by importing the application.

## Reconciliation

The command reports any unassigned brief IDs. These remain visible to their rightful Client, including approved briefs, but cannot be submitted or exposed to a Provider until reconciled. Do not guess an owner. An administrator should inspect the historic questionnaire owner and review evidence, verify the intended Provider with the participants, then make an audited controlled update to that specific null assignment. No public reconciliation endpoint is provided.

Read-only audit during implementation found one existing approved brief, ID 3, with authoritative questionnaire ownership by Provider ID 2. Both existing questionnaires had valid Provider owners. No reconciliation was indicated by that audit; rerun the audit via the migration's output because records may change before deployment.

After reviewing the migration output, start Elunette normally and verify both roles' queues. Retain the backup. For rollback, stop the application, retain the migrated database separately, restore the timestamped backup and use the preceding application version. A pre-migration database is incompatible with the new assignment queries.

## Existing limitations

Notifications still have no storage/delivery/read-state backend; no notifications are fabricated. Password recovery and administrator user-management screens remain their existing placeholders. They were not expanded by this step. Use a stable private `ELUNETTE_SECRET_KEY` for the trial so sessions survive application restarts. No invitation or Provider-approval system was present or added.
