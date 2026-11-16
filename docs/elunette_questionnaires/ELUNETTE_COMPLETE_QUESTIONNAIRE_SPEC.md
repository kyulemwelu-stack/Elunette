# Elunette — Complete Adaptive Questionnaire Specification

**Version:** 1.0.0 (proposed implementation catalog)  
**Platform:** Flask + SQLite  
**Coverage:** Seven design services; nine Posters & Flyers categories; full branching, colour selection, draft and submission requirements.

> **Implementation note:** These are proposed requirements created from our questionnaire-planning conversation. They are not changes to the existing VS Code repository. Codex must inspect the repository before implementation.


## 1. Purpose and scope

This is the implementation-oriented questionnaire specification for Elunette, a Flask + SQLite adaptive client brief management platform. It contains a complete first-pass catalog for seven design services. Posters & Flyers retains 17 main question groups, nine categories and distinct event/business sub-branches. The catalog is a specification, not a claim that any code has been changed.


## 2. Source-of-truth and compatibility

`elunette_questionnaire_catalog.json` is the canonical field catalog, including question IDs, exact wording, field types, options, conditional visibility and required flags. Keep it versioned. Use the current application architecture, database access and routes after inspection; do not assume the screenshot establishes present functionality.


## 3. Questionnaire experience

Clients select a service; see a short introduction; complete logically ordered sections; see only relevant follow-ups; select palettes visually; add repeated rows for products, event guests and tickets; upload approved reference assets; save drafts; review a structured summary; submit; and respond to revision requests. Show progress as completed applicable requirements, not total catalog fields. A designer-to-recommend answer is an explicit valid preference, not an omission.


## 4. Status lifecycle

Separate draft/incomplete, submitted_needs_information, submitted_ready_for_review, approved_for_design, revision_requested, revised/resubmitted and archived states. Existing status vocabulary may differ: adapt to existing models and make a transition table. Submission is distinct from approval. Preserve immutable answer snapshots for submissions and resubmissions, and retain revision chronology, actor and timestamps.


## 5. Hidden answers and revisions

Evaluate conditions consistently on client and server. Preserve off-branch draft values when switching temporarily, but exclude hidden values from validation, customer preview, designer exports and submitted snapshots. When a previously approved answer changes, log a revision or new answer snapshot; never silently mutate an approved historical brief.


## 6. Validation and pending data

A required field is required only when all its ancestor groups and `when` predicates are active. Draft save tolerates missing required answers and explicit pending choices. Submission should show missing fields clearly; design-ready eligibility also checks pending essentials and required assets. A confirmed TBA message is legitimate only when knowingly approved for a teaser. Validate money, dates, timezones, formats, file ownership and link methods server-side. Never accept a client-sent `required=false` or fake category to bypass validation.


## 7. Data and versioning model

Recommended logical entities: questionnaire_definition(id, service, version, schema_json, enabled), brief(id, owner_id, service, questionnaire_version, state), brief_draft_answers(brief_id, answers_json, updated_at), brief_submission_snapshot(id, brief_id, revision_number, answers_json, completeness_json, submitted_at, actor_id), brief_asset(id, brief_id, uploader_id, path, media_type, size, status), and brief_revision(id, brief_id, requested_by, comment, created_at). This is logical guidance: map to existing SQLite tables with forward-only, non-destructive migrations. Do not invent a second parallel brief system.


## 8. Visual design

Keep Elunette's product UI in chocolate brown #5C3A26, warm cream #F1E7D3, soft sage #A3B18A, burgundy #6B1F2F and white; use an editorial serif paired with a clear sans-serif. Client artwork colours are unrestricted. Provide a swatch gallery (six included examples), custom HEX picker with keyboard access, brand colours, designer recommendation, avoid-colours text and colour flexibility. Show accessible colour names and HEX values, do not rely on colour alone.


## 9. Privacy, security and reliability

Respect CSRF/session/auth and per-brief ownership on all GET and POST endpoints. Protect against IDOR, XSS, unsafe HTML, CSRF, SQL injection, upload filename traversal, oversized files, forged MIME, SVG script and hidden answer injection. Store uploads outside public static if possible; serve via permission-checked routes. Enforce maximum size per file and total request, content sniffing, safe filenames, upload audit, and never log user-sensitive content or credentials. Keep backups and migration rollback instructions.


## 10. Accessibility and interaction

Use associated labels, fieldsets for choice groups, visible focus states, keyboard-operable palette swatches, semantic progress, inline error messages, accessible condition announcements, screen-reader label for required and pending fields, responsive layout and reduced motion. Provide section navigation without losing draft values. Never lock clients into a choice that can be changed safely.


## 11. Asset and copyright rules

Clients can upload their logos, images, brand guides and references, indicate permission/licensing, and specify exact text they do not want changed. Store file metadata and relation to the brief; do not assume every upload must be publicly accessible. For photographs of people, avoid promising permissions you cannot verify. For slogans/statistics/regulated claims, record the supporting source or human review requirement.


## 12. Testing and acceptance

Use temporary SQLite databases and fixtures. Cover all seven top-level services, all nine Posters & Flyers categories, all conditional subtype questions, colour picker, file uploads, server-side validation, redirect/auth, two users, draft/resume, change branches, review summary, submit, revisions/resubmission, privacy, tampered payloads, date-money checks, missing assets and mobile smoke tests. Verify existing unrelated project tests still pass.


## 13. Service map

| Service | Branching detail |
|---|---|
| Posters & Flyers | 17 main groups, nine named poster types, optional event and business shared modules |
| Logo & Branding | Logo only, Logo refresh, Full visual identity, Brand guidelines, Business stationery, Other branding |
| Websites & Applications | Business/marketing website, Portfolio, E-commerce, Booking/service platform, Dashboard/portal, Mobile app, Custom web application, Redesign, Other |
| Social Media Design | Single social post, Multi-slide carousel, Story/status, Cover/banner, Paid ad creative, Reusable template set, Campaign pack, Other social design |
| Events & Invitations | Wedding invitation, Birthday invitation, Corporate invitation, Church/community event, Graduation, Save-the-date, Event ticket/pass, Digital invitation, Other invitation |
| Brochures & Menus | Corporate/product brochure, Product catalogue, Restaurant menu, Service price list, Event programme booklet, Tri-fold leaflet, Digital brochure/menu, Other |
| Packaging Design | Product label, Box/carton, Bag/pouch, Bottle/jar wrap, Sleeve/band, Sticker/seal, Complete packaging range, Other packaging |

## 14. Universal project metadata

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| META01 | Project title (for the client dashboard) | short_text | Required | Always |
| META02 | What service do you need? | single_choice | Required | Always |

## 15. Posters & Flyers — 17 main question groups


### PF01 — Design format

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| PF01A | What would you like us to design? | single_choice | Required | Always |
| PF01B | Should both designs contain the same information? | single_choice | Required | PF01A = both |


### PF02 — Category and event type

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| PF02A | What is your design for? | single_choice | Required | Always |
| PF02B | Please describe your project category | long_text | Required | PF02A = other |
| PF02C | Is your design promoting a specific event or gathering? | single_choice | Required | Always |
| PF02D | What type of event or project is this? | single_choice | Required | PF02A = events_entertainment |
| PF02E | Which business promotion best describes your project? | single_choice | Required | PF02A = business_promotion |
| PF02F | What kind of corporate communication is it? | single_choice | Required | PF02A = corporate |
| PF02G | What kind of educational material is it? | single_choice | Required | PF02A = educational |
| PF02H | What kind of campaign is it? | single_choice | Required | PF02A = awareness |
| PF02I | What kind of opportunity are you announcing? | single_choice | Required | PF02A = recruitment |
| PF02J | What kind of celebration is it? | single_choice | Required | PF02A = celebrations |
| PF02K | What kind of religious or community design is it? | single_choice | Required | PF02A = religious_community |
| PF02L | Please specify your subtype or occasion | long_text | Required | (PF02D = other OR PF02E = other OR PF02F = other OR PF02G = other OR PF02H = other OR PF02I = other OR PF02J = other OR PF02K = other) |

*Note:* Subtype fields depend on category; event data is collected in EV module only when PF02C=yes. Warn if subtype suggests an event but PF02C=no; allow valid non-event teaser/announcement cases.


### PF03 — Intended use

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| PF03A | Where will your design be used? | single_choice | Required | Always |


### PF04 — Project objective

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| PF04A | What is the main thing you want the design to achieve? | single_choice | Required | Always |
| PF04B | What outcome would you like? | long_text | Required | PF04A = other |


### PF05 — Target audience

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| PF05A | Who would you like your design to reach? | multi_choice | Required | Always |
| PF05B | Describe the specific or other audience | long_text | Required | (PF05A includes community OR PF05A includes other) |
| PF05C | Anything else we should know about your audience? | long_text | Optional | Always |


### PF06 — Main message

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| PF06A | How prepared is your main headline or message? | single_choice | Required | Always |
| PF06B | What is the main message you want people to remember? | long_text | Required | Always |


### PF07 — Supporting content

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| PF07A | Do you already have supporting content? | single_choice | Required | Always |
| PF07B | How would you like to provide the content? | single_choice | Required | PF07A ∈ ready, partial |
| PF07C | Paste the supporting content | long_text | Required | (PF07A ∈ ready, partial AND PF07B = type) |
| PF07D | Upload supporting document | file_upload | Required | (PF07A ∈ ready, partial AND PF07B = upload) |
| PF07E | What supporting content should the designer help develop? | long_text | Required | PF07A = help |


### PF08 — Call to action

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| PF08A | What would you like viewers to do next? | single_choice | Required | Always |
| PF08B | Describe the other action | short_text | Required | PF08A = other |
| PF08C | How can viewers take this action? | multi_choice | Required | PF08A not in none, share |
| PF08D | Action destinations | repeater | Optional | PF08C not empty |
| PF08E | Would you like a QR code? | single_choice | Optional | Always |
| PF08F | QR destination if different from the existing action link | url | Optional | PF08E = yes |

*Note:* When QR is yes, require at least one valid pre-existing or new destination at submission; never generate invalid QR targets.


### PF09 — Category-specific questions

*Dynamic content from the chosen category, plus event/business modules as applicable.*

*Note:* Display exactly one corresponding category branch; also load shared_event only if PF02C=yes; load shared_business for business branch.


### PF10 — Existing branding and supplied assets

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| PF10A | Do you have existing branding or materials to use? | single_choice | Required | Always |
| PF10B | Which materials do you have? | multi_choice | Optional | PF10A = yes |
| PF10C | Upload brand material or visual reference | file_upload | Optional | PF10A = yes |
| PF10D | Do you have permission to use the supplied materials? | single_choice | Optional | PF10A = yes |


### PF11 — Visual direction

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| PF11A | Which feelings or styles suit your design? | multi_choice | Required | Always |
| PF11B | What kind of imagery do you prefer? | single_choice | Required | Always |
| PF11C | Which typography direction do you prefer? | single_choice | Optional | Always |
| PF11D | What should stand out most? | short_text | Required | Always |
| PF11E | Do you have inspiration or example designs? | single_choice | Required | Always |
| PF11F | Upload visual references | file_upload | Optional | PF11E = yes |
| PF11G | What do you like about these references? | long_text | Optional | PF11E = yes |
| PF11H | Which language(s) should appear on the design? | multi_choice | Required | Always |
| PF11I | Specify the other language(s) | short_text | Required | PF11H includes other |
| PF11J | Is the translation supplied? | single_choice | Optional | Always |


### PF12 — Colour selection

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| PF12A | How would you like to choose colours? | single_choice | Required | Always |
| PF12B | Choose a suggested colour palette | palette_select | Required | PF12A = palette |
| PF12C | Choose your own colours | color_multi_picker | Required | PF12A = custom |
| PF12D | Enter brand colours or HEX values | long_text | Required | PF12A = brand |
| PF12E | Any colours to avoid? | short_text | Optional | Always |
| PF12F | How strictly should your selected colours be followed? | single_choice | Required | PF12A ∈ palette, custom, brand |


### PF13 — Sizes and versions

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| PF13A | Which sizes, platforms or formats do you need? | repeater | Required | Always |
| PF13B | Do the versions require different content or layouts? | single_choice | Required | Always |


### PF14 — Print preparation

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| PF14A | Will any of these designs be printed? | single_choice | Required | PF03A ∈ print, both |
| PF14B | Is print single- or double-sided? | single_choice | Required | PF14A = yes |
| PF14C | Expected print quantity (if known) | short_text | Optional | PF14A = yes |
| PF14D | Do you have printer size, bleed, safe-area or colour requirements? | long_text | Optional | PF14A = yes |


### PF15 — Deliverables

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| PF15A | Which final files do you need? | multi_choice | Required | Always |
| PF15B | Any handover or file-naming requirements? | long_text | Optional | Always |


### PF16 — Deadline

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| PF16A | When do you need the completed design? | date | Required | Always |
| PF16B | How flexible is this deadline? | single_choice | Required | Always |
| PF16C | Is there an earlier approval or publishing deadline? | long_text | Optional | Always |


### PF17 — Budget and approval

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| PF17A | How would you prefer to discuss the budget? | single_choice | Required | Always |
| PF17B | Minimum budget | money | Required | PF17A = range |
| PF17C | Maximum budget | money | Required | PF17A = range |
| PF17D | Who will approve the final design? | single_choice | Required | Always |
| PF17E | Explain any approval process or special instructions | long_text | Optional | Always |
| PF17F | Anything else the designer should know? | long_text | Optional | Always |


## 16. Shared event module (use only for actual event designs)


### EV01 — Event identity

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| EV01A | What is the name of your event? | short_text | Required | Always |
| EV01B | Is this event name final? | single_choice | Required | Always |
| EV01C | What wording should we use until the name is confirmed? | short_text | Required | EV01B = working |


### EV02 — Event date

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| EV02A | When will your event take place? | single_choice | Required | Always |
| EV02B | Event date | date | Required | EV02A = single |
| EV02C | Starting date | date | Required | EV02A = range |
| EV02D | Ending date | date | Required | EV02A = range |
| EV02E | Describe the recurring schedule | long_text | Required | EV02A = recurring |


### EV03 — Event time

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| EV03A | What time will your event take place? | single_choice | Required | Always |
| EV03B | Start time | time | Required | EV03A = fixed |
| EV03C | End time (if known) | time | Optional | EV03A = fixed |
| EV03D | Describe the schedule by day | long_text | Required | EV03A = variable |
| EV03E | Time zone for online or international audiences | short_text | Optional | Always |


### EV04 — Event location

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| EV04A | Where will your event take place? | single_choice | Required | Always |
| EV04B | Venue name | short_text | Required | EV04A ∈ physical, hybrid |
| EV04C | Town or city | short_text | Required | EV04A ∈ physical, hybrid |
| EV04D | Address, landmark or directions | long_text | Optional | EV04A ∈ physical, hybrid |
| EV04E | Online platform | short_text | Required | EV04A ∈ online, hybrid |
| EV04F | Public event or registration link | url | Optional | EV04A ∈ online, hybrid |


### EV05 — Admission

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| EV05A | How can people attend? | single_choice | Required | Always |
| EV05B | Ticket pricing structure | single_choice | Required | EV05A = paid |
| EV05C | Ticket categories | repeater | Required | EV05A = paid |


### EV06 — Featured people

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| EV06A | Should any speakers, performers, hosts or guests be featured? | single_choice | Required | Always |
| EV06B | Add featured people | repeater | Required | EV06A = yes |


### EV07 — Programme highlights

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| EV07A | Are there activities or programme highlights to include? | single_choice | Required | Always |
| EV07B | List the highlights | repeater | Required | EV07A = yes |


### EV08 — Organiser

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| EV08A | Who is organising or hosting the event? | short_text | Optional | Always |
| EV08B | Should the organiser name appear on the design? | single_choice | Optional | Always |


### EV09 — Attendance notices

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| EV09A | Are there any important notices for attendees? | multi_choice | Optional | Always |
| EV09B | Provide the selected notice details | long_text | Required | EV09A not empty |


### EV10 — Sponsors and partners

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| EV10A | Should sponsors or partners appear in the design? | single_choice | Required | Always |
| EV10B | Sponsors / partners | repeater | Required | EV10A = yes |


## 17. Shared business promotion module


### BIZ01 — Business identity

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| BIZ01A | What is the exact business or brand name? | short_text | Required | Always |
| BIZ01B | Should the business name appear in the design? | single_choice | Required | Always |


### BIZ02 — Products and services

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| BIZ02A | Which products or services should appear? | repeater | Optional | Always |


### BIZ03 — Prices

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| BIZ03A | Would you like prices to appear? | single_choice | Required | Always |
| BIZ03B | Prices to show | repeater | Required | BIZ03A ∈ exact, starting, range |


### BIZ04 — Offers

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| BIZ04A | Is there a special offer or discount? | single_choice | Required | Always |
| BIZ04B | What is the type of offer? | single_choice | Required | BIZ04A = yes |
| BIZ04C | Give the exact offer details, values and included items | long_text | Required | BIZ04A = yes |
| BIZ04D | List restrictions, exclusions or offer terms | long_text | Optional | BIZ04A = yes |


### BIZ05 — Availability

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| BIZ05A | When is this promotion or offering available? | single_choice | Required | Always |
| BIZ05B | Start date | date | Required | BIZ05A ∈ start, range |
| BIZ05C | End date | date | Required | BIZ05A = range |


### BIZ06 — How customers access it

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| BIZ06A | Where can customers buy, book or access it? | multi_choice | Optional | Always |
| BIZ06B | Supply relevant outlet, service area or other access details | long_text | Optional | Always |


### BIZ07 — Claims and features

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| BIZ07A | Are there facts, specifications, guarantees or claims that must appear? | single_choice | Required | Always |
| BIZ07B | Claims to include | repeater | Required | BIZ07A = yes |


### BIZ08 — Terms and restrictions

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| BIZ08A | Are there important terms or restrictions customers should know? | single_choice | Required | Always |
| BIZ08B | Provide exact terms and restrictions | long_text | Required | BIZ08A = yes |


## 18. Nine Posters & Flyers category branches


### Events & Entertainment

**Activation:** `PF02A = events_entertainment`.

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| ENT01 | What genre, theme or atmosphere should the entertainment communicate? | short_text | Optional | Always |
| ENT02 | Which performers or attractions should be highlighted? | repeater | Optional | PF02D ∈ concert, festival, performance, exhibition |
| ENT03 | Will the event feature several stages, sessions or areas? | single_choice | Required | PF02D ∈ festival, exhibition |
| ENT04 | Describe the areas, stages or sessions | long_text | Required | ENT03 = yes |
| ENT05 | What is the party theme or dress concept? | short_text | Optional | PF02D = party |
| ENT06 | Which film titles will be screened? | repeater | Required | PF02D = film |
| ENT07 | Which teams, athletes or activities should appear? | repeater | Required | PF02D = sports |
| ENT08 | Who is the sports poster primarily for? | single_choice | Required | PF02D = sports |
| ENT09 | Are there production credits or featured collaborators? | long_text | Optional | PF02D = performance |
| ENT10 | List any eligibility, participation or age-rating information | long_text | Optional | Always |


### Business & Product Promotion

**Activation:** `PF02A = business_promotion`.

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| BP01 | What product category or service industry is this about? | short_text | Required | Always |
| BP02 | Does the product have variants or options customers should know? | single_choice | Required | PF02E = product |
| BP03 | List the variants | repeater | Required | BP02 = yes |
| BP04 | What exactly is included in your service? | long_text | Required | PF02E = service |
| BP05 | How is the service delivered? | single_choice | Required | PF02E = service |
| BP06 | Do customers need to book appointments? | single_choice | Required | PF02E = service |
| BP07 | Which products/services are covered by the sale? | single_choice | Required | PF02E = sale |
| BP08 | What is new about the product or service? | long_text | Required | PF02E = launch |
| BP09 | How much should the launch reveal? | single_choice | Required | PF02E = launch |
| BP10 | What kind of business opening is this? | single_choice | Required | PF02E = opening |
| BP11 | Which branch or business location is opening or changing? | short_text | Required | PF02E = opening |
| BP12 | What makes your business unique? | long_text | Required | PF02E = brand |
| BP13 | What prizes or rewards can participants win? | repeater | Required | PF02E = giveaway |
| BP14 | What steps must someone take to enter? | long_text | Required | PF02E = giveaway |
| BP15 | Who is eligible? | long_text | Required | PF02E = giveaway |
| BP16 | When does the giveaway close? | date | Required | PF02E = giveaway |
| BP17 | How and when are winners selected or announced? | long_text | Required | PF02E = giveaway |
| BP18 | Describe the other promotion | long_text | Required | PF02E = other |


### Corporate & Professional

**Activation:** `PF02A = corporate`.

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| COR01 | What is the official organisation or department name? | short_text | Required | Always |
| COR02 | What tone should the official communication have? | single_choice | Required | Always |
| COR03 | What official information must be stated exactly as approved? | long_text | Required | Always |
| COR04 | Who is issuing or authorising the communication? | short_text | Optional | Always |
| COR05 | Does the communication require an official sign-off or approval notice? | single_choice | Required | Always |
| COR06 | Provide the signature, title, approval wording or protocol | long_text | Required | COR05 = yes |
| COR07 | Seminar/workshop topics or sessions | repeater | Required | PF02F = seminar |
| COR08 | What milestone or achievement is being celebrated? | long_text | Required | PF02F = milestone |
| COR09 | What policy or notice is being communicated? | long_text | Required | PF02F = policy |
| COR10 | Provide the verified statistics or highlights to display | long_text | Required | PF02F = report |
| COR11 | What are the key corporate strengths or services to highlight? | long_text | Required | PF02F = brand |
| COR12 | Describe the custom corporate communication | long_text | Required | PF02F = other |


### Educational & Informational

**Activation:** `PF02A = educational`.

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| EDU01 | What is the school, institution, course or subject? | short_text | Required | Always |
| EDU02 | Who needs to understand this material? | single_choice | Required | Always |
| EDU03 | Which facts, learning points or instructions must be accurate and included? | long_text | Required | Always |
| EDU04 | Are references or source citations needed on the design? | single_choice | Required | Always |
| EDU05 | References or approved information sources | repeater | Required | EDU04 = yes |
| EDU06 | Course or workshop details | repeater | Required | PF02G ∈ class, workshop |
| EDU07 | Timetable entries | repeater | Required | PF02G = timetable |
| EDU08 | What are the admission requirements and application steps? | long_text | Required | PF02G = admission |
| EDU09 | When does admission or registration close? | date | Optional | PF02G = admission |
| EDU10 | Describe the educational or safety instructions to communicate | long_text | Required | PF02G ∈ infographic, safety |
| EDU11 | Describe the other educational material | long_text | Required | PF02G = other |


### Awareness & Campaigns

**Activation:** `PF02A = awareness`.

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| AW01 | What cause, issue or campaign name is this about? | short_text | Required | Always |
| AW02 | What is the key fact, problem or message people should understand? | long_text | Required | Always |
| AW03 | Which response are you asking the audience to make? | single_choice | Required | Always |
| AW04 | Facts, data or statistics to include | repeater | Optional | Always |
| AW05 | Does the poster include sensitive or potentially distressing material? | single_choice | Required | Always |
| AW06 | What sensitive-content precautions or tone should the design follow? | long_text | Optional | AW05 = yes |
| AW07 | Who is the campaign organiser or sponsoring organisation? | long_text | Optional | Always |
| AW08 | What contribution instructions and beneficiary details must appear? | long_text | Required | PF02H ∈ fundraiser, charity |
| AW09 | What action can viewers take locally? | long_text | Optional | PF02H = community |
| AW10 | Describe the other awareness campaign | long_text | Required | PF02H = other |


### Recruitment & Opportunities

**Activation:** `PF02A = recruitment`.

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| REC01 | Which organisation is offering the opportunity? | short_text | Required | Always |
| REC02 | Which positions or opportunities are available? | repeater | Required | Always |
| REC03 | What are the eligibility criteria and qualifications? | long_text | Required | Always |
| REC04 | What responsibilities, benefits or opportunity details should be highlighted? | long_text | Optional | Always |
| REC05 | How should applicants submit their applications? | single_choice | Required | Always |
| REC06 | Give exact application instructions and destination | long_text | Required | Always |
| REC07 | What is the application deadline? | date | Required | Always |
| REC08 | Which documents are required from applicants? | long_text | Optional | Always |
| REC09 | Must an equal opportunity or official disclaimer appear? | single_choice | Required | Always |
| REC10 | Provide the exact disclaimer | long_text | Required | REC09 = yes |
| REC11 | Describe any interview, audition or selection instructions | long_text | Optional | PF02I = casting |
| REC12 | Describe the custom opportunity | long_text | Required | PF02I = other |


### Celebrations & Personal Events

**Activation:** `PF02A = celebrations`.

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| CEL01 | Whose occasion is being celebrated? (Name exactly as it should appear) | short_text | Required | Always |
| CEL02 | What is the occasion, theme or celebration message? | long_text | Required | Always |
| CEL03 | Is this a public announcement or a private invitation? | single_choice | Required | Always |
| CEL04 | Should RSVP information appear? | single_choice | Required | CEL03 = invite |
| CEL05 | Provide RSVP contact or instructions | short_text | Required | CEL04 = yes |
| CEL06 | What birthday age or milestone should appear (if any)? | short_text | Optional | PF02J = birthday |
| CEL07 | Names of the couple | repeater | Required | PF02J = wedding |
| CEL08 | Degree, institution or graduation accomplishment to mention | short_text | Optional | PF02J = graduation |
| CEL09 | Which anniversary or milestone is being marked? | short_text | Required | PF02J = anniversary |
| CEL10 | Are there special cultural, family or memorial sensitivities to follow? | long_text | Optional | Always |
| CEL11 | What remembrance wording or service details must be used? | long_text | Required | PF02J = memorial |
| CEL12 | Describe the other personal occasion | long_text | Required | PF02J = other |


### Religious & Community

**Activation:** `PF02A = religious_community`.

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| REL01 | What is the name of the church, ministry or community organisation? | short_text | Required | Always |
| REL02 | What is the theme or main spiritual/community message? | long_text | Optional | Always |
| REL03 | Should any scripture or quotation appear? | single_choice | Required | Always |
| REL04 | Give the scripture reference and translation, or exact quotation source | short_text | Required | REL03 = yes |
| REL05 | Provide the exact scripture/quotation text or request approved wording | long_text | Required | REL03 = yes |
| REL06 | Will a pastor, guest minister, leader or speaker be featured? | single_choice | Optional | PF02K ∈ service, youth, conference, prayer, outreach, gospel |
| REL07 | Describe the ministry focus, activities or special programme | long_text | Optional | Always |
| REL08 | What is the fundraising purpose or beneficiary? | long_text | Required | PF02K = harambee |
| REL09 | Is there a fundraising target to display? (optional) | short_text | Optional | PF02K = harambee |
| REL10 | Provide approved contribution instructions and payee confirmation | long_text | Required | PF02K = harambee |
| REL11 | Should the design quote a Bible passage rather than announce an event? | single_choice | Optional | PF02K = scripture |
| REL12 | Describe the community announcement and who it applies to | long_text | Required | PF02K = community |
| REL13 | Describe the other religious/community purpose | long_text | Required | PF02K = other |


### Other / Custom

**Activation:** `PF02A = other`.

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| CUS01 | Tell us exactly what you are creating and who it is for | long_text | Required | Always |
| CUS02 | What information absolutely must appear? | long_text | Required | Always |
| CUS03 | Are there any unusual specifications or constraints? | long_text | Optional | Always |
| CUS04 | Upload a sample brief or design reference | file_upload | Optional | Always |


## 19. Shared core for the other six design services

These sections are reused once across non-poster services, so project title, brand preferences, colours and deadlines are never asked multiple times. META01 remains the canonical project title.


### CORE01 — Project foundation

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| CORE01B | Briefly describe what you need and why | long_text | Required | Always |
| CORE01C | Who is the intended audience? | multi_choice | Required | Always |
| CORE01D | What should the audience understand, feel or do? | long_text | Required | Always |


### CORE02 — Existing brand, content and assets

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| CORE02A | Do you have existing brand assets, content or design references? | single_choice | Required | Always |
| CORE02B | Upload approved assets or a reference | file_upload | Optional | CORE02A = yes |
| CORE02C | What parts of your supplied material must remain unchanged? | long_text | Optional | Always |


### CORE03 — Visual direction

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| CORE03A | What visual style do you prefer? | multi_choice | Required | Always |
| CORE03B | How should colours be chosen? | single_choice | Required | Always |
| CORE03C | Choose a palette | palette_select | Required | CORE03B = palette |
| CORE03D | Choose custom colours | color_multi_picker | Required | CORE03B = custom |
| CORE03E | Enter official brand colours or HEX codes | long_text | Required | CORE03B = brand |
| CORE03F | Which colours should be avoided? | short_text | Optional | Always |
| CORE03G | Describe any imagery or typography preferences | long_text | Optional | Always |


### CORE04 — Delivery and approvals

| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| CORE04A | When do you need the finished work? | date | Required | Always |
| CORE04B | What files or handover materials are needed? | multi_choice | Required | Always |
| CORE04C | How do you want to handle the budget? | single_choice | Required | Always |
| CORE04D | Minimum budget | money | Required | CORE04C = range |
| CORE04E | Maximum budget | money | Required | CORE04C = range |
| CORE04F | Who approves the result? | single_choice | Required | Always |
| CORE04G | Any other constraints or approval instructions? | long_text | Optional | Always |


## 20. Other six services — exact conditional fields


### Logo & Branding

**Subtype selection:** Which type of logo & branding do you need?  
**Choices:** Logo only, Logo refresh, Full visual identity, Brand guidelines, Business stationery, Other branding


| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| LB01 | What exact brand name should appear? | short_text | Required | Always |
| LB02 | Is a tagline or slogan required? | short_text | Optional | Always |
| LB03 | Is this an existing brand or a new one? | single_choice | Required | Always |
| LB04 | What does the brand do and what makes it distinctive? | long_text | Required | Always |
| LB05 | What personality should the logo communicate? | long_text | Required | Always |
| LB06 | Which logo structures appeal to you? | multi_choice | Required | Always |
| LB07 | Where will the logo be used? | single_choice | Required | Always |
| LB08 | Do you need variants? | single_choice | Required | Always |
| LB09 | Which variants matter? | multi_choice | Optional | LB08 = yes |
| LB10 | What parts of the existing identity must be retained? | long_text | Required | LB03 = existing |
| LB11 | What stationery pieces are required? | long_text | Required | LOGO_BRANDING00 = stationery |
| LB12 | Which brand guidelines or applications are expected? | long_text | Required | LOGO_BRANDING00 ∈ identity, guidelines |


### Websites & Applications

**Subtype selection:** Which type of websites & applications do you need?  
**Choices:** Business/marketing website, Portfolio, E-commerce, Booking/service platform, Dashboard/portal, Mobile app, Custom web application, Redesign, Other


| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| WA01 | What is the project, business or product name? | short_text | Required | Always |
| WA02 | What primary problem should the website or app solve? | long_text | Required | Always |
| WA03 | Is this a new product or a redesign? | single_choice | Required | Always |
| WA04 | Link to the existing website or app | url | Optional | WA03 = redesign |
| WA05 | Which pages or main screens do you need? | repeater | Required | Always |
| WA06 | What functionality is required? | multi_choice | Required | Always |
| WA07 | Describe the main user journey or task flow | long_text | Required | Always |
| WA08 | Which user roles exist? | repeater | Optional | WA06 includes roles |
| WA09 | What content, photos, products or records must be migrated or supplied? | long_text | Optional | Always |
| WA10 | Which third-party integrations or systems are required? | long_text | Optional | WA06 includes api |
| WA11 | Do you already have a domain and hosting? | single_choice | Optional | Always |
| WA12 | Which languages, accessibility or device requirements apply? | long_text | Optional | Always |
| WA13 | Are there data privacy, payment or other compliance requirements? | long_text | Optional | Always |
| WA14 | What should be delivered as the minimum first release? | long_text | Required | Always |


### Social Media Design

**Subtype selection:** Which type of social media design do you need?  
**Choices:** Single social post, Multi-slide carousel, Story/status, Cover/banner, Paid ad creative, Reusable template set, Campaign pack, Other social design


| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| SM01 | Which social platforms will use the designs? | multi_choice | Required | Always |
| SM02 | Which posts, sizes or placements do you need? | repeater | Required | Always |
| SM03 | What message or offer should each design communicate? | long_text | Required | Always |
| SM04 | Who will provide captions and hashtags? | single_choice | Required | Always |
| SM05 | Should the design include people, products or supplied photos? | single_choice | Required | Always |
| SM06 | Are these paid advertising creatives? | single_choice | Required | SOCIAL_MEDIA_DESIGN00 = ads |
| SM07 | What advertising objective, approved claims and required disclosures apply? | long_text | Required | SM06 = yes |
| SM08 | Do you need a consistent template for future posts? | single_choice | Optional | Always |
| SM09 | Carousel slides / content order | repeater | Required | SOCIAL_MEDIA_DESIGN00 = carousel |
| SM10 | What is the publishing date or schedule? | short_text | Optional | Always |
| SM11 | Are there platform brand guidelines or prohibited content to consider? | long_text | Optional | Always |


### Events & Invitations

**Subtype selection:** Which type of events & invitations do you need?  
**Choices:** Wedding invitation, Birthday invitation, Corporate invitation, Church/community event, Graduation, Save-the-date, Event ticket/pass, Digital invitation, Other invitation


| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| EI01 | What is the event or occasion name? | short_text | Required | Always |
| EI02 | Is this a public invitation, private invite or announcement? | single_choice | Required | Always |
| EI03 | Who is hosting or inviting? | short_text | Required | Always |
| EI04 | Do you need personalised guest names or individual invitations? | single_choice | Required | Always |
| EI05 | Guest/personalisation fields | repeater | Optional | EI04 = yes |
| EI06 | What invitation wording should be printed exactly? | long_text | Required | Always |
| EI07 | Does RSVP need to appear? | single_choice | Required | Always |
| EI08 | Provide RSVP deadline and instructions | long_text | Required | EI07 = yes |
| EI09 | Are there dress code, access, gift or etiquette notes? | long_text | Optional | Always |
| EI10 | Should a map, location link or QR code be used? | single_choice | Required | Always |
| EI11 | What should each invitation version differ by? | long_text | Optional | Always |
| EI12 | What is the event date? | short_text | Required | Always |
| EI13 | What is the event time and time zone? | short_text | Required | Always |
| EI14 | What is the event venue or online access information? | long_text | Required | Always |


### Brochures & Menus

**Subtype selection:** Which type of brochures & menus do you need?  
**Choices:** Corporate/product brochure, Product catalogue, Restaurant menu, Service price list, Event programme booklet, Tri-fold leaflet, Digital brochure/menu, Other


| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| BM01 | What kind of publication do you need? | single_choice | Required | Always |
| BM02 | Which sections or pages should be included? | repeater | Required | Always |
| BM03 | Do you already have approved text and item details? | single_choice | Required | Always |
| BM04 | Upload your approved content or existing menu/catalogue | file_upload | Optional | Always |
| BM05 | Products/dishes/services and descriptions | repeater | Required | BROCHURES_MENUS00 ∈ catalogue, restaurant, service |
| BM06 | Do dietary, allergen or ingredient labels apply? | single_choice | Required | BROCHURES_MENUS00 = restaurant |
| BM07 | Provide verified dietary/allergen labels and ingredients | long_text | Required | BM06 = yes |
| BM08 | Is this folded, bound or single-sheet? | single_choice | Required | Always |
| BM09 | Specify paper size, number of pages and printer requirements | long_text | Optional | Always |
| BM10 | Will prices or availability change often? | single_choice | Required | Always |
| BM11 | What should remain editable for future updates? | long_text | Optional | BM10 = yes |
| BM12 | Any required disclaimers, business contacts or ordering details? | long_text | Optional | Always |


### Packaging Design

**Subtype selection:** Which type of packaging design do you need?  
**Choices:** Product label, Box/carton, Bag/pouch, Bottle/jar wrap, Sleeve/band, Sticker/seal, Complete packaging range, Other packaging


| Field ID | Exact question / label | Type | Requirement | Show when |
|---|---|---|---|---|
| PK01 | What exact product and brand name should appear? | short_text | Required | Always |
| PK02 | Describe the product and how it is used | long_text | Required | Always |
| PK03 | What packaging structure or material will be used? | single_choice | Required | Always |
| PK04 | Which package sizes or variants exist? | repeater | Required | Always |
| PK05 | Do you have a manufacturer dieline/template? | single_choice | Required | Always |
| PK06 | Upload manufacturer dieline (PDF/SVG/image) | file_upload | Required | PK05 = yes |
| PK07 | What must appear on the front of the package? | long_text | Required | Always |
| PK08 | What must appear on the back or sides? | long_text | Optional | Always |
| PK09 | Are ingredients, nutrition, warnings or regulatory marks required? | single_choice | Required | Always |
| PK10 | Provide exact approved regulatory and safety wording | long_text | Required | PK09 = yes |
| PK11 | Are barcodes, QR codes, batch/expiry placeholders required? | single_choice | Required | Always |
| PK12 | Give code and variable-data requirements | long_text | Required | PK11 = yes |
| PK13 | What printing technique, material finish or colour constraints apply? | long_text | Optional | Always |
| PK14 | Will a physical print proof be checked before production? | single_choice | Required | Always |
| PK15 | What pack claims need evidence and approval? | long_text | Optional | Always |


## 21. Palette swatches offered as suggestions


| Palette | Hex values |
|---|---|
| Warm & Elegant | #653D30, #C88B59, #F1E7D3, #A3B18A |
| Bold & Energetic | #DD3A29, #FFC145, #184E77, #FFF9EF |
| Soft & Pastel | #D8A7B1, #E9D5CA, #B7C9B1, #F9F3EA |
| Modern & Minimal | #1C2329, #677880, #D5DDE0, #FAFAF8 |
| Luxury & Premium | #232323, #B89452, #F2E7D0, #70414B |
| Earthy & Natural | #526547, #B6A17B, #DACDB3, #F4EFE3 |

## 22. Additional field-level conventions

- `single_choice`: one allowlisted option; `multi_choice`: zero or more valid options unless required (then at least one).
- `short_text`/`long_text`: trim and validate length; display exact client wording without unapproved rewriting.
- `repeater`: validate required child fields for every active row; child names are scoped to their parent field ID.
- `date`/`time`: valid ISO values; validate ranges and scheduling consistency.
- `money`: non-negative decimal with currency; never parse through binary floating point for stored money.
- `file_upload`: uploaded asset ID reference, not trusted client filesystem path.
- `palette_select`: one known palette ID; `color_multi_picker`: list of valid 6-digit HEX codes and visual previews.
- `asset_reference`: the asset must exist and belong to the authenticated user/brief.
- `pending`: valid for draft saved state; flag readiness issues for essential design details.
- `PF01A=both` plus `PF01B=different`: store shared fields once, plus content-per-deliverable variants in PF06–PF08.
- `PF02C=yes` activates the shared event module. `PF02A=business_promotion` activates the business module.
- Provide a review screen with clear headings, outstanding items and explicit confirmation before final submit.


## 23. Acceptance scenarios by service

| Scenario | Expected outcome |
|---|---|
| Church scripture poster without event | Scripture and religious content required; EV date, time and venue hidden |
| Church youth conference poster | Shared event details and religious theme/speaker/scripture details; no concert-only questions |
| Concert poster | Shared event details, admission and performer-specific questions |
| Business sale flyer | Offer details and item pricing validated; irrelevant recruitment fields hidden |
| Corporate seminar announcement | Official wording and seminar sessions; EV branch only if event flag yes |
| Educational timetable | Repeatable day/activity rows; no event ticket fields |
| Campaign with verified statistics | Source and date captured for each statistic |
| Internship recruitment | Position, qualifications, application process and deadline required |
| Birthday invitation | Celebrant details and RSVP if private; date/location only for actual event |
| Religious harambee | Fundraising purpose and approved payment details; separate event information if held |
| Logo redesign | Existing identity and retained elements required; other service questions absent |
| E-commerce web app | Products, pages, payments, role/permission needs and privacy requirements recorded |
| Instagram carousel | Slide repeater and placement quantity; no print-only questions |
| Wedding invitation | Host, exact invitation wording, date, venue, RSVP conditional |
| Restaurant menu | Menu items and applicable allergen info; print-specific sections as needed |
| Packaging label | Dieline and approved regulatory copy captured; pending manufacturer specs flagged |
| Draft change category | Hidden branch answer excluded from submission, old draft can be restored |
| Two users request same brief id | Unauthorized cross-user access rejected |
| Submission and revision | Immutable submission snapshots remain visible after revision |
| QR selected without valid URL | Not marked ready, shown as actionable missing item |

## 24. Completion definition

A feature is complete only if (1) user-facing question label and inputs are implemented, (2) visibility/required logic matches the catalog, (3) client draft and resumption work, (4) server rejects invalid or unauthorized submissions, (5) review and designer views preserve correct active answers, (6) historical revisions remain intact, and (7) automated tests pass. Work should be described as proposed or implemented accurately, never assumed.

