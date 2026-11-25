# Functional, integration, security, and usability test results

Date: 2026-11-25 (America/Los_Angeles). Tester: Codex.
Requirements: [release backlog](release-1-backlog.md), especially G1–G5,
ACCESS-01, DEL-01 and DEL-02. Tested merge: local parent
`07cf9c4` (testing) + incoming main `87150abaf29abae9b32ec709317e9c1aedc17a15`,
with the conflict resolutions and regression fixes in this working tree. This is
local evidence, not hosted CI or independent release approval.

**Previously blocked feature journeys now pass locally.** Deadline creation and
resolution, task edits/transitions/reopening, dashboard recalculation and audit
filtering/denial capture are available and exercised. All prior Q-004–Q-007 defects
are retested below. Full release approval still requires the separate team review,
complete backlog/demo review, and operational checks listed in the limitations.

## Environment and isolation

- macOS, Python 3.12.14, Django 5.2.19, PostgreSQL/pg_dump 16.13,
  Playwright 1.65.0 with Chromium. Development `.env` provides connection settings;
  credentials are not included here.
- Django creates/destroys `test_lexflow`. `config.settings.test` creates a private
  temporary media root per process. All records and files are synthetic; no
  development records or uploads are changed by tests.
- The restore drill generates `test_lexflow_recovery_<uuid>`, restores into that
  database and an empty temporary media directory, and drops the database in
  `finally`. It compares SHA-256 hashes with source fixtures, verifies relationships,
  downloads active and archived files, and denies the other case's attorney.
- Interactive exploration used another generated `test_lexflow_exploratory_<uuid>`
  database and temporary files at `127.0.0.1:8765`. The server was stopped and its
  database and temporary files removed afterward.

## Commands and observed results

Run with PostgreSQL healthy and compatible `pg_dump`/`pg_restore` on PATH:

```sh
docker compose up -d --wait db
sh scripts/check.sh
```

For this sandbox, the equivalent run used
`UV_CACHE_DIR=/private/tmp/lexflow-uv-cache sh scripts/check.sh` with permission to
connect to local PostgreSQL and launch Chromium. The initial run could not access
the default uv cache or PostgreSQL; the service was then started and checks rerun.
No failed or unexecuted test is counted as a pass.

| Run | Observed result |
| --- | --- |
| Unmodified baseline | 71 Django tests + 7 Chromium tests passed; no skips |
| New regression suite before fixes | Found date-only task acceptance and unexpected multipart field acceptance; corrected test-harness assumptions separately |
| Expanded Django suite including real backup/restore | 80 tests passed before the final staff-route matrix was added |
| New combined browser/role tests after harness corrections | 2 passed |
| Previous testing branch check | 81 Django + 9 Chromium tests passed (90 total), zero skips |
| Merged feature check | 181 Django + 10 Chromium tests passed (191 total), zero skips; dependency audit reported no known vulnerabilities |
| First full check with failure-event fix | 184 Django tests ran; 2 existing exact-event assertions needed the newly required validation.failed event added to their expected sets. Updated those assertions; no checks were removed. |
| Additional audit regression before fix | Invalid deadline, stale task write, and invalid audit-filter requests had no failure event; 3 new regressions reproduced the gap |
| Final shared check after merge and audit fix | **184 Django + 10 Chromium tests passed (194 total), zero skips; exit 0.** Dependency audit: no known vulnerabilities. Format/lint, Django system checks, migration drift, schema round trip, and paired database/document recovery all passed. |

The shared check runs dependency vulnerability auditing, formatting, lint, Django system checks, migration drift,
functional/security/schema/migration/recovery tests, then browser tests. The new
modules are included in [scripts/check.sh](../scripts/check.sh). Missing PostgreSQL
clients or Chromium fail the run; there are no environment-based skips.

## Requirements and test coverage

These rows describe tested behavior and its limits, rather than declaring each
entire backlog story complete.

| Area / requirements | Executable evidence | Coverage and limits |
| --- | --- | --- |
| Validation / G2, CLIENT-01/03, CASE-01/02 | [Client](../tests/test_clients.py), [case](../tests/test_cases.py), [schema](../tests/test_schema.py), [quality](../tests/test_release_quality.py) tests | Required fields, contact formats, duplicate warnings/references, invalid relationships, unsupported fields, failed transactions |
| Permissions / G1, ACCESS-01, USER-01/02 | [Permission matrix](../tests/test_permissions.py), `ProtectedOperationTests` in [quality tests](../tests/test_release_quality.py), [accounts](../tests/test_accounts.py) | Inventory of all 32 current case/client/task/deadline/dashboard/search/audit routes; anonymous/deactivated sessions, wrong case, removed membership, staff role denials, CSRF, unsupported methods, and unchanged business rows. Existing suites exercise permitted operations and grant revocation. Inventory test fails when a route is added without an explicit test entry. Account management GET/POST denial is also covered. All incoming task/deadline mutations are included in that inventory. |
| Integration / CLIENT, CASE, DOC, TASK | [Combined Chromium journey](../tests/browser/test_release_workflow.py) and [existing workflows](../tests/browser/test_workflow.py) | Create client → create case/team → upload/download byte equality → assign/edit task → create/edit deadline → staff moves task through In progress/Done/reopen/Done → verify dashboard → attempt blocked closure → complete/reopen/cancel deadline → remove membership → copied URLs denied → close case → logout. All writes go through the browser UI. |
| Files / DOC-01/02/03, G3 | [Documents](../tests/test_documents.py), [permissions](../tests/test_permissions.py), [recovery](../tests/test_recovery.py) | Exact size boundary, oversize, disguised/corrupt files, storage/audit failure compensation, scan failure, private delivery, archive retention, unauthorized downloads. Hosted ClamAV daemon integration is still an operator check. |
| Sessions / AUTH-01/02, USER-02 | [Account tests](../tests/test_accounts.py), [account browser workflow](../tests/browser/test_account_workflow.py) | Logout/replay, idle/absolute expiry, reset expiry/reuse, role change, deactivation/reactivation revocation, CSRF, generic failure messages |
| Audit / G5, LOG-01/02 | [Audit tests](../tests/test_audit.py), `ValidationAuditTests` in [quality tests](../tests/test_release_quality.py), [Chromium audit workflow](../tests/browser/test_release_workflow.py) | Actor/action/resource/UTC-date filters, range/page validation, safe fields and correlation IDs, access-denial capture, transactional mutation rollback, and redacted failure events for invalid forms/filters and stale writes. Browser filtering and invalid-range errors pass. |
| Concurrency / G3 | `WorkValidationTests` in [quality tests](../tests/test_release_quality.py), [schema](../tests/test_schema.py), [accounts](../tests/test_accounts.py) | Two HTTP sessions read the same task revision; first save succeeds, stale save returns 409 and preserves the first change. Existing client/case/account revision checks also run. This is a stale-editor scenario, not a load or deadlock stress test. |
| Time / G2, TASK-01, DATE-01/02 | `WorkValidationTests`, `RevisionAndTimezoneTests`, [migration tests](../tests/test_migrations.py) | Fixed winter local/UTC equality; invalid/impossible, date-only task, nonexistent DST and ambiguous DST input rejected; schema/migration tests preserve historical due dates. Date-only input is intentionally unsupported under the revised date/time baseline. [Deadline boundary tests](../tests/test_deadlines.py) now exercise the +7/+8 inclusive window across spring-forward and fall-back; [dashboard tests](../tests/test_dashboard.py) verify linked-list counts, ordering, completion and revocation refresh. |
| Recovery / DEL-02 | [Real restore test](../tests/test_recovery.py), [operator instructions](document-operations.md) | Actual PostgreSQL dump/restore with matching documents, source/restored hash equality, case links/memberships, authorized active/archived downloads, and unrelated-user denial. Does not establish production recovery time/objective or offsite backup reliability. |
| Usability / DEL-01 | [Chromium release workflow](../tests/browser/test_release_workflow.py) and interactive charters below | Keyboard login, retained form input/readable errors, empty states, 320/390 px viewport overflow checks, permitted actions per role, useful 403/404 return links. No screen-reader audit or non-Chromium certification claimed. |

## Interactive exploratory charters

Performed through the app's browser controls, separately from the scripted suite,
including a second isolated session after merging main,
with the isolated seeded environment described above. This was agent-led interactive
exploration; independent human usability acceptance remains a team review step.

| Role / charter | Observation | Result |
| --- | --- | --- |
| Administrator: sign in, inspect empty case workspace and Accounts, sign out | All workspace totals zero without memberships; Accounts lists synthetic users; sign out returns to login | Pass |
| Attorney A: inspect Alpha clients/team/documents/tasks/deadlines; attempt closure | Alpha is visible; closure lists unfinished tasks and pending deadlines and retains Open status. Deadline rows provide no resolution action | Original observation: closure protection passed; Q-004 blocked resolution. See merged retest below. |
| Staff A: inspect actions, open edit form, change description, visit copied Accounts URL, sign out | Only docket/description fields editable; change persists; no team/upload/assignment controls without grants; direct Accounts URL returns 403 | Permission behavior passes; original bare denial page tracked as Q-003 |
| Denied-page retest | New 403/404 templates retain generic resource wording and provide a return link; automated Chromium role checks exercise the fix | Pass |
| Merged Attorney A retest: resolve seeded overdue deadline, return to dashboard | Deadline changes to Completed, offers Reopen, and overdue-deadline count drops from 1 to 0 | Pass |
| Merged granted Administrator retest: filter audit by deadline.resolve | Only the completed deadline event remains; actor, UTC timestamp, result, resource and changed field names are shown; submitted completion notes are absent | Pass |

## Defect register

Severity: S1 = access/data-loss/core-journey blocker; S2 = acceptance or significant
usability failure; S3 = minor. Fixed items retain reproduction steps and retest
results. Implementation from main is attributed to that merge; Codex owns the listed
merge/regression fixes and their local retests. Independent review is still pending.

| ID / requirement | Severity / owner | Reproduction and expected behavior | Fix / retest |
| --- | --- | --- | --- |
| Q-001 / TASK-01, G2 | S2; Codex | POST a valid task with `due_at=2026-11-25`. Previously saved midnight despite the required time. Expect 400 and no task. | Fixed: explicit date/time field, local input widget and timezone help. Date-only, impossible-date and DST regressions pass. The same date/time field now validates task edits and deadline create/edit forms. |
| Q-002 / G2 | S2; Codex | Add `unexpected_file` to an otherwise valid multipart client-create/task-assign/task-reassign POST. Previously saved the record/change while ignoring the field. Expect unsupported-field error and no business change. | Fixed: bind request files to every case/client/task mutation form so `StrictFields` checks both collections. Regression suite passes. Extended the same fix to incoming task edit/status and deadline create/edit/resolve/reopen forms; no privilege escalation was observed. |
| Q-003 / usability | S2; Codex | As Staff A, open `/accounts/manage/`; previously only a bare Forbidden heading appeared with no return path. | Fixed: generic 403/404 explanations and Return to my cases links. Chromium role checks pass; no inaccessible record details rendered. |
| Q-004 / DATE-01/02, CASE-04, D6/D7 | S1; implemented on main, retested by Codex | Before the merge, open seeded Alpha as its attorney: pending deadlines appeared without create/edit/resolve controls. Attempt closure: pending dates block it permanently through the UI. Expect deadline creation/resolution with notes, audit, validation and permission tests. | Fixed on main; retest passes in deadline integration tests, complete Chromium journey and interactive resolution. Actor/time/reason, reopen/cancel, closure blockers and eventual closure are verified. No direct database workaround used. |
| Q-005 / DASH-01, DATE-02 | S2; implemented on main, retested by Codex | Finish a task and refresh the workspace. Previously, totals counted all unarchived tasks, including Done; overdue/upcoming date groups and filters were absent. Expect unfinished/pending groups with now/+7/+8 and DST boundary evidence. | Fixed on main; dashboard/list count, date-window/DST, ordering, completion and membership-change tests pass. Browser task/deadline completion removes items from the upcoming cards; interactive overdue deadline count changes from 1 to 0. |
| Q-006 / TASK-02/03 | S2; implemented on main, retested by Codex | Before the merge, existing tasks offered only reassign/complete; title/date editing, In progress and reopening were absent. Expect all required edit/status transitions and history. | Fixed on main; task detail editing and allowed/forbidden status tests pass. Chromium exercises In progress → Done → To do → Done and preserves completion metadata. |
| Q-007 / LOG-01/02, G5 | S2; implemented on main; final failure-event fix and retest by Codex | Before the merge, the granted administrator's audit list lacked actor/action/resource/date filters, and denied/invalid record requests lacked complete event capture. Expect filtered, validated review and complete safe audit events. | Fixed: main supplies filters and denial capture; the merge retest found invalid/stale requests still lacked failure events. Added validation.failed events for case-domain 400/409 responses after the view transaction, using actor/URL resource only. Invalid deadline, stale task and invalid audit-filter regressions verify one redacted event and unchanged business data. Audit integration and Chromium filtering/range checks pass. |

No access-control bypass or data-loss defect was observed in the exercised cases.
This does not close the unimplemented acceptance criteria above.

## Dedicated integration period and sign-off

After each feature's tests pass, use a separate integration pass before presentation:

1. Run the shared checks against isolated PostgreSQL and files. Record revision,
   environment, commands, counts, failures and skips here; retest each fixed defect.
2. Rehearse the complete client → case → upload → task → deadline journey and
   revocation/recovery using synthetic data; rerun the three role charters.
3. Resolve all S1 defects and security/data-loss/core-workflow failures. Required
   acceptance failures remain blockers regardless of severity label. Review every
   backlog row, not only tests that currently exist.
4. Obtain the separate teammate review required by [CONTRIBUTING](../CONTRIBUTING.md)
   and document any explicitly accepted nonblocking limits and final demo revision.

Current outcome: the previously blocked feature checks and complete synthetic core
journey pass locally; no Q-001–Q-007 defect remains open. This is not a declaration
that every release story or presentation deliverable is complete. Independent team
review, the full D1–D10 rehearsal, browser breadth beyond Chromium, hosted
scanning/HTTPS/SMTP, production restore rehearsal, hosted CI results, and final
presentation artifacts remain outside this local run's evidence.
