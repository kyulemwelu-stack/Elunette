# Adaptive questionnaires — implementation and preview

The supplied specification and JSON are preserved in this directory. The runtime
loader identifies its normalized definition as `1.0.0+elunette.1`; the original
source catalog stays at `1.0.0`. Each published definition stores the entire
normalized catalog in SQLite, so future source edits cannot alter old briefs.

## Existing architecture and integration

The repository uses Flask 3.1.3, Flask-WTF 1.3.0 and SQLite through `database.py`.
There was no requirements manifest. The existing `.venv` supplies dependencies;
this implementation adds no third-party dependencies. Existing questionnaires
support four simple field types and two-option adaptive rules. Existing accounts,
provider assignment, project_briefs, publications, dashboard queries, review
records and legacy revision cycles are retained.

Catalog questionnaires extend questionnaire_versions through adaptive_definitions;
answers extend the existing project brief through adaptive_drafts. No second brief
or account system is created. Catalog drafts are created after selecting one of
seven services and an active provider. Their publications are immutable. Existing
questionnaire links dispatch to the catalog wizard; provider review links dispatch
to the catalog review. Legacy questionnaire creation and existing routes retain
their original behavior. Catalog publication rows are excluded from the legacy
new-brief selector and its POST eligibility check.

## Coverage and explicit catalog adjustments

All seven services render from the JSON; Posters & Flyers has PF01–PF17, all nine
category branches, and conditionally activated event/business modules. The other
six services get META once, CORE once and their own subtype/details. All catalog
field types, repeater children, option labels and stored codes are supported.

Explicit compatibility adjustments, covered by tests:

- A sale subtype activates required BIZ04B/BIZ04C even when BIZ04A is not yes.
- `PF_CONTENT_VARIANTS` is an explicit implementation extension: a repeater with
  exactly one poster and one flyer row, containing message, supporting content
  and CTA, active only for PF01A=both and PF01B=different. Shared answers remain
  stored once. This fulfills the catalog's PF06–PF08 variation rule without
  silently repurposing an existing field ID.
- Missing/inactive controlling answers cannot activate negative predicates.
  Retained off-branch values cannot activate a dependent field. Hidden draft
  answers remain reversible but never enter active reviews or snapshots.
- SVG is rejected, including for PK06, because no SVG sanitizer exists. PDF,
  DOCX, UTF-8 TXT, PNG, JPEG and WebP are supported with content sniffing. Each
  file is limited to 20 MB, each request to 25 MB, each brief to 200 MB. Uploads
  live outside static, use random server names, and download as attachments with
  nosniff and private/no-store headers. Providers can access only assets actually
  referenced in a submitted snapshot, including historical snapshots.

Money uses decimal strings with recognized ISO currency codes, with KES suggested
in the UI. Checks include dates/times, budget and price ranges, contact methods,
percentage offers, public QR destinations, palette and HEX allowlists, row
schemas and uploaded asset ownership. URL validation checks public HTTP(S) syntax
and rejects credentials, private literal IPs and local hostnames. It does not
fetch destinations, verify DNS resolution, generate QR images, scan documents
for malware or establish external licensing/claim truth.

Claims, allergen and regulatory wording require explicit human verification at
provider approval. Pending essentials block approval; approved TBA and designer
recommendation options remain distinct. No private attendance-code field is
introduced or automatically copied onto artwork. Final design output is still a
human designer's responsibility.

## Status mapping

| Requirement | Existing status / additional evidence |
|---|---|
| Incomplete or complete draft | draft + applicable completeness |
| Submitted, needs information | submitted + snapshot assessment issues |
| Submitted, ready for review | submitted + ready assessment |
| Approved for design | approved + provider review record |
| Revision requested | revision_requested + provider feedback |
| Revised/resubmitted | submitted + new numbered immutable snapshot and response |

The existing status enum is preserved. There is no new archive action because
existing dashboards and the status schema have no archive workflow. Legacy
revision history remains unchanged; catalog submission history retains actor,
timestamp, exact labels, values, readiness and revision response on every cycle.

## Migration and backup

Stop the local server, then start the updated app normally. Before adding tables
to any existing database lacking adaptive_definitions, database.py uses SQLite's
backup API to write a sibling `*.pre-adaptive-<UTC timestamp>.db`. The connection
is explicitly closed before schema changes. Failure to back up aborts startup.
The extension is additive and repeatable: no table drops, data resets or updates
to existing briefs. Existing provider-assignment migration prerequisites still
apply. Backups, uploads and real databases remain ignored through existing rules.
All automated testing uses temporary databases and temporary uploads.

Rollback before any new catalog briefs are created: stop all app processes,
preserve a copy of the current database and its uploads, restore the timestamped
backup to the configured database path, then use the prior application code.
Restoring an old backup after new work would lose that new work; retain the
current database for recovery rather than overwriting it blindly.

## Files

- app.py: legacy-link dispatch, catalog mutation guards and route registration.
- database.py / schema.sql: backup plus additive definition/draft/snapshot/asset tables.
- questionnaire_engine.py: catalog loading, branching, normalization, validation,
  readiness, snapshots and the allowlisted condition interpreter.
- adaptive_questionnaires.py: creation, draft save, review, submission,
  revision, provider approval and permission-checked asset routes.
- templates/new_brief.html / static/js/new-brief.js: unified project/provider/service form with dynamically loaded provider questionnaires.
- templates/adaptive_new.html, adaptive_questionnaire.html, _adaptive_answers.html:
  service selection, wizard and readable structured reviews/history.
- static/css/adaptive.css / static/js/adaptive.js: isolated responsive theme,
  section navigation, swatches/HEX pickers, repeaters, announcements and autosave.
- tests/test_adaptive.py / tests/adaptive_browser_smoke.py: engine, integration,
  migration/security checks and real desktop/phone browser interactions.

## Preview and validation

Run from the workspace root in PowerShell:

```powershell
.\.venv\Scripts\python.exe app.py
```

Open http://127.0.0.1:5000/ and sign in as an existing client. Choose Create Brief,
then **Start a guided brief · All seven design services**, or go directly to
http://127.0.0.1:5000/client/adaptive/new. Select a service and provider; use Save
draft or let autosave run, then Review your brief and explicitly submit. The
assigned provider can open the brief from their existing Studio to request a
revision or approve. A client can explain changes and resubmit from the same
brief. An active provider account is required to create a new guided brief.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tests/adaptive_browser_smoke.py
```

Chrome checks use the installed Chrome executable; set CHROME_EXECUTABLE when
needed. They block external font requests for deterministic offline execution,
retain Chrome's security sandbox, and save screenshots to the system temporary
directory. JavaScript is required to edit the catalog wizard; reviews and
historical snapshots are server-rendered. Browser tests exercise 1440, 390 and
320 pixel widths. All services and poster categories have automated server-side
coverage; the browser interaction run focuses on the shared poster renderer.

No commits or pushes are made by this implementation.
## Final verification

- Baseline: 60 existing tests passed before implementation.
- Final regression run: 76 tests passed (60 existing + 16 new), using temporary
  databases and uploads. Includes backup preservation/idempotence and immutable
  snapshots, all seven services, all nine poster branches, named acceptance
  scenarios, drafts, submissions, revisions, approval, forged payloads, CSRF,
  stale drafts, cross-user access and submitted-only provider asset access.
- Chrome: all three real interaction cases passed at 1440, 390 and 320 pixels;
  no JavaScript errors or horizontal overflow. Phone screenshot inspected.
- Python compilation and `git diff --check` passed.
- Working tree: four modified tracked files (app.py, database.py, schema.sql,
  templates/new_brief.html), plus new engine/routes, templates, JS/CSS,
  specification/catalog/implementation notes and two test files listed above.
  No database, upload, environment, secret, commit or push is included.

Create Brief refinement: removed the extra hero link and consolidated creation into one form and Continue action. All seven adaptive services and existing provider questionnaires remain selectable. All 76 regression tests and six Chrome cases (Create Brief and wizard at 1440/390/320 pixels) passed. No hero CSS was changed.
## Editorial questionnaire interface refinement

The questionnaire presentation now uses a compact, labelled section selector
with current/complete/to-do states, applicable step counts, and a thin progress
bar. Client-facing cards show natural guidance in place of catalog authoring
notes, omit internal IDs from headings/reviews, and use restrained serif
headings, white cards and the existing cream/chocolate/sage/burgundy palette.
Short choice lists use native keyboard-operable radio cards backed by the same
stored values. Palette cards, custom colours, checkboxes, repeaters, dates and
file upload areas have scoped visual styling. Continue has primary burgundy
styling; Back, Save draft and Review have secondary treatments. The footer sits
in document flow so it cannot cover form content. Conditional transitions respect
reduced motion. Focus remains visible on interactive controls. Save generation
handling and all existing endpoints/validation remain intact; no schema change
was needed for the redesign.

Changed for this refinement: templates/adaptive_questionnaire.html,
templates/_adaptive_answers.html, static/css/adaptive.css,
static/js/adaptive.js, tests/adaptive_browser_smoke.py and this document.

Validation: all 76 Python regression tests passed. Real Chrome checks passed at
1440, 820, 390 and 320 pixel widths for both Create Brief and the wizard. Browser
checks also exercised native radio cards, compact section navigation and states,
conditional fields, retained palette choices, custom colours, repeaters,
applicable progress, saving, a real document upload, branch switching, reload,
keyboard focus and reduced-motion styling. Desktop palette and phone opening
screenshots were inspected. No JavaScript errors, horizontal page overflow or
footer/content overlaps were found. Existing server tests cover required-field
validation, uploads, submissions, revisions, approval and ownership.
## Editorial Review Your Brief redesign

The client review now has a compact editorial header, a completion card using
server-validated applicable required fields, an outstanding-required count, and
individual missing-information cards. Empty optional fields and hidden branches
do not add missing items. Corrections to optional answers can still block
submission when the existing validator requires them, without being counted as
missing required questions. A blank revision response is shown as a required
follow-up, separately from catalog percentage calculation.

Missing cards link to the owning brief's existing edit route with a question
parameter. The wizard verifies that target against the active field list,
selects its exact section and focuses its editable control. Save & return to
review uses the existing safe save pipeline, including token renewal,
acknowledgements and concurrency protection. No answers are changed by opening a
review or following an edit link.

Answers are grouped into relevant native collapsible sections, with section edit
links, visual palette/custom swatches, permission-checked file links, readable
ISO date/time presentation, decimal-preserving price formatting and pending or
needs-attention badges. Stored values and immutable snapshots are not rewritten.
Only active answers are used. Incomplete briefs offer Complete My Brief and a
disabled submission action. Complete briefs retain the explicit confirmation
checkbox and the existing CSRF-protected POST workflow. Submitted/approved
briefs remain read-only. Existing provider review/approval routes are preserved.

Files changed for this refinement:
- questionnaire_review.py (read-only review model and display formatters)
- adaptive_questionnaires.py (review context and template filters)
- templates/adaptive_questionnaire.html (client-review integration)
- templates/_adaptive_review.html and _adaptive_review_answers.html
- static/css/adaptive-review.css (loaded and scoped only for client review)
- static/js/adaptive.js (exact-question focus and save/return wording)
- tests/test_adaptive.py and tests/review_browser_smoke.py
- this implementation document

Validation: 83 Python tests passed, including existing authentication, save
recovery/concurrency, submissions, approval and revision checks, plus dynamic
missing cards, no-mutation GETs, attachments, swatches, pending information,
formatted dates/prices and explicit submission confirmation. Chrome passed
incomplete and complete review cases at 1440, 820, 390 and 320 pixels (eight
layout cases), with expanded summaries, file permissions, keyboard disclosure
controls/focus, no horizontal overflow and reduced motion. The browser followed
all four example missing-field links, saved each answer, returned to review,
unlocked submission only when complete, and completed a confirmed submission.
Desktop and phone screenshots were inspected. Python compilation and git diff
--check passed. Tests used temporary SQLite databases and uploads. No schema
changes or destructive migrations were introduced.

Run the focused browser check with:
`.\.venv\Scripts\python.exe tests/review_browser_smoke.py`
