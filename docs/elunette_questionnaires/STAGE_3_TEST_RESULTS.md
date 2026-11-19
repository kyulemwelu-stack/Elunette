# Elunette Stage 3 adaptive questionnaire QA

**Test date:** 19 November 2026 (East Africa Time)

The audit compared 322 documented question rows with the runtime catalog for wording, input type, required status and field visibility. It also verified the two documented runtime adjustments for sale offers. Fixtures covered all 112 named subtype choices, including subtype-level Other options, plus the standalone Other / Custom poster category. Each poster choice was checked with event details enabled and disabled.

## Results by service

| Service | Result | Subtypes covered | Representative adaptive branches |
|---|---|---|---|
| Posters & Flyers | Pass | 64 subtypes across eight categories, plus Other / Custom | Event and business modules, birthday and graduation, scripture, sale offers, QR and contact methods, separate poster and flyer content |
| Logo & Branding | Pass | Logo only, refresh, identity, guidelines, stationery, other | Existing identity, retained elements, variants, stationery, guidelines and brand colours |
| Websites & Applications | Pass | Marketing, portfolio, e-commerce, booking, dashboard, mobile, web app, redesign, other | Pages and screens, redesigned products, payments, roles and integrations |
| Social Media Design | Pass | Post, carousel, story, cover, ads, templates, campaign, other | Slide order, placements, custom colours, paid-ad disclosures and verification |
| Events & Invitations | Pass | Wedding, birthday, corporate, church/community, graduation, save-the-date, ticket, digital, other | Guest personalisation, RSVP, invitation copy, date, time and venue |
| Brochures & Menus | Pass | Brochure, catalogue, restaurant, service, programme, trifold, digital, other | Menu items, allergen wording, editability and human verification |
| Packaging Design | Pass | Label, box, pouch, bottle/jar, sleeve, sticker, packaging set, other | Variants, PDF dieline, regulatory wording, barcodes and variable data |

One isolated project per service went through draft creation, incomplete save, resume, client review, submission, designer review, revision, resubmission and approval. Checks verified both immutable snapshots and all four notification events with their expected recipients. Shared tests covered required and optional fields, missing-answer links, hidden answer exclusion, ownership, CSRF, stale generations, upload type and size checks, and rollback.

## Defects corrected

- Inactive malformed answers and retained online-event values could affect completeness or readiness. Validation now scopes field errors and the time-zone check to active questions.
- Free-text answers such as “working” could be marked pending. Both review views now use field-aware pending detection, including deferred essential poster or menu content.
- Time ranges compared strings, so equivalent times with and without seconds could fail. The engine now compares parsed times and checks the format used by the native time input.
- Upload failures displayed a generic save message. Upload controls now show specific errors, allow retrying the same file and direct users to a failed active upload. An inactive upload no longer blocks review.
- Repeater rows inserted after an upload lacked the new asset option, and cloned upload descriptions could point to missing labels. New rows now reuse uploaded references and preserve label associations.
- Event-like poster subtypes lacked the specified prompt when event details were switched off. The wizard now shows a hint and still allows teasers or announcements without event details.
- A missing upload on disk now returns a 404 from its authorized download route.
- The designer form refreshed the submission before approval, but a resubmission could arrive between that check and the write. The form now identifies the submission and the server verifies it inside the review transaction.

## Verification and limits

- **Automated:** 95 tests passed using temporary SQLite databases and upload folders.
- **Chrome:** The adaptive wizard, client review and designer review suites passed. All seven services passed active-section layout checks at 1440, 390 and 320 pixels. Shared wizard and review scenarios also passed at 820 pixels. Browser checks covered palettes, keyboard focus, reduced motion, repeaters, upload recovery, stale drafts, expired sessions and CSRF tokens, and the complete submission-to-approval workflow.
- **Live project:** SQLite integrity was checked read-only. The existing Graduation poster remained approved with two submissions and two review decisions. Testing left no permanent test briefs or notifications and required no database migration.
- **Coverage limits:** Subtype coverage is automated at the catalog and validation layer. Browser checks use representative branches in Chrome. Firefox, Safari, physical devices and screen-reader output were outside this run.
- **Existing scope differences:** The supplied packaging dieline wording mentions SVG. Uploads accept PDF and raster images as dieline alternatives because Elunette has no SVG sanitizer. The project has no archive action. For online poster events, the time zone is free text and is checked for presence before approval.

## Files changed

- Engine and review presentation — questionnaire_engine.py, questionnaire_review.py and designer_review.py
- Routes and templates — adaptive_questionnaires.py, static/js/adaptive.js, templates/adaptive_questionnaire.html and templates/designer_brief.html
- Tests — tests/test_adaptive.py, tests/adaptive_browser_smoke.py and tests/designer_browser_smoke.py
