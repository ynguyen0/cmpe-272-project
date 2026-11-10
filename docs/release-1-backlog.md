# LexFlow release 1: requirements and prioritized backlog

Baseline: 2026-11-09. Updated: 2026-11-10. Status: architecture and project foundation implemented; full release workflows remain incomplete. See [architecture](architecture.md) and [current story status](development-record.md#story-tracking).

## Purpose and scope

This backlog translates [the project abstract](lexflow_abstract.pdf), sections I–III, and the requested first-release feature list into testable work. Release 1 demonstrates secure collaboration around clients and cases, documents, tasks, deadlines, personal work summaries, and accountability. All stories below are required for release 1. Priority determines build order, not optional scope.

Client self-service, email/push reminders, external calendar integration, electronic signatures, advanced reports, and cloud deployment remain future work, as described in the abstract. Release 1 uses synthetic demonstration data only. Legal deadline calculation is outside scope; users enter dates explicitly.

The detailed rules below are proposed baseline decisions, not claims that the abstract specifies them. Record revisions in [the development record](development-record.md). The abstract targets December 4, 2026 for final materials, subject to the instructor's official deadline; this backlog does not claim earlier milestone completion.

## Roles and permissions

Each active account has exactly one role: **Administrator**, **Attorney**, or **Staff**. There is no public registration. Administrators have access to all records within this single-firm prototype, including user administration and audit review. Attorneys and staff need both the role permission below and the applicable case assignment. A role alone never grants them access to an unassigned case.

| Action | Administrator | Attorney | Staff |
| --- | --- | --- | --- |
| Create/deactivate users; change roles; review audit log | Yes | No | No |
| Create clients; access own unlinked clients | Yes | Yes | Yes |
| View/search/update linked clients | All | If assigned to any linked case | If assigned to any linked case |
| Create a case | Yes | Yes; automatically assigned | No |
| View case and its active documents, tasks, deadlines | All | Assigned cases | Assigned cases |
| Edit case details, link clients, manage team/status | All | Assigned cases | No |
| Upload/download documents; create/edit tasks and deadlines | All open cases | Assigned open cases | Assigned open cases |
| Archive documents | All open cases | Assigned open cases | No |
| Complete/reopen a task | All open cases | Assigned open cases | Own tasks in assigned open cases |
| View personal dashboard | Yes | Yes | Yes |

An unlinked client is visible/editable only to its creator and administrators. Once linked, case-based access replaces creator access. Access to a shared client never grants access to its other cases, their names, or their contents. A client page lists only cases the viewer may access. Only an administrator or assigned attorney may link an existing client, and they must already be allowed to view that client. Administrators can handle cross-team linking. Removing an assignment immediately removes case access, including previously copied URLs.

## Shared acceptance rules

These rules are acceptance criteria for **every** story, including the negative tests. Each story adds specific examples below.

- **G1 — Authorization:** enforce permissions on the server for list, search, detail, download, and mutation requests; hiding a button is insufficient. Missing/expired authentication returns 401. A forbidden role action returns 403; an inaccessible or nonexistent record ID returns the same 404 response. Failures expose no record contents, counts, filenames, or storage URLs and make no business-data change. Search, summaries, and related records use the same filters.
- **G2 — Validation:** trim surrounding whitespace; reject blank required fields, excessive lengths, unknown enums/fields, invalid identifiers, and invalid relationships. Invalid requests return field errors (400 or 422), preserve entered nonsecret values, and make no partial change. Treat free text as text, never executable HTML. Recheck permissions and referenced records at write time.
- **G3 — Integrity:** generate immutable IDs, creator, and creation/update timestamps server-side. Persist successful changes across refresh and restart. Use transactions for multi-record changes. Reject stale edits with 409 and offer reload rather than silently overwriting changes. Do not expose password fields in responses.
- **G4 — State:** closed cases and their documents/tasks/deadlines are readable to authorized users but immutable except for reopening by an administrator or assigned attorney. Client records can still be corrected. There is no hard-delete endpoint for clients, cases, documents, users, tasks, deadlines, or audit entries in release 1. Archive applies only to documents.
- **G5 — Accountability:** record successful reads/searches/downloads and mutations, authentication events, and authorization denials under LOG-01/02. A mutation and its audit event succeed together or neither commits. Never log passwords, session tokens, document contents, or client contact/notes text.

## Data and state decisions

Lengths are maximum characters unless noted; IDs and timestamps are generated, not entered. Optional fields may be blank. Dates must be real ISO `YYYY-MM-DD` calendar dates. The firm's display timezone is `America/Los_Angeles`; store event timestamps in UTC. Date-only deadlines and task due dates retain their calendar date and do not shift with browser timezone.

| Record | Required user-entered fields | Optional fields and constraints |
| --- | --- | --- |
| User | Full name (1–100); unique email (≤254, valid email syntax, case-insensitive uniqueness); role | Password on creation: 12–128 characters; active flag defaults true; no account deletion or email change in release 1 |
| Client | Display/legal name (1–150); type: `Individual` or `Organization` | Email (valid syntax, ≤254), phone (≤30; digits, spaces, `+()-`), address (≤500), notes (≤2,000); duplicate names allowed and distinguished by ID |
| Case | Title (1–200); at least one accessible client; at least one active attorney | Summary (≤2,000); system-generated unique case number; default status `Open` |
| Document | Accessible case; file; title (1–200); category | Categories: `Pleading`, `Evidence`, `Correspondence`, `Contract`, `Other`; state `Active` or `Archived`; preserve uploader, original filename, media type, size, and upload time |
| Task | Open case; title (1–200); one active assigned case member; due date | Description (≤2,000); default status `To do`; past dates allowed for recording overdue work |
| Deadline | Open case; title (1–200); date; type | Types: `Hearing`, `Filing`, `Meeting`, `Other`; notes (≤2,000); default status `Pending`; past dates allowed |

- **Case transitions:** `Open → On hold → Open`; either `Open` or `On hold → Closed`; `Closed → Open`. Both `Open` and `On hold` permit normal edits (the permission matrix's “open cases” includes both). Closing requires every task to be `Done` and every deadline to be `Completed` or `Cancelled`; otherwise return 409 with the accessible blockers. Reopening requires at least one active assigned attorney; an administrator may supply one as part of the same reopen transaction if all previous attorneys became inactive or changed role while the case was closed. No bulk override.
- **Tasks:** `To do → In progress → Done`, `To do → Done`, and `Done → To do` (reopen); `In progress → To do` also allowed. Set completion time on `Done`; clear it on reopen. Reject all other transitions and unknown statuses.
- **Deadlines:** `Pending → Completed` or `Cancelled`; `Completed/Cancelled → Pending` on an editable case. A pending item dated before today is overdue; today through today + 7 calendar days inclusive is upcoming. Completed/cancelled items are excluded. Tasks use the same date rules, excluding `Done`.
- **Assignments:** only active attorneys/staff may be team members; administrators have global access and need no membership. Retain at least one active attorney per nonclosed case. Block removal, deactivation, or role change that would leave a nonclosed case without one, or leave unfinished tasks assigned to a nonmember/inactive user. Return 409 with blockers the administrator/attorney can resolve first. Done tasks retain historical attribution. Reassignment must target an active member of the same case.
- **Files:** accept `.pdf`, `.docx`, `.txt`, `.png`, `.jpg`, `.jpeg` only, matching server-validated content type/signature (UTF-8 text for TXT; valid DOCX container for DOCX). Reject empty, corrupt, encrypted, disguised, or unsupported files, path-bearing filenames, and files larger than 10 MiB (10,485,760 bytes). Use generated private storage keys; original names are display metadata. Downloads require a fresh authorization check and attachment disposition. No public file URLs or inline preview. Duplicate filenames are separate document IDs; no overwrites or versioning.
- **Archive:** one-way `Active → Archived`, with actor/time and required reason (1–500). Keep the file and metadata; hide from default lists and all download paths immediately. Authorized case members may explicitly include archived metadata; archived bytes remain unavailable even to administrators in release 1. Repeated archive requests return 409. Restoration, retention automation, and physical purge are deferred.

## Ordered backlog

Priority **P0** establishes security and the case/client workflow; **P1** completes daily work; **P2** completes release evidence. All are release blockers. Build in listed dependency order within each priority. Each item is a small independently verifiable story; its ID is stable across code, tests, issues, and demo evidence. Current partial implementation and ownership are tracked in the [development record](development-record.md#story-tracking); unlisted items remain Planned/unassigned.

### P0 — Identity, permissions, clients, and cases

#### AUTH-01 — Sign in (depends on USER-01)
As an authorized user, I can sign in to access my work.
- Valid credentials for an active account establish an authenticated session and open the personal dashboard. Passwords are stored using the chosen framework's maintained password hashing facility, never plaintext.
- Blank/malformed input is rejected; an unknown email, incorrect password, and inactive account show the same generic failure. After five failed attempts per normalized email within 15 minutes, further attempts for that email are blocked until that window expires; successful login resets its failure count.
- Require HTTPS outside loopback development; use Secure (outside loopback), HttpOnly, SameSite session cookies, rotate the session at login, and protect cookie-authenticated mutations against CSRF. Unauthenticated requests follow G1; password/token values never appear in logs.

#### AUTH-02 — Sign out and expire sessions (depends on AUTH-01)
As a signed-in user, I can end my session securely.
- Sign out revokes the server session and clears its cookie; replaying it returns 401. Signing out again is harmless.
- Sessions expire after 30 minutes of inactivity or 8 hours absolute lifetime; the next protected request returns 401. Invalid session values are rejected without a server error.
- Deactivation revokes all user sessions; role/assignment changes take effect on the next request, including existing sessions. Browser back/refresh after sign-out cannot retrieve protected data; sensitive responses use `Cache-Control: no-store`.

#### USER-01 — Create accounts (foundation)
As an administrator, I can create accounts for authorized colleagues.
- A documented local bootstrap command creates the first administrator without public registration or committed credentials; subsequent accounts require an authenticated administrator. Supply name, email, role, and initial password; return the generated ID and active status without echoing the password.
- Duplicate normalized emails, weak/blank passwords, invalid roles, and missing fields are rejected atomically. Initial passwords are handed to demo users locally; self-service password recovery is deferred.
- Attorney, staff, and anonymous calls cannot create users or enumerate the administration list.

#### USER-02 — Deactivate users and change roles (depends on USER-01, ACCESS-01)
As an administrator, I can deactivate accounts and assign roles.
- Display users and change one account's role or active state; retain existing records and historical actor IDs. Reactivation is supported and does not resurrect revoked sessions.
- Reject unknown roles/IDs, repeated deactivation, and changes blocked by assignment rules. Prevent deactivation/demotion of the last active administrator; reject self-deactivation/demotion to prevent accidental lockout.
- Nonadministrators cannot list users through administration or change roles/status, including their own. Case assignment selectors expose only active eligible users' IDs, names, and roles to authorized case managers.

#### ACCESS-01 — Enforce role and assignment boundaries (depends on AUTH-01)
As an attorney or staff member, I can access only permitted records and actions.
- Apply the permission matrix to every API and private file route; authorized list/search/detail and mutation operations succeed within their permitted scope.
- Test each role against every action, plus assigned/unassigned cases, unlinked/shared clients, and guessed IDs; altering a case/client ID in a valid request never bypasses checks. An invalid relationship is rejected even if both IDs exist.
- Removing membership or changing role takes effect on the next read/write/download. Shared-client results never disclose inaccessible case names or counts. All negative paths follow G1.

#### CLIENT-01 — Create clients (depends on ACCESS-01)
As an attorney or staff member, I can register a client before opening a case.
- Save valid required/optional fields and show the generated ID; a new unlinked client is available to its creator and administrators.
- Missing name/type, invalid contact format, and excessive lengths produce field errors. Duplicate names are allowed; selection/results show IDs to distinguish them.
- A different nonadministrator cannot read or update the unlinked client by ID; anonymous creation fails.

#### CLIENT-02 — View and search clients (depends on CLIENT-01)
As a team member, I can find clients I am allowed to serve.
- List authorized clients and search by case-insensitive name substring or exact ID, with deterministic name/ID ordering and pages of at most 25. Blank search lists authorized clients; no matches shows an empty state.
- Reject malformed IDs, invalid page values, and search text longer than 150 characters; never interpret search text as code or SQL.
- Results, totals, detail views, and linked-case lists contain only authorized records, including after membership removal.

#### CLIENT-03 — Update client details (depends on CLIENT-02)
As an authorized team member, I can correct client information.
- Update permitted fields and see the saved values after refresh; blank optional fields clear their values. Preserve immutable ID and creation metadata.
- Reject invalid email/phone, blank name, and stale edits without partial changes.
- Users lacking current client access cannot update it; request fields cannot replace creator or grant access to another case.

#### CASE-01 — Create a case and link its first clients (depends on CLIENT-01)
As an attorney, I can open a case for existing clients.
- Create a case with title, one or more accessible clients, and at least one active attorney. Assign the attorney creator automatically; an administrator creator must select an active attorney. Generate a case number and `Open` status atomically.
- Reject empty titles/client lists, duplicate links, invalid/inaccessible clients, inactive members, and teams without an attorney. A failed create leaves no orphan case or links.
- Staff and anonymous users cannot create cases; an attorney cannot use creation to gain access to an inaccessible client.

#### CASE-02 — Find, view, and update cases (depends on CASE-01)
As a case team member, I can see the case and keep its details current.
- List/search authorized cases by number/title, filter by status, and view title, summary, authorized clients, team, and status; use pages of at most 25 with deterministic case-number ordering. Administrators/assigned attorneys can edit title and summary on editable cases.
- Reject unknown filters, blank title, invalid pagination, excessive search text (>200), and stale edits; empty search results show an empty state.
- Staff have read access but cannot edit case details; unassigned users cannot discover cases or related contents through search/detail.

#### CASE-03 — Maintain client links and team assignments (depends on CASE-02)
As an assigned attorney, I can connect clients and colleagues to a case.
- Add/remove accessible client links and active attorney/staff members; keep at least one client. Newly assigned users immediately gain case access; removed users lose it.
- Reject duplicate links/members, unknown/inaccessible client IDs, inactive users, removing the final client, closed-case edits, and assignment-rule blockers. No partial team/link changes occur.
- Staff and unassigned attorneys cannot change links/team. Linking a client does not expose its other cases; an attorney cannot link a client they cannot already access.

#### CASE-04 — Track case status (depends on CASE-03, TASK-03, DATE-02)
As an assigned attorney, I can pause, close, and reopen a case.
- Apply the case transition rules and display the current status after refresh; log each change.
- Reject unknown/invalid transitions, closing with unfinished tasks or pending deadlines, and reopening without an active assigned attorney; list the blockers. Closed-case mutations fail until reopening, except the administrator's atomic attorney assignment during reopen.
- Staff and unassigned attorneys cannot change status, including through direct requests. An assigned attorney or administrator can reopen a closed case.

### P1 — Documents, work tracking, dashboard, and audit

#### DOC-01 — Upload and categorize documents (depends on CASE-02)
As a case team member, I can add a categorized file to an editable case.
- A permitted file with title/category creates active metadata and a private file linked to that case; repeated filenames do not overwrite. A failed upload leaves neither a visible record nor a stray stored file.
- Reject every invalid file condition defined above, missing title/category, unknown categories, and closed cases. Accept a file exactly 10 MiB if otherwise valid; reject 10 MiB + 1 byte.
- Anonymous/unassigned uploads fail without saving bytes; changing the submitted case ID cannot target an inaccessible case.

#### DOC-02 — List, recategorize, and download documents (depends on DOC-01)
As a case team member, I can find and retrieve the correct active document.
- List active case documents, filter by category, and download identical bytes with the original display filename. Team members may update title/category on an editable case, preserving file/creator metadata.
- Reject invalid category/title/filter and stale edits; unknown document IDs return 404. Changing bytes requires a new upload, never an update to an existing file.
- Deny guessed storage URLs and unassigned downloads/updates. Archived files cannot be downloaded, and closed cases allow authorized downloads but reject metadata changes.

#### DOC-03 — Archive documents (depends on DOC-02)
As an assigned attorney, I can retire a document without deleting its history.
- Archive with a reason, actor, and timestamp; default lists hide it. An explicit archived filter shows retained metadata and reason to authorized case members.
- Reject missing/overlong reason, repeated archive, and closed-case archive. Retain original bytes privately; no restore/delete operation exists.
- Staff/unassigned users cannot archive; all roles are denied archived downloads, including via a previously copied URL.

#### TASK-01 — Create and assign tasks (depends on CASE-03)
As a case team member, I can assign work with a due date.
- Create a `To do` task with title, description, due date, and one active member of the same case. The assignee sees it in their work list after refresh.
- Reject missing title/date/assignee, impossible dates, inactive/nonmember assignees, and closed cases; past dates are accepted and shown as overdue.
- Unassigned users cannot create tasks or use the assignee selector to enumerate a different case's team.

#### TASK-02 — Edit and reassign tasks (depends on TASK-01)
As a case team member, I can update task details and responsibility.
- Update title, description, date, or assignee to another active case member; preserve task ID, creation metadata, and current status.
- Reject invalid dates, blank title, inactive/nonmember reassignment, closed-case changes, and stale edits. Changing the task's case ID is prohibited.
- Unassigned users cannot read or change tasks; reassignment removes the item from the previous assignee's personal work list without granting access to another case.

#### TASK-03 — Track completion (depends on TASK-01)
As a task assignee, I can report progress and finish my work.
- Apply allowed task status transitions and completion timestamps; `Done` tasks leave overdue/upcoming counts. Reopening recalculates date-based indicators.
- Reject unknown/invalid transitions, missing status, and changes on closed cases without modifying the task.
- Staff can change only their own task status; administrators/assigned attorneys may change any task status in an editable permitted case. An unassigned user cannot complete a task, even if historically its assignee.

#### DATE-01 — Record and edit deadlines (depends on CASE-02)
As a case team member, I can record important dates.
- Create a pending deadline with title, type, date, and optional notes; edit those fields on an editable case. Permit multiple deadlines on one date and historical dates.
- Reject missing/impossible dates, blank title, invalid type, excessive notes, stale edits, and changing the deadline's case ID.
- Unassigned users cannot read/create/edit deadlines; closed-case edits fail.

#### DATE-02 — Show and resolve upcoming/overdue dates (depends on DATE-01)
As a case team member, I can see outstanding deadlines and mark them resolved.
- Show case deadlines sorted by date then ID, with overdue/upcoming labels using the shared inclusive date rules. Apply allowed completion/cancellation/reopen transitions.
- Reject invalid status transitions and closed-case updates. Completed/cancelled items remain in history but leave pending date summaries; an empty list has a clear empty state.
- Unassigned users cannot read or resolve deadlines. Verify today, yesterday, today + 7, and today + 8 using a fixed test clock, including a timezone/date boundary.

#### DASH-01 — Summarize personal work (depends on TASK-03, DATE-02, DOC-02)
As a signed-in user, I can see what needs my attention.
- Show my assigned nonclosed cases; my unfinished tasks grouped into overdue/upcoming; and pending overdue/upcoming deadlines for my assigned nonclosed cases. Administrators see their own tasks and all nonclosed cases/deadlines, labeled as firm-wide. Counts match the linked filtered lists; task lists sort by due date then ID and deadlines by date then ID.
- After completion, reassignment, closure, or membership changes, refresh shows recalculated counts. A new user with no work sees zeros and empty states, never sample or unrelated data. Invalid filter/date input is rejected.
- Dashboard data and links obey G1 even when called directly; removing membership removes all related summary items on the next request.

#### LOG-01 — Record access and changes (foundation alongside ACCESS-01)
As an administrator, I can rely on a history of relevant access and changes.
- Append an event with UTC time, actor ID (or unauthenticated marker), action, resource type/ID when known, result, and request correlation ID for login success/failure/logout, expiry/deactivation revocation, user/role changes, reads/searches, uploads/downloads, archive, creates/edits, assignment changes, and status changes. Record failed validation as a failure event without submitted sensitive values.
- Mutation events contain changed field names and non-sensitive status/assignment IDs, not client text or file contents. Search/read events omit search text and response contents. No passwords/tokens are recorded; invalid input cannot inject log structure.
- Clients cannot submit actor/time or update/delete events; nonadministrators cannot fetch logs. Failed authorization is logged without disclosing inaccessible record data to the caller.

#### LOG-02 — Review activity (depends on LOG-01)
As an administrator, I can investigate relevant access and changes.
- Show newest-first events, ordered by time then ID, with actor, action, resource, result; filter by actor, action, resource ID, and UTC date range; paginate at most 50 per page.
- Reject invalid filters, reversed date ranges, excessive range (>31 days), and invalid page values; no matches shows an empty state. Default range is the most recent 7 days.
- Only administrators may query logs; results contain no secrets or document/client body text. Audit-log review itself creates an event after the query, without recursive logging.

### P2 — Release evidence and handoff

#### DEL-01 — Run functional and security checks (depends on all P0/P1 stories)
As a reviewer, I can reproduce evidence that the prototype meets its requirements.
- Provide runnable automated tests mapped below, a fixed-clock date suite, file boundary fixtures, and a permission suite across roles/assignments. Cover each story's valid, invalid, and unauthorized criteria and G1–G5; run against persistent storage and private document delivery.
- Replace the Jenkinsfile's echo-only build/test stages with real install/build/test commands after the stack is selected. A deliberately failing test makes CI fail; an empty/skipped suite cannot count as a pass. Record command, commit, environment, counts, and results.
- Demonstrate that forged requests/IDs, stale sessions/edits, invalid uploads, and failed transactions neither change protected data nor expose secrets. A failing security requirement blocks release; do not mark planned tests as passed.

#### DEL-02 — Maintain reproducible source and project documentation (starts immediately)
As a teammate, I can run the prototype and understand its decisions and progress.
- Commit application source, dependency lockfiles, schema/migrations, synthetic seed data, and setup/run/test instructions. Document framework/database choice, entity relationships, permission model, UI navigation, configuration, file storage, backup/restore, and known limits. A clean checkout follows the instructions successfully.
- Keep real secrets/data out of source and use an example environment file with placeholders; missing configuration produces an actionable startup error without printing secrets. Restore a synthetic database/file backup and verify relationships and a downloaded file.
- For each change, update the development record and traceability with requirement IDs, rationale, owner/date, code/test evidence, and remaining gaps. Documentation must not expose actual credentials or claim tests/deliverables that do not exist.

#### DEL-03 — Present and demonstrate release 1 (depends on DEL-01/02)
As a reviewer, I can follow a repeatable demonstration and inspect the delivered materials.
- Deliver the final report, presentation, demo video or file, and source repository through the team leader, following the instructor's confirmed deadline. Map slides/demo segments to the steps below and record final artifact locations and commit.
- Rehearse from a clean synthetic seed; include valid workflows, invalid-input rejection, access denial, archive denial, and audit evidence. If a required workflow fails, record the defect and rerun after correction; a prerecorded success alone does not close a known failure.
- Demonstration credentials/data are synthetic; presentation/video/source contain no real client data, private secrets, or live session tokens. Confirm every required story has implementation, passing test evidence, and a demo checkpoint before sign-off.

## Requirements traceability

### Foundation evidence (2026-11-10; partial stories)

The local `sh scripts/check.sh` run passed 18 Django tests and one Chromium workflow, with no skipped tests, against Docker PostgreSQL 16.13 / Python 3.12.14. These are scaffold checks, not a full release acceptance pass. Changes are in the working tree with no commit/PR yet. No hosted CI run, full D1–D10 rehearsal, or full story completion is claimed.

| Requirement | Actual implementation | Actual tests / evidence | Demonstrated subset and gaps |
| --- | --- | --- | --- |
| AUTH-01/02 | [User](../accounts/models.py), [form](../accounts/forms.py), [routes](../accounts/urls.py), [cache middleware](../accounts/middleware.py), [settings](../config/settings/base.py) | [AuthenticationTests](../tests/test_foundation.py), [Chromium workflow](../tests/browser/test_workflow.py) | D2/D10 subset: email login, invalid credentials, inactive rejection, CSRF, logout/replay; throttling/idle/absolute policies and audit remain |
| USER-01 | [Custom user/manager](../accounts/models.py), [migration](../accounts/migrations/0001_initial.py); Django `createsuperuser` | `AccountTests` in [foundation tests](../tests/test_foundation.py) | D1 subset: bootstrap role, password hash, normalized unique email; account-management UI/services remain |
| ACCESS-01, CLIENT-02 | [Filtered case/client policies](../cases/policies.py) | `PermissionTests` in [foundation tests](../tests/test_foundation.py) | D4 subset: role/membership scope, shared/unlinked clients, removed membership; client UI and complete action matrix remain |
| CASE-02 | [Read views](../cases/views.py), [templates](../templates/cases/index.html) | `PermissionTests`, [browser workflow](../tests/browser/test_workflow.py) | D4 subset: assigned list/detail, guessed ID denial; search, paging, edit/conflicts remain |
| DOC-01/02/03 (storage foundation only) | [Private storage](../documents/storage.py), [metadata schema](../documents/models.py) | `DemoCommandTests.test_private_files_have_no_url_or_public_route` in [tests](../tests/test_foundation.py) | Private fixture bytes and no public file route verified; upload, authorized download, archive workflows are not implemented |
| DEL-01 | [Shared checks](../scripts/check.sh), [GitHub workflow](../.github/workflows/ci.yml), [Jenkinsfile](../Jenkinsfile) | Local run: format/lint/system/migration checks, 18 Django + 1 Chromium passed; `SettingsTests` includes configured deployment checks | D9 subset: real commands and local results; hosted CI and full feature/security suite remain |
| DEL-02 | [Setup](../README.md), [architecture](architecture.md), [review/DoD](../CONTRIBUTING.md), [seed command](../accounts/management/commands/seed_demo.py), [dependency lock](../uv.lock) | `DemoCommandTests`, `DemoRollbackTests`, `SettingsTests`; fresh local Docker migration + seed | D9 subset: setup/migrations/fixtures, rerun safety and rollback; independent teammate reproduction and backup/restore remain |

### Full release targets

The table below remains the full-release plan, **not evidence of completion**. `I-*` names identify logical components. `T-*` names reserve complete test groups whose cases must map to the story's individual acceptance bullets and G1–G5. Foundation evidence above links actual partial implementations; replace target labels with further actual paths and result/commit links as each story is completed. Demo steps are defined below. None of these release-level test groups is claimed fully passing yet.

| Requirement | Abstract/request coverage | Planned implementation | Planned test group | Demo |
| --- | --- | --- | --- | --- |
| AUTH-01 | Secure login | I-Identity: sign-in/session creation | T-AUTH-01 credentials, throttle, cookie/CSRF | D1, D2 |
| AUTH-02 | Secure logout/access | I-Identity: revocation/expiry | T-AUTH-02 replay, fixed-clock expiry, deactivation | D2, D10 |
| USER-01 | User administration (request) | I-Users: bootstrap/create/list | T-USER-01 bootstrap, validation, admin boundary | D1 |
| USER-02 | User administration (request) | I-Users: roles/activation | T-USER-02 blockers, last admin, revocation | D1, D10 |
| ACCESS-01 | Role-based security; assignments (request) | I-Policy: centralized permission checks | T-ACCESS-01 full permission matrix, ID tampering | D2, D4, D10 |
| CLIENT-01 | Client management | I-Clients: create | T-CLIENT-01 required fields, creator scope | D3 |
| CLIENT-02 | Client management/search (request) | I-Clients: filtered list/detail/search | T-CLIENT-02 search, paging, shared-client scope | D3, D4 |
| CLIENT-03 | Client management | I-Clients: update | T-CLIENT-03 validation, stale update, scope | D3 |
| CASE-01 | Create cases | I-Cases: transactional creation | T-CASE-01 links, automatic membership, rollback | D4 |
| CASE-02 | Update cases/status | I-Cases: list/detail/edit | T-CASE-02 filters, staff boundary, conflicts | D4 |
| CASE-03 | Collaboration/assignments (request) | I-Cases: team/client links | T-CASE-03 minimum links/team, access removal | D4, D10 |
| CASE-04 | Case progress | I-Cases: status transitions | T-CASE-04 close blockers, read-only, reopen | D7 |
| DOC-01 | Upload/organize documents | I-Documents: validation/private upload | T-DOC-01 each type, disguise/size, rollback | D5 |
| DOC-02 | Documents/download (request) | I-Documents: list/edit/authorized download | T-DOC-02 byte equality, filters, private routes | D5 |
| DOC-03 | Archive (request); accountable deletion alternative | I-Documents: archive state | T-DOC-03 retention, repeat, download denial | D5 |
| TASK-01 | Assign work | I-Tasks: create/assign | T-TASK-01 dates, active membership, scope | D6 |
| TASK-02 | Coordinate work | I-Tasks: edit/reassign | T-TASK-02 reassignment, conflict, scope | D6 |
| TASK-03 | Track completion (request) | I-Tasks: transitions | T-TASK-03 timestamps, staff ownership, scope | D6 |
| DATE-01 | Record important dates | I-Deadlines: create/edit | T-DATE-01 field/date validation, scope | D6 |
| DATE-02 | Monitor deadlines | I-Deadlines: pending/date queries/transitions | T-DATE-02 fixed-clock boundaries, history, scope | D6, D7 |
| DASH-01 | Personal summary (request) | I-Dashboard: authorized aggregates | T-DASH-01 counts, refresh, empty/boundary cases | D7 |
| LOG-01 | Activity tracking | I-Audit: append-only event writer | T-LOG-01 event coverage, redaction, atomicity | D8 |
| LOG-02 | Accountability/auditing | I-Audit: admin query UI/API | T-LOG-02 filters, ordering, role denial | D8 |
| DEL-01 | Functional/security testing | I-Quality: test suites and Jenkins pipeline | T-DEL-01 real CI run and induced failure | D9 |
| DEL-02 | Continuous docs/design/source/backups | I-Delivery: docs, source, seed, backup tooling | T-DEL-02 clean setup/restore and evidence review | D9 |
| DEL-03 | Report/presentation/demo/submission | I-Delivery: final artifacts and demo fixture | T-DEL-03 rehearsal and artifact checklist | D1–D10 |

## Prototype demonstration contract

Use a resettable seed with Admin A, Attorney A, Attorney B, Staff A, and one inactive account. Case Alpha belongs to Attorney A and Staff A; Case Beta belongs only to Attorney B. Include separate clients plus a shared client, one unlinked client per attorney, active and archived documents, and tasks/deadlines dated yesterday, today, +7, and +8 relative to the demo date. Use a controlled test clock for automated boundary checks; derive demo dates on seed reset. Never use real matter data.

| Step | What the prototype must demonstrate | Observable evidence |
| --- | --- | --- |
| D1 | Bootstrap/admin login, create accounts, reject duplicate email, change a role | Valid accounts/roles persist; nonadmin administration denied |
| D2 | Invalid/inactive login, valid login, anonymous access and guessed case URL | Generic login failure; 401/404; no confidential content |
| D3 | Create client, reject invalid email, search and update | Saved details survive refresh; unrelated unlinked client absent |
| D4 | Attorney creates case, links clients, assigns team, changes details | Generated case number; staff can read; unassigned attorney cannot; shared client does not reveal Beta |
| D5 | Upload/categorize/download a valid file; reject disguised/oversize file; archive | Download byte match; no failed-upload residue; archived download denied and metadata retained |
| D6 | Assign/reassign a task, move through statuses; enter/resolve deadlines | Assignee work list changes; invalid date/nonmember rejected; historical records remain |
| D7 | Show overdue/upcoming dashboard; attempt blocked closure, resolve work, close/reopen | Counts match dates/lists; blockers explained; closed edits rejected; reopen succeeds |
| D8 | Administrator filters access/change events; staff attempts log access | Events identify actor/action/time/result without secrets; staff denied |
| D9 | Show source, setup/design docs, CI/test results, restore evidence, report/slides | Traceability points to actual code/tests/run/commit; final artifacts open successfully |
| D10 | Remove Staff A after resolving/reassigning unfinished work; deactivate a user; sign out | Old case/download URLs denied; deactivated/replayed sessions rejected; records/history retained |

## Release completion and ongoing tracking

- A story is done only when all its criteria and G1–G5 pass, code is reviewed, actual implementation/test evidence is linked in the traceability row, and its demo step is rehearsed. Update its status/owner in the development record; never delete its stable ID.
- Release 1 is done when all 26 stories are done, functional/security defects affecting acceptance are resolved, reproducible source/docs and final presentation/demo/report are available, and the team can run D1–D10. Deferred scope and known nonblocking limitations must be explicit.
- At each development session and scope change, record decisions, progress, completed features, failures, test results, and changes in the development record. Link the implementing commit/PR and affected IDs; update this baseline and traceability in the same change.
- Confirm the official instructor deadline and team leader before submission; the abstract's date is a planning target, not evidence of submission.
