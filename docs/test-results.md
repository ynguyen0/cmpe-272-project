# Functional, integration, security, and usability test results

Date: 2026-11-25 (America/Los_Angeles). Tester: Codex.
Requirements: [release backlog](release-1-backlog.md), especially G1–G5,
ACCESS-01, DEL-01 and DEL-02. Base revision:
`720fc87be954560b0ad087803403e94e5fc5707b`, plus the uncommitted testing/fix changes
in this working tree. This report is local evidence, not hosted CI or release approval.

**Presentation gate: BLOCKED.** The implemented-operation checks pass, but the full
required journey cannot complete a deadline. DATE-01/02 and other acceptance gaps
below remain open. Passing existing tests does not establish full release acceptance.

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
| Final shared check | **81 Django + 9 Chromium tests passed (90 total), zero skips**; format/lint/system/migration-drift checks passed; exit 0 |

The shared check runs formatting, lint, Django system checks, migration drift,
functional/security/schema/migration/recovery tests, then browser tests. The new
modules are included in [scripts/check.sh](../scripts/check.sh). Missing PostgreSQL
clients or Chromium fail the run; there are no environment-based skips.

## Requirements and test coverage

These rows describe tested behavior and its limits, rather than declaring each
entire backlog story complete.

| Area / requirements | Executable evidence | Coverage and limits |
| --- | --- | --- |
| Validation / G2, CLIENT-01/03, CASE-01/02 | [Client](../tests/test_clients.py), [case](../tests/test_cases.py), [schema](../tests/test_schema.py), [quality](../tests/test_release_quality.py) tests | Required fields, contact formats, duplicate warnings/references, invalid relationships, unsupported fields, failed transactions |
| Permissions / G1, ACCESS-01, USER-01/02 | [Permission matrix](../tests/test_permissions.py), `ProtectedOperationTests` in [quality tests](../tests/test_release_quality.py), [accounts](../tests/test_accounts.py) | Inventory of all 22 current case/client/audit routes; anonymous/deactivated sessions, wrong case, removed membership, staff role denials, CSRF, unsupported methods, and unchanged business rows. Existing suites exercise permitted operations and grant revocation. Inventory test fails when a route is added without an explicit test entry. Account management GET/POST denial is also covered. Future deadline endpoints must extend this inventory. |
| Integration / CLIENT, CASE, DOC, TASK | [Combined Chromium journey](../tests/browser/test_release_workflow.py) and [existing workflows](../tests/browser/test_workflow.py) | Create client → create case/team → upload/download byte equality → assign task → staff completes → remove membership → copied URLs denied → close case → logout. Deadline creation/completion is unavailable and is not simulated or counted as passed. |
| Files / DOC-01/02/03, G3 | [Documents](../tests/test_documents.py), [permissions](../tests/test_permissions.py), [recovery](../tests/test_recovery.py) | Exact size boundary, oversize, disguised/corrupt files, storage/audit failure compensation, scan failure, private delivery, archive retention, unauthorized downloads. Hosted ClamAV daemon integration is still an operator check. |
| Sessions / AUTH-01/02, USER-02 | [Account tests](../tests/test_accounts.py), [account browser workflow](../tests/browser/test_account_workflow.py) | Logout/replay, idle/absolute expiry, reset expiry/reuse, role change, deactivation/reactivation revocation, CSRF, generic failure messages |
| Concurrency / G3 | `WorkValidationTests` in [quality tests](../tests/test_release_quality.py), [schema](../tests/test_schema.py), [accounts](../tests/test_accounts.py) | Two HTTP sessions read the same task revision; first save succeeds, stale save returns 409 and preserves the first change. Existing client/case/account revision checks also run. This is a stale-editor scenario, not a load or deadlock stress test. |
| Time / G2, TASK-01, DATE-01/02 | `WorkValidationTests`, `RevisionAndTimezoneTests`, [migration tests](../tests/test_migrations.py) | Fixed winter local/UTC equality; invalid/impossible, date-only task, nonexistent DST and ambiguous DST input rejected; schema/migration tests preserve historical due dates. Date-only input is intentionally unsupported under the revised date/time baseline. No overdue/upcoming classifier exists yet, so now/+7/+8 calculation acceptance remains open. |
| Recovery / DEL-02 | [Real restore test](../tests/test_recovery.py), [operator instructions](document-operations.md) | Actual PostgreSQL dump/restore with matching documents, source/restored hash equality, case links/memberships, authorized active/archived downloads, and unrelated-user denial. Does not establish production recovery time/objective or offsite backup reliability. |
| Usability / DEL-01 | [Chromium release workflow](../tests/browser/test_release_workflow.py) and interactive charters below | Keyboard login, retained form input/readable errors, empty states, 320/390 px viewport overflow checks, permitted actions per role, useful 403/404 return links. No screen-reader audit or non-Chromium certification claimed. |

## Interactive exploratory charters

Performed through the app's browser controls, separately from the scripted suite,
with the isolated seeded environment described above. This was agent-led interactive
exploration; independent human usability acceptance remains a team review step.

| Role / charter | Observation | Result |
| --- | --- | --- |
| Administrator: sign in, inspect empty case workspace and Accounts, sign out | All workspace totals zero without memberships; Accounts lists synthetic users; sign out returns to login | Pass |
| Attorney A: inspect Alpha clients/team/documents/tasks/deadlines; attempt closure | Alpha is visible; closure lists unfinished tasks and pending deadlines and retains Open status. Deadline rows provide no resolution action | Closure protection passes; Q-004 blocks the full journey |
| Staff A: inspect actions, open edit form, change description, visit copied Accounts URL, sign out | Only docket/description fields editable; change persists; no team/upload/assignment controls without grants; direct Accounts URL returns 403 | Permission behavior passes; original bare denial page tracked as Q-003 |
| Denied-page retest | New 403/404 templates retain generic resource wording and provide a return link; automated Chromium role checks exercise the fix | Pass |

## Defect register

Severity: S1 = access/data-loss/core-journey blocker; S2 = acceptance or significant
usability failure; S3 = minor. Fixed items retain reproduction steps and retest
results. Open component ownership is explicitly pending team assignment; do not
interpret a placeholder as a teammate accepting responsibility.

| ID / requirement | Severity / owner | Reproduction and expected behavior | Fix / retest |
| --- | --- | --- | --- |
| Q-001 / TASK-01, G2 | S2; Codex | POST a valid task with `due_at=2026-11-25`. Previously saved midnight despite the required time. Expect 400 and no task. | Fixed: explicit date/time field, local input widget and timezone help. Date-only, impossible-date and DST regressions pass. |
| Q-002 / G2 | S2; Codex | Add `unexpected_file` to an otherwise valid multipart client-create/task-assign/task-reassign POST. Previously saved the record/change while ignoring the field. Expect unsupported-field error and no business change. | Fixed: bind request files to every case/client/task mutation form so `StrictFields` checks both collections. Regression suite passes. No privilege escalation was observed. |
| Q-003 / usability | S2; Codex | As Staff A, open `/accounts/manage/`; previously only a bare Forbidden heading appeared with no return path. | Fixed: generic 403/404 explanations and Return to my cases links. Chromium role checks pass; no inaccessible record details rendered. |
| Q-004 / DATE-01/02, CASE-04, D6/D7 | **S1; deadline component owner unassigned (team triage required)** | Open seeded Alpha as its attorney; pending deadlines appear, but there is no create/edit/resolve route or control. Attempt closure: pending dates block it permanently through the UI. Expect deadline creation/resolution with notes, audit, validation and permission tests. | **Open.** No workaround involving direct database writes counts as workflow acceptance. Add the feature and rerun the full deadline-inclusive browser journey before presentation. |
| Q-005 / DASH-01, DATE-02 | S2; work-summary component owner unassigned | Finish a task and refresh the workspace. Totals currently count all unarchived tasks, including Done; no overdue/upcoming date groups or filters exist. Expect unfinished/pending groups with now/+7/+8 and DST boundary evidence. | Open; no fixed-clock overdue classifier pass claimed. |
| Q-006 / TASK-02/03 | S2; task component owner unassigned | Open an existing task: only reassign/complete actions exist; title/date editing, In progress and reopening are absent. Expect all required edit/status transitions and history. | Open; current assign/reassign/complete subset passes. |
| Q-007 / LOG-01/02, G5 | S2; audit component owner unassigned | Granted administrator opens audit list: required actor/action/resource/date filters are absent. Inspect denied/invalid record requests: complete denial/validation event capture is not implemented. Expect filtered, validated review and complete safe audit events. | Open; append-only schema and existing successful mutation/account audit tests pass, but full audit acceptance remains incomplete. |

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

Current outcome: implemented-operation regression coverage improved; full release
DoD and presentation sign-off remain **not met**, pending the open acceptance gaps
and independent review. Browser breadth, hosted scanning/HTTPS/SMTP, production
restore rehearsal, hosted CI results, and final presentation artifacts remain outside
this local run's evidence.
