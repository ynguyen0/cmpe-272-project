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

## Progress and change log

| Date | Entry | Affected IDs | Owner | Evidence / result / remaining work |
| --- | --- | --- | --- | --- |
| 2026-11-09 | Established requirements baseline from abstract sections I–III and requested release features; added roles, data/state rules, acceptance criteria, traceability, and demo contract. | All; DEC-01–08 | Documentation author; team ownership unassigned | Backlog is ready for planning. Repository contains abstract, overview, and placeholder Jenkins pipeline; no application implementation or test pass is claimed. Team must assign owners, choose stack, and implement/validate stories. |

For each subsequent entry, copy this structure (replace every placeholder):

| Date | Entry | Affected IDs | Owner | Evidence / result / remaining work |
| --- | --- | --- | --- | --- |
| YYYY-MM-DD | Decision/change/progress/defect; old → new behavior and rationale; cite superseded DEC-ID if applicable | Story/decision IDs | Named team member | Commit/PR; actual code and test paths; command/environment/run date; passed/failed/skipped counts; demo step/artifact; remaining gap and next action |

## Story tracking

Initial status for every story: **Planned**; owner: **Unassigned**. The backlog has 26 stories. Add an entry here when assigning or changing status, using `Planned`, `In progress`, `Blocked`, `In review`, or `Done`; keep a current row per affected story. Record blockers and test failures even when no feature is completed. Done requires the backlog's completion checks.

| Story ID | Owner | Current status | Implementation / test run / demo evidence | Blocker or next action |
| --- | --- | --- | --- | --- |
| (add story ID when work starts) | Unassigned | Planned | None | Team assignment and stack selection |

## Submission record

TBA. Fill in the confirmed instructor deadline, team leader, release commit/tag, final report, presentation, demonstration video/file, source repository, test report, known limitations, and submission confirmation when available. Do not mark submission complete without evidence.
