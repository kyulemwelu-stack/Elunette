# Draft-saving failure investigation and fix

## Evidence

The live SQLite database was opened read-only. Brief 9 exists, is a draft, uses
the celebrations/graduation poster branch, and had 40 saved fields, generation
54 and 76% persisted completeness. SQLite quick_check passed and the saved
answers passed draft validation. The browser's reported 91% therefore included
unsaved changes; the database could not provide those in-memory values.

A consistent SQLite backup into a temporary directory was used to reproduce
requests with the existing saved graduation answers:

- A valid security token produced HTTP 200 and persisted the incomplete draft.
- The identical payload with a token older than Flask-WTF's default 3600 seconds
  produced HTTP 400, text/html, "The CSRF token has expired."
- The identical payload with a missing session produced HTTP 400, text/html,
  "The CSRF session token is missing."

The former JavaScript captured its security token once at page load, never
renewed it, and mapped any non-JSON error except 409 to a generic connection
failure. This reproduces the reported message without a connection failure.
Invalidated sessions can take the same path. The original browser request or
server trace was not available, so this investigation does not claim to identify
which of those two rejections occurred in the original tab.

The recent visual redesign did not introduce a 91% threshold, change the save
route, or require a full questionnaire. However, page reloads of the existing
development server can invalidate sessions because app.py uses a random signing
key when ELUNETTE_SECRET_KEY is absent. This existing application configuration
was not changed here. A stable private ELUNETTE_SECRET_KEY remains necessary for
sessions to survive server restarts. Security checks remain enabled.

## Changes

- adaptive_questionnaires.py: authenticated, ownership-checked, no-store
  save-state endpoint supplies a fresh token and persisted generation/state;
  JSON API errors distinguish authentication, token renewal, access, conflicts,
  validation and server/database failures. Save transactions explicitly roll
  back on failure. Missing project-title input can remain incomplete in draft
  answers while the dashboard retains its last valid title.
- questionnaire_engine.py: structural/type/choice/asset checks still protect
  draft data. Required fields, row completeness and cross-field consistency
  remain review/submission checks. In-progress contact, date and budget edits
  no longer block otherwise valid partial draft persistence.
- static/js/adaptive.js: renew tokens before writes; retry a token rejection
  once; coalesce concurrent Save calls; serialize the latest edits; confirm
  success only after a server acknowledgement; reconcile a lost response only
  when the persisted generation and exact normalized answers match the pending
  write. Never adopt a newer generation to overwrite different answers.
  Failed requests leave inputs untouched and dirty. Errors are friendly and
  omit internal keys such as _form. Authentication failures offer a separate-tab
  sign-in link. A user-triggered JSON download preserves the current form values.
- templates/adaptive_questionnaire.html: exposes the state endpoint and adds
  recovery actions, without a further visual redesign.
- tests/test_adaptive.py: expired tokens, lost sessions, JSON conflicts,
  incomplete graduation drafts, missing titles, deferred consistency checks,
  strict submission/type validation and persistence rollback.
- tests/adaptive_browser_smoke.py: real browser checks for duplicate clicks,
  edits in flight, lost responses after commits, token renewal, sign-in without
  reloading the form, completed review and stale-tab conflicts.

No database/schema migration was introduced. No live answers, briefs, accounts
or historical snapshots were edited. Live database SHA-256 before and after:
65afcfa8c20b0f560d3e87463cf01415d9fec652878de6fd45620ff6775bdcfa

## Verification

80 Python tests passed (60 existing workflow tests and 20 adaptive tests).
Chrome checks passed at 1440/820/390/320 pixels, including uploads, conditional
answers, saving/resuming, and all of the recovery/concurrency scenarios above.
Python compilation and git diff --check passed. Tests use temporary databases
and uploads; reproduction against brief 9 used a disposable backup only.

The updated JavaScript takes effect when a questionnaire page is newly loaded.
If the original failing tab still contains unsaved answers, keep it open and
copy those answers before refreshing. The server cannot reconstruct values that
were never received. The new recovery actions preserve future failed saves on
the page and provide an explicit downloadable copy.
