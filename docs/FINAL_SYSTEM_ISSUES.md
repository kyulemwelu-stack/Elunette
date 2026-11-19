# Elunette final system issues

**Assessment date** — 19 November 2026, East Africa Time

## Corrected during Stage 5

| Issue | Finding | Correction and evidence | Status |
|---|---|---|---|
| EL5-01 | The direct Python entry point forced Flask debug mode and the signed session validity depended on the framework default. | Normal startup now leaves Flask debug opt-in. Signed cookies have an explicit eight-hour validity after issuance. HttpOnly and SameSite=Lax remain enabled, with Secure-cookie support for HTTPS environments. F05-02 verified the cookie flags and expiry. | Closed for local scope |
| EL5-02 | Attachment access checked recorded ownership and assignment without requiring the account’s current role. | Attachment downloads now require the current client role plus ownership, or the current provider role plus assignment and a submitted reference. F05-07 confirmed access before the fixture role change and denial afterward. | Closed |
| EL5-03 | Common pages fetched the same logged-in account three to five times per request. | The authenticated row is reused within one Flask request. Subsequent requests still consult SQLite for account status and role. F05-12 measured one account lookup per authenticated request. | Closed |

## Outstanding or unverified

| Issue | Evidence and impact | Disposition |
|---|---|---|
| EL5-04 — Password reset | The account recovery pages are informational. Reset delivery and token verification have no backend. | Demonstrate sign-in and recovery guidance. Treat full recovery as a feature gap if the approved requirements include it. |
| EL5-05 — Approved SRS and SDS | No separately identified approved files were located under the project. | Reconcile the provisional matrix with the approved versions before asserting formal compliance. |
| EL5-06 — Browser and accessibility breadth | Chrome and keyboard smoke checks passed. Safari, Firefox, physical devices and assistive technology were outside this run. | Verify on demonstration hardware if available. Complete a separate accessibility review before making a conformance claim. |
| EL5-07 — Deployment controls | Secure cookies were verified in an HTTPS test request. Production TLS, proxy configuration, shared secret management, authentication rate limiting and deployment load were outside this audit. | For HTTPS, configure `ELUNETTE_COOKIE_SECURE=1` and a stable deployment-provided `ELUNETTE_SECRET_KEY`. Keep Flask debug disabled. A production readiness review remains separate. |
| EL5-08 — Asset scanning | Uploads use a file allowlist, limits, content checks and authorized serving. SVG remains rejected. | Current checks cover the supported formats and recorded permissions. Malware scanning and full document sanitization remain outside the implemented scope. |
| EL5-09 — Existing workflow boundaries | The administrator directory remains read-only. Archive and full time-zone validation are also absent. | These gaps should be mapped to final SRS/SDS requirements if included. The local client and designer demo does not depend on them. |
| EL5-10 — Session revocation scope | Logout clears the browser’s signed cookie. The app has no server-side session registry for global revocation across devices. | Use the tested cookie expiry and per-request account checks for the local demonstration. Assess server-side revocation separately if required for deployment. |

## Files modified

- `app.py` and `adaptive_questionnaires.py`
- `tests/test_final_system.py` and `tests/final_system_benchmark.py`
- This issue register, the [final test results](STAGE_5_FINAL_TEST_RESULTS.md), and the [requirements traceability matrix](REQUIREMENTS_TRACEABILITY_MATRIX.md)

## Readiness assessment

The measured evidence supports a local DBIT demonstration covering registration, role separation, all seven brief services, submission, revision, resubmission, approval and their notification trail. The live database was inspected read-only. There was no schema migration. Outstanding items limit claims about full feature coverage, production security, or approved SRS/SDS compliance.
