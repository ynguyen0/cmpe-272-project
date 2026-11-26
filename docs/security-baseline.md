# Security baseline verification — issue #26

Verified: 2026-11-26. Owner: ynguyen0. Repository:
[ynguyen0/cmpe-272-project](https://github.com/ynguyen0/cmpe-272-project).
This records live GitHub checks separately from local code and test evidence.
**Issue #26 remains incomplete until team-wide GitHub and cloud MFA are verified.**

## Requirement status

| Requirement | Status | Evidence / action |
| --- | --- | --- |
| Turn on secret scanning and dependency alerts | Verified enabled | Authenticated repository API reports `secret_scanning`, `secret_scanning_push_protection`, and `dependabot_security_updates` enabled. `GET /repos/ynguyen0/cmpe-272-project/vulnerability-alerts` returned HTTP 204, confirming Dependabot alerts enabled. Secret-scanning and Dependabot alert lists both had zero open alerts at verification. |
| Dependency scan and CI failure on known-exploited flaws | Implemented; merge gate enabled during this audit | Both GitHub Actions and Jenkins run [scripts/check.sh](../scripts/check.sh), starting with locked `pip-audit` under `set -eu`. Any reported vulnerability fails, without severity filtering, ignored advisories, or `continue-on-error`. Live `main` protection now requires the successful GitHub Actions `checks` job. |
| Replace long-lived CI cloud keys with workload identity | Not applicable to the current GitHub CI; no OIDC deployment implemented | Tracked workflow/Jenkinsfile contain no cloud authentication or deployment. GitHub repository Actions secrets count is zero and environments list is empty. There is no organization-secret source because the repository owner is a personal account. The ephemeral test database password and generated signing key are not cloud credentials. External Jenkins controller/agent credentials were not accessible for verification. |
| Ownership/authorization check on every ID endpoint, with tests | Existing checks retained; regression coverage expanded | Scoped case/client querysets and parent-child filters protect record endpoints. Account administration uses administrator authorization; password recovery binds tokens to the account. Tests and route inventory are detailed below. |
| Require MFA for every team member on GitHub and the cloud account | Blocked on account administration / target identification | This is a personal-account repository (`owner.type=User`), not an organization. There is no repository-level organization MFA policy to enable. The user API did not disclose the owner's MFA state, and collaborator MFA states were not available. The cloud provider, account, identity system, and team roster have not been supplied. No MFA status is inferred from repository access. |

## CI gate and dependency scan

Before this audit, `main` had neither branch protection nor repository rulesets.
Applied branch protection and independently read it back:

- Require `checks` from the GitHub Actions app, ID **15368**; the exact check name
  was obtained from successful check runs on `main`.
- Require the branch to be up to date before merging.
- Require one approving review, dismiss stale reviews, and resolve review threads.
- Enforce protection for administrators; disallow force pushes and branch deletion.

The [workflow](../.github/workflows/ci.yml) grants only `contents: read` and uses
[the shared script](../scripts/check.sh). A successful audit does not compensate
for a failing test or check. Jenkins calls the same script, but its external job
configuration and merge integration were not verified.

Local `uv run --locked pip-audit` exited 0 with **No known vulnerabilities found**.
A controlled failure-injection check placed a temporary `uv` stub first on PATH,
returned exit 1 for the initial audit, and verified `sh scripts/check.sh` returned
nonzero without invoking later commands. The stub did not alter dependencies or
the real audit tool.

This policy blocks all vulnerabilities reported by the configured advisory feed,
which includes reported known-exploited vulnerabilities. It does not separately
query CISA KEV or promise detection before the advisory feed contains a flaw.
[pip-audit documents its vulnerability sources and exit behavior](https://github.com/pypa/pip-audit).

## Endpoint authorization evidence

[ProtectedOperationTests](../tests/test_release_quality.py) inventories all 32
case/client/work/audit routes. The inventory test fails if a route is added
without being listed. Every record route is exercised with a wrong-case user and
a revoked membership; GET and POST are both checked where applicable, including
no business-data changes and no protected text in denial responses.

Added `test_every_nested_record_rejects_a_child_from_another_accessible_case`:
for every nested document/task/deadline route, give the actor access to both
cases, pair a child ID with the wrong parent case, and require 404 with no
protected text and no business-data changes. This tests parent-child binding
independently of case-membership denial.

Account routes are defined in [accounts/urls.py](../accounts/urls.py). The only
numeric record route, `accounts:access`, calls `require_administrator` before
loading its target, with another check inside the serialized write.
Protected-operation and [account tests](../tests/test_accounts.py) cover anonymous,
deactivated, and nonadministrator access. Ownership alone would be insufficient
here: administrators intentionally manage other accounts.

The other account-ID route is `password_reset_confirm`, whose user identifier is
paired with a signed, expiring, single-use recovery token. Added
`test_recovery_token_cannot_be_used_with_another_account_identifier`: use a Staff
token with the administrator's identifier, try GET and POST, and verify neither
password changes and no successful reset event is recorded. Existing tests cover
expiry, reuse, revocation, and CSRF.

Additional action-specific coverage remains in [permissions](../tests/test_permissions.py),
[cases](../tests/test_cases.py), [clients](../tests/test_clients.py),
[documents](../tests/test_documents.py), [tasks](../tests/test_tasks.py), and
[deadlines](../tests/test_deadlines.py). No missing application authorization check
was found during this audit; changes add regression coverage.

## Workload identity boundary

No static cloud key was found to replace in the current tracked CI configuration
or GitHub Actions secret inventory. Do not add an unused OIDC role or token
permission to a test-only workflow. When cloud deployment is introduced, use the
provider's short-lived workload federation, limit token issuance to the deployment
job, and restrict provider trust to this repository and its approved deployment
branch/environment. Review external Jenkins credentials before declaring that
runner free of long-lived cloud keys. Current CI does not demonstrate OIDC login.

## Remaining owner actions for MFA

GitHub collaborators currently listed by the repository API are `ynguyen0`,
`Sptailor`, and `alicemdao`. Their presence does not prove MFA enrollment.

1. Confirm each collaborator has MFA enabled and retains recovery access. For
   centrally enforced team MFA, identify an organization that will own the
   repository, confirm enrollment, and require MFA there. Repository transfer
   and removal of collaborators were not performed as part of this audit.
   [GitHub documents organization MFA enforcement and its access impact](https://docs.github.com/en/organizations/keeping-your-organization-secure/managing-two-factor-authentication-for-your-organization/requiring-two-factor-authentication-in-your-organization).
2. Identify the cloud provider/account, sign-in system, and all team identities.
   Configure MFA enforcement in that identity system and verify that users
   cannot sign in without enrollment; include privileged and emergency access
   accounts. Individual device enrollment must be completed by each user.
3. Record dated, nonsecret evidence of the GitHub policy and cloud policy plus
   complete team coverage before marking the MFA requirement or issue #26 done.

No external messages were sent and no issue checklist was edited by this audit.

## Local validation results

On 2026-11-26, all **186 Django tests passed with no skips**, including both new
regressions. The run used Python 3.12, locked dependencies, a temporary PostgreSQL
16 instance with generated credentials, a separate test database, and test-only
private file storage. It included the recovery drill and historical migration
round trip. The temporary PostgreSQL cluster was stopped and removed afterward;
the existing development database and private documents were not used.

Command (temporary-instance connection settings supplied through the environment):

```sh
uv run --locked python manage.py test tests.test_accounts tests.test_audit tests.test_dashboard tests.test_cases tests.test_tasks tests.test_deadlines tests.test_clients tests.test_documents tests.test_foundation tests.test_permissions tests.test_release_quality tests.test_recovery tests.test_schema tests.test_migrations --settings=config.settings.test --noinput
```

`ruff check .`, `ruff format --check .`, and `git diff --check` passed. The real
dependency audit and audit-failure propagation check also passed as described
above. Chromium workflows were not rerun for these test/documentation changes.
This is local working-tree evidence, not a hosted CI run or independent review.
