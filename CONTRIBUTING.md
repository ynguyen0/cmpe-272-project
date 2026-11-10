# Team workflow and shared definition of done

Work from small branches (`codex/…` for agent-created branches). Link stable backlog
IDs in the PR title/body and keep one reviewable change per PR. Open a pull request to
the team's default branch; no direct pushes, self-approval, or merging failed checks.
At least **one other team member** reviews each PR, including tests, permissions,
migrations, setup instructions, and requirement coverage. Resolve review comments
before merging. This is the team policy effective with this scaffold.

Repository administrators should enforce that policy through GitHub branch protection
or a ruleset: require a PR, one approving review, dismiss stale approvals, resolve review
threads, and require `CI / checks` (select the exact reported check name after the first
run). Remote protection is not enabled by these files; verify it in repository settings.
Do not claim a local check as a GitHub CI run. No specific reviewers are hardcoded
because team GitHub handles/ownership have not been confirmed.

## Before requesting review

- Run `uv sync --locked` and `sh scripts/check.sh` against dedicated local PostgreSQL.
- Add meaningful functional, invalid-input, and permission tests for changed behavior;
  include a browser workflow when changing a user journey. Never skip tests to pass CI.
- Generate/commit migrations and test a fresh database initialization when changing schema.
- Keep secrets and real client data out of source, seeds, screenshots, and test artifacts.
- Update the requirements traceability and development record with affected IDs, actual
  code/test paths, command/results, design changes, and remaining gaps.

## Definition of done

A change is done when its acceptance criteria pass, checks pass without unexplained
skips, another team member approves, migration/configuration instructions are current,
and its evidence and demonstration scope are recorded. A backlog story is done only
when **all** its criteria and G1–G5 pass; a model or skeleton is partial implementation.

For this establishment step, a teammate must be able to follow the root README from
a clean checkout: locked install → local configuration → healthy PostgreSQL → migrations
→ fictional seed → checks (including Chromium) → application startup/sign-in. Deployment
settings must fail closed for missing secrets and pass the deployment system check when
configured. Full release completion remains governed by the backlog's release checklist.

## CI runners

GitHub Actions is the primary pull request check. It installs Python 3.12, pinned uv,
locked dependencies, Chromium/system packages, and a dedicated PostgreSQL service.
Its database password is a public, ephemeral CI-only value, never deployment credentials.
Its signing key is generated for each job. Workflow permissions are read-only.

For Jenkins, provision Python 3.12, uv 0.12.15, Chromium system dependencies, and a
dedicated PostgreSQL service with test database creation permission. Inject
`DJANGO_SECRET_KEY`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`,
`POSTGRES_HOST`, and optionally port/test database through Jenkins credentials/environment,
never the Jenkinsfile. The pipeline installs locked packages and Chromium, then runs the
same `scripts/check.sh` as GitHub Actions. It does not target a production database.
