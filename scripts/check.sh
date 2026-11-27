#!/bin/sh
set -eu

# Gate on every reported vulnerability, including known-exploited advisories
# present in the feed. Do not suppress findings or ignore the audit exit code.
uv run --locked pip-audit --timeout 15
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked python manage.py check --settings=config.settings.test
uv run --locked python manage.py makemigrations --check --dry-run --settings=config.settings.test
uv run --locked python manage.py test tests.test_accounts tests.test_audit tests.test_dashboard tests.test_landing tests.test_cases tests.test_tasks tests.test_deadlines tests.test_clients tests.test_documents tests.test_foundation tests.test_permissions tests.test_release_quality tests.test_recovery tests.test_schema tests.test_migrations tests.test_observability --settings=config.settings.test --noinput
uv run --locked python manage.py test tests.browser --settings=config.settings.test --noinput
