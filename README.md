# LexFlow

LexFlow is a law firm case management prototype built as one Django application:
Django templates and Bootstrap, PostgreSQL, and private filesystem documents.
See the [architecture](docs/architecture.md), [release backlog](docs/release-1-backlog.md),
and [team workflow/definition of done](CONTRIBUTING.md).
The [database design and ER diagram](docs/database-design.md) define the fields,
protected relationships, constraints, indexes, archive rules, and migration strategy.

The application provides email sign-in, password recovery, account administration,
and membership-scoped case and client workflows. The dashboard, search results, task
actions, and private downloads use the same case access rules. Remaining release
workflows are tracked in the backlog.

## Prerequisites

- Git, Python **3.12**, and [uv **0.12.15**](https://docs.astral.sh/uv/getting-started/installation/).
  Check with `python3.12 --version` and `uv --version`.
- Docker Desktop/Engine with Compose v2, running with Linux containers.
- macOS/Linux, or Windows using WSL2 (run these shell commands within WSL2).
- Internet for the initial Python packages, PostgreSQL image, and Chromium installation.
  Bootstrap CSS is already included locally; Node/npm is not required.

## Install and start

Run from the repository root. Each developer uses their own `.env` and local database.

```sh
git clone https://github.com/ynguyen0/cmpe-272-project.git
cd cmpe-272-project
uv sync --locked
uv run python scripts/init_env.py
docker compose up -d --wait db
uv run python manage.py migrate
uv run python manage.py seed_demo
uv run python manage.py runserver
```

Open [LexFlow locally](http://127.0.0.1:8000/). Sign in with
`attorney.a@example.test` and the `LEXFLOW_DEMO_PASSWORD` value from **your local `.env`**.
The initialization command generates unique local secrets and never prints them.
`.env.example` documents the variables with blank secret values; existing environment
variables override `.env`. If `.env` already exists, initialization exits without changing it.

The seed also creates `admin@example.test`, `attorney.b@example.test`,
`staff.a@example.test`, and `inactive@example.test`. All newly created accounts use your
local demo password; the inactive account cannot sign in. The application administrator
role is distinct from Django's `is_staff` flag. There is no Django admin route exposed.
For a non-demo bootstrap account, run `uv run python manage.py createsuperuser`;
it prompts for an email, full name, and password and assigns the Administrator role.

## Authentication and accounts

Sign in as an administrator and open **Accounts** to create a colleague’s account or
edit an existing account’s role and status. Account changes take effect on the next
request. Deactivating an account also revokes its existing sessions and reset links,
even if the account is later reactivated.

Use **Change password** from the navigation or **Forgot your password?** from the
sign-in page. In development, open the reset email in the ignored `.dev-email/`
directory. Reset links expire after 30 minutes and can be used once. Five failed
sign-in attempts for one email block further attempts for that email until the
15-minute window ends. Sessions expire after 30 minutes of inactivity or eight hours
from sign-in.

Demo records include Alpha/Beta cases with separate teams, five clients including one
shared client and two unlinked intakes, explicit case/client and team responsibility
links, two private text files (active/archived), four tasks and four deadlines due at
17:00 firm time on day -1, 0, +7, and +8, and a seed audit event. The seed administrator
can manage accounts and starts with no case memberships or additional grants.

`uv run python manage.py seed_demo` is repeatable: it does not duplicate fixture records,
delete unrelated data, change existing passwords, or reset existing task/deadline dates.
It adds expected demo case/team/client links if missing and preserves existing inactive
links rather than reactivating them. `DEMO-*` case numbers and
`@example.test` fixture emails are reserved for this command; use a dedicated local
database. To get fresh relative dates without deleting data, explicitly edit them in a
development shell or use a new empty development database. Seeding is disabled in deployment.

## Case access and explicit grants

All three roles need an active membership to access case records and documents.
Linked clients require an active link to a visible case. A never-linked intake is
visible to its creator. Staff with case access can edit the summary and court docket
number. Task completion requires the acting user to be the current assignee.

Optional capabilities use direct Django user permissions. After running migrations,
an operator can add or remove a grant in `uv run python manage.py shell`:

```python
from accounts.models import User
from django.contrib.auth.models import Permission

user = User.objects.get(email="staff.a@example.test")
grant = Permission.objects.get(
    content_type__app_label="cases",
    content_type__model="case",
    codename="manage_case_documents",
)
user.user_permissions.add(grant)
# To revoke: user.user_permissions.remove(grant)
```

| Role | Grant codename | Capability |
| --- | --- | --- |
| Staff | `create_case_records` | Create clients and cases |
| Staff | `manage_case_documents` | Upload and edit document metadata in assigned cases |
| Staff | `assign_case_tasks` | Assign and reassign tasks in assigned cases |
| Administrator | `archive_case` | Archive closed cases with active membership |
| Administrator | `view_organization_audit` | View organization-wide audit records |

The responsible attorney can archive a closed case while their membership is active.
For case access, the operator maintains `CaseMembership` rows. Setting
`is_active=False` revokes access on the next request, including copied download URLs.

## Navigation wireframe

With the development server running, open [the LexFlow wireframe](http://127.0.0.1:8000/wireframe/).
The [journey map and walkthrough](docs/navigation-and-screen-design.md) cover client intake,
case creation, document upload, and assigned work. Use fictional inputs. The preview
keeps changes in the current page and resets when refreshed.

## Run checks and browser workflows

Keep PostgreSQL running. Tests create and destroy `POSTGRES_TEST_DB` (default
`test_lexflow`), not the development database. The local Compose user has permission
to create this database. Never point tests at a real or shared deployment database.

```sh
uv run playwright install chromium
# Linux/WSL2 may first need system packages; this command may request sudo:
# uv run playwright install --with-deps chromium
sh scripts/check.sh
```

The shared script runs Ruff format/lint checks, Django checks, migration drift checks,
authentication/foundation/schema tests, a historical migration round trip, and
Chromium workflows for case access, account creation, recovery, and deactivation.
Browser tests start their own Django server and isolated test database; no development
server or seeded development data is required. Missing browsers fail the check rather
than silently skipping it. Development uses Django's normal password hashers; the fast
hasher is confined to test settings. Test files are isolated in a temporary directory.

Useful individual commands:

```sh
uv run ruff format .
uv run ruff check .
uv run python manage.py test tests.test_foundation --settings=config.settings.test --noinput
uv run python manage.py test tests.test_schema tests.test_migrations --settings=config.settings.test --noinput
uv run python manage.py test tests.browser --settings=config.settings.test --noinput
uv run python manage.py makemigrations
uv run python manage.py migrate
```

Commit migrations alongside model changes. CI rejects uncommitted migration changes.
Use `uv sync --locked` for reproducible installations; direct dependencies are pinned
in `pyproject.toml`, and transitive versions/hashes are in `uv.lock`. Upgrade dependencies
through a reviewed PR, regenerate the lock, and rerun the same checks.

## Configuration and storage

| Setting | Purpose |
| --- | --- |
| `config.settings.development` | Default for `manage.py`; local debug pages and demo seeding |
| `config.settings.test` | PostgreSQL test database, fast hashing, isolated private files |
| `config.settings.deployment` | Debug off, required hosts/origins/private path, secure cookies/HTTPS/HSTS, demo seeding disabled |

Select a settings module with `--settings=...` for management commands or
`DJANGO_SETTINGS_MODULE` in the process environment. WSGI/ASGI entry points default to
deployment settings. Only `manage.py` loads `.env`; deployment workers read their
environment directly and never load a developer `.env` implicitly.

Database name, user, password, host, signing key, and optional database TLS mode come
from the environment. Missing required configuration fails with the variable name.
For a native PostgreSQL 16 installation, create a dedicated role/database, give the
local test role `CREATEDB`, and set those variables instead of starting Compose.

Private documents default to `private-media/`. Downloads stream through the application
after checking case access. Uploaded files use generated names and restrictive
permissions. The public `static/` directory contains only application assets. See
[document operations](docs/document-operations.md) for ClamAV, backup and restore,
and cleanup commands.

For deployment, supply a separate strong key, explicit hosts, HTTPS CSRF origins, an
absolute persistent `DJANGO_PRIVATE_MEDIA_ROOT`, an absolute `DJANGO_CLAMDSCAN_PATH`
for the local ClamAV daemon, and dedicated database credentials. Configure the `DJANGO_EMAIL_*` settings and
`DJANGO_DEFAULT_FROM_EMAIL` in `.env.example` for your SMTP relay. If your proxy or
application server records access logs, redact recovery URLs under `/accounts/reset/`.
Then run:

```sh
uv run python manage.py check --deploy --settings=config.settings.deployment --fail-level WARNING
uv run python manage.py migrate --settings=config.settings.deployment
uv run python manage.py collectstatic --noinput --settings=config.settings.deployment
uv run gunicorn config.wsgi:application --bind 127.0.0.1:8000
```

For the worker command explicitly set `DJANGO_SETTINGS_MODULE=config.settings.deployment`
in the hosting environment; do not reuse the development `.env`. Configure a trusted
HTTPS reverse proxy to serve `staticfiles/` only. Cap upload request bodies at
10,551,296 bytes and keep private files outside the webroot. Proxy
header trust, certificates, database TLS, database/file backups and restore verification
must be configured for that host. This step prepares settings; it does not deploy a site.
See [deployment responsibilities](docs/architecture.md#deployment-boundary).

## Collaboration and troubleshooting

GitHub Actions runs the shared check script against PostgreSQL for pushes and pull
requests. The Jenkinsfile runs the same script on a preconfigured agent; see
[contributing](CONTRIBUTING.md) for review rules, CI prerequisites, and the definition of done.

- **Docker unavailable:** start Docker Desktop, then rerun Compose. Check `docker compose ps`.
- **Port 5432 occupied:** choose a free `POSTGRES_PORT` in `.env`, then rerun Compose.
- **Database authentication fails after editing `.env`:** PostgreSQL initializes its
  role/password only on first volume creation. Use the original local credentials or
  deliberately rotate the database role password; editing `.env` alone does not rotate it.
- **Permission to create test DB denied:** give the dedicated local/CI role `CREATEDB`;
  do not grant application deployment users this permission.
- **Missing Chromium/system libraries:** rerun the browser installation command above.
- **Seed login fails after changing the demo password variable:** existing accounts
  keep their password. Use `uv run python manage.py changepassword attorney.a@example.test`.
- **Stop local PostgreSQL:** `docker compose stop db`; restart with the normal Compose
  command. Named volumes retain the database. Back up before deliberately removing volumes.

Project planning and progress live in [the release backlog](docs/release-1-backlog.md) and
[the development record](docs/development-record.md).
