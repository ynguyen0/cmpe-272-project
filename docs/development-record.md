# LexFlow development record

This is the continuing record required by the abstract. Keep entries chronological and append dated changes; preserve superseded decisions and explain their replacement. The [release 1 backlog](release-1-backlog.md) is the current requirements baseline.

## Initial decision register

These are proposed implementation defaults established on 2026-11-09, pending team review. They make acceptance testable; they do not represent decisions stated verbatim in the abstract. Change them through the log below and update affected criteria/tests/demo steps together.

| Decision | Baseline and reason | Affected requirements |
| --- | --- | --- |
| DEC-01 | Single firm; one role per account; admin has global access; attorney/staff require case assignments. Gives a concrete prototype permission boundary. | USER-01/02, ACCESS-01, all record stories |
| DEC-02 | Unlinked clients belong to creator/admin; linked clients use case membership; shared clients never reveal other cases. Supports intake and confidentiality. | CLIENT-01/02/03, CASE-01/03 |
| DEC-03 | Enumerated case/task/deadline states and closure blockers; no hard deletion. Preserves history and makes status behavior predictable. | CASE-04, TASK-03, DATE-02, LOG-01 |
| DEC-04 | Six file extensions, content validation, private downloads, 10 MiB maximum, one-way archive with metadata retention and no archived download. Bounds document scope. | DOC-01/02/03 |
| DEC-05 | Firm dates use America/Los_Angeles; events use UTC; upcoming is today through +7 inclusive. Removes boundary ambiguity. | TASK-01/03, DATE-01/02, DASH-01 |
| DEC-06 | Framework-managed password hashing, cookie sessions, explicit expiry/throttling/CSRF requirements; no public registration or self-service recovery. Makes prototype sign-in measurable. | AUTH-01/02, USER-01 |
| DEC-07 | Append-only, redacted audit events for reads and changes; admin-only review; atomic mutation/event persistence. Supports accountability without logging sensitive bodies. | LOG-01/02, all mutations |
| DEC-08 | All backlog stories required; P0/P1/P2 indicate sequence; no stack selected; traceability targets are planned. Avoids confusing a plan with delivered evidence. | All, DEL-01/02/03 |
| DEC-09 | Team selected a Django monolith with templates/Bootstrap, PostgreSQL in development/tests, private filesystem storage, Django/Chromium tests, and GitHub CI. Supersedes DEC-08's undecided-stack portion; all stories remain required. See [architecture](architecture.md) and [setup](../README.md). | All; particularly DEL-01/02 |
| DEC-10 | One custom email-based user model, one explicit role, and filtered read querysets for case/client access. Django groups/model permissions alone do not grant case access. Initial schema and read pages are partial implementation; transactional write policies and audit capture remain future stories. | AUTH-01/02, USER-01, ACCESS-01, CLIENT-02, CASE-02, LOG-01 |
| DEC-11 | Locked Python 3.12 dependency set, separate settings, private files with no public URL, environment-only deployment secrets, repeatable non-destructive fictional seeding, and one-peer PR review policy. Remote branch-protection enforcement remains repository-admin configuration. | DOC-01/02/03, DEL-01/02/03 |

## Progress and change log

| Date | Entry | Affected IDs | Owner | Evidence / result / remaining work |
| --- | --- | --- | --- | --- |
| 2026-11-09 | Established requirements baseline from abstract sections I–III and requested release features; added roles, data/state rules, acceptance criteria, traceability, and demo contract. | All; DEC-01–08 | Documentation author; team ownership unassigned | Backlog is ready for planning. Repository contains abstract, overview, and placeholder Jenkins pipeline; no application implementation or test pass is claimed. Team must assign owners, choose stack, and implement/validate stories. |
| 2026-11-10 | Established the team-selected architecture, six domain apps, initial migrations, email sign-in/out and assigned-case read pages, private files, fictional seeding, locked dependencies, environment settings, real CI commands, PR template/review policy, and root setup README. | DEC-09–11; AUTH-01/02, USER-01, ACCESS-01, CASE-02, DEL-01/02 (partial) | Codex implementation; team review pending | Local working tree; no commit/PR created. `uv sync --locked` succeeded with Python 3.12.14, Django 5.2.19, PostgreSQL 16.13 (Docker). `manage.py migrate` and two `seed_demo` runs succeeded; `runserver` startup and HTTP login/static/root-redirect smoke checks passed. `sh scripts/check.sh`: Ruff format/lint, system check, migration drift, **18 Django tests + 1 Chromium workflow passed, 0 skipped**. Configured `check --deploy --fail-level WARNING` passed. Private Bootstrap CSS hash matches upstream. Port 5432 was occupied; only local ignored `.env` was changed to 55432. GitHub/Jenkins hosted runs and remote branch protection are not claimed. Release acceptance remains incomplete; see foundation traceability below. |

For each subsequent entry, copy this structure (replace every placeholder):

| Date | Entry | Affected IDs | Owner | Evidence / result / remaining work |
| --- | --- | --- | --- | --- |
| YYYY-MM-DD | Decision/change/progress/defect; old → new behavior and rationale; cite superseded DEC-ID if applicable | Story/decision IDs | Named team member | Commit/PR; actual code and test paths; command/environment/run date; passed/failed/skipped counts; demo step/artifact; remaining gap and next action |

## Story tracking

Initial status for every story was **Planned**; owner: **Unassigned**. The backlog has 26 stories. Rows below override that initial state; unlisted stories remain Planned/unassigned. Use `Planned`, `In progress`, `Blocked`, `In review`, or `Done`; keep a current row per affected story. Record blockers and test failures even when no feature is completed. Done requires the backlog's completion checks; no full release story is Done yet.

| Story ID | Owner | Current status | Implementation / test run / demo evidence | Blocker or next action |
| --- | --- | --- | --- | --- |
| AUTH-01 | Codex; team owner pending | In progress | `accounts/models.py`, `forms.py`, `urls.py`; `AuthenticationTests`; Chromium workflow | Throttling, audit capture, and full story acceptance remain |
| AUTH-02 | Codex; team owner pending | In progress | `accounts/urls.py`, `middleware.py`; session replay/deactivation tests | Idle/absolute lifetime policies and lifecycle logging remain |
| USER-01 | Codex; team owner pending | In progress | Custom user, initial migration, `createsuperuser`; `AccountTests` | Administrator account-management UI/services remain |
| ACCESS-01 | Codex; team owner pending | In progress | `cases/policies.py`, filtered views; `PermissionTests` and browser denial | Full action/mutation matrix and every-domain integration remain |
| CASE-02 | Codex; team owner pending | In progress | `cases/views.py`, templates; read visibility tests | Search, filters, paging, edits, and conflict checks remain |
| DEL-01 | Codex; team owner pending | In progress | `scripts/check.sh`, workflow, Jenkinsfile; 19 local tests passed on 2026-11-10 | Expand tests with release workflows; hosted CI/induced-failure evidence remains |
| DEL-02 | Codex; team owner pending | In progress | Root README, architecture, lock, migrations, seed, contributing policy | Teammate review/reproduction, backup/restore and final delivery docs remain |

## Submission record

TBA. Fill in the confirmed instructor deadline, team leader, release commit/tag, final report, presentation, demonstration video/file, source repository, test report, known limitations, and submission confirmation when available. Do not mark submission complete without evidence.
