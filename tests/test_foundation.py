import os
import subprocess
import sys
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from audit.models import AuditEvent
from cases.models import Case
from clients.models import Client
from documents.models import Document
from work.models import Deadline, Task

DEMO_PASSWORD = "Fictional-test-passphrase-73!"


class SeededTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        with patch.dict(os.environ, {"LEXFLOW_DEMO_PASSWORD": DEMO_PASSWORD}):
            call_command("seed_demo", stdout=StringIO())


class AccountTests(TestCase):
    def test_email_identity_normalizes_and_rejects_case_duplicates(self):
        user = User.objects.create_user("Attorney.A@Example.test", DEMO_PASSWORD, full_name="A")
        self.assertEqual(user.email, "attorney.a@example.test")
        self.assertTrue(user.check_password(DEMO_PASSWORD))
        self.assertNotEqual(user.password, DEMO_PASSWORD)
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create(email="ATTORNEY.A@example.test", full_name="Duplicate")

    def test_bootstrap_superuser_has_administrator_role(self):
        user = User.objects.create_superuser("admin@example.test", DEMO_PASSWORD, full_name="Admin")
        self.assertTrue(user.is_administrator)
        self.assertTrue(user.is_superuser)
        with self.assertRaises(ValueError):
            User.objects.create_superuser(
                "bad@example.test", DEMO_PASSWORD, full_name="Bad", role=User.Role.STAFF
            )


class AuthenticationTests(SeededTestCase):
    def test_login_normalizes_email_and_logout_invalidates_session(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "ATTORNEY.A@EXAMPLE.TEST", "password": DEMO_PASSWORD},
        )
        self.assertRedirects(response, reverse("cases:dashboard"))
        cookie = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.assertRedirects(
            self.client.post(reverse("accounts:logout")), reverse("accounts:login")
        )
        self.client.cookies[settings.SESSION_COOKIE_NAME] = cookie
        self.assertEqual(self.client.get(reverse("cases:index")).status_code, 302)

    def test_csrf_required_and_sensitive_pages_not_cached(self):
        from django.test import Client as HttpClient

        csrf_client = HttpClient(enforce_csrf_checks=True)
        self.assertEqual(csrf_client.post(reverse("accounts:login"), {}).status_code, 403)
        response = self.client.get(reverse("accounts:login"))
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.client.force_login(User.objects.get(email="attorney.a@example.test"))
        self.assertIn("no-store", self.client.get(reverse("cases:index")).headers["Cache-Control"])


class DemoCommandTests(SeededTestCase):
    def test_seed_rerun_preserves_records_even_when_contact_email_is_shared(self):
        models = [User, Client, Case, Document, Task, Deadline, AuditEvent]
        self.assertEqual([model.objects.count() for model in models], [5, 5, 2, 2, 4, 4, 1])
        original = Client.objects.get(email="client.alpha@example.test")
        duplicate = Client.objects.create(
            name="Fictional Duplicate",
            type=Client.Type.INDIVIDUAL,
            email=original.email,
            created_by=original.created_by,
        )
        before = [model.objects.count() for model in models]
        hashes = list(User.objects.order_by("pk").values_list("password", flat=True))
        dates = list(Task.objects.order_by("pk").values_list("due_at", flat=True))
        with patch.dict(os.environ, {"LEXFLOW_DEMO_PASSWORD": "Another-valid-passphrase-81!"}):
            call_command("seed_demo", stdout=StringIO())
        self.assertEqual([model.objects.count() for model in models], before)
        self.assertEqual(
            list(User.objects.order_by("pk").values_list("password", flat=True)), hashes
        )
        self.assertEqual(list(Task.objects.order_by("pk").values_list("due_at", flat=True)), dates)
        self.assertTrue(original.case_links.exists())
        self.assertFalse(duplicate.case_links.exists())

    def test_private_files_have_no_url_or_public_route(self):
        for doc in Document.objects.all():
            with self.assertRaises(ValueError):
                _ = doc.file.url
            with doc.file.open("rb") as file:
                self.assertIn(b"Fictional", file.read())
            self.assertEqual(self.client.get(f"/media/{doc.file.name}").status_code, 404)

    @override_settings(ALLOW_DEMO_DATA=False)
    def test_deployment_cannot_seed(self):
        with self.assertRaisesMessage(CommandError, "disabled"):
            call_command("seed_demo")

    def test_missing_password_creates_no_records(self):
        with patch.dict(os.environ, {"LEXFLOW_DEMO_PASSWORD": ""}):
            with self.assertRaises(CommandError):
                call_command("seed_demo")
        self.assertEqual(User.objects.count(), 5)


class SettingsTests(SimpleTestCase):
    def run_settings(self, module, **overrides):
        env = {**os.environ, "DJANGO_SETTINGS_MODULE": module, **overrides}
        return subprocess.run(
            [sys.executable, "-c", "import django; django.setup()"],
            env=env,
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def test_missing_required_secret_fails_without_echoing_secrets(self):
        result = self.run_settings("config.settings.development", DJANGO_SECRET_KEY="")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Set the DJANGO_SECRET_KEY environment variable", result.stderr)

    def test_deployment_rejects_weak_key_and_wildcard_hosts(self):
        result = self.run_settings("config.settings.deployment", DJANGO_SECRET_KEY="short")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("strong, unique", result.stderr)
        result = self.run_settings(
            "config.settings.deployment",
            DJANGO_SECRET_KEY="test-key-" * 10,
            DJANGO_ALLOWED_HOSTS="*",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("explicit DJANGO_ALLOWED_HOSTS", result.stderr)

    def test_test_storage_is_separate_and_database_is_postgresql(self):
        self.assertEqual(settings.DATABASES["default"]["ENGINE"], "django.db.backends.postgresql")
        self.assertNotEqual(settings.PRIVATE_MEDIA_ROOT, settings.BASE_DIR / "private-media")

    def test_configured_deployment_passes_django_security_checks(self):
        env = {
            **os.environ,
            "DJANGO_SECRET_KEY": "configuration-test-only-key-" * 4,
            "DJANGO_ALLOWED_HOSTS": "lexflow.example.test",
            "DJANGO_CSRF_TRUSTED_ORIGINS": "https://lexflow.example.test",
            "DJANGO_PRIVATE_MEDIA_ROOT": str(settings.PRIVATE_MEDIA_ROOT),
            "DJANGO_CLAMDSCAN_PATH": "/usr/bin/clamdscan",
        }
        result = subprocess.run(
            [
                sys.executable,
                "manage.py",
                "check",
                "--deploy",
                "--settings=config.settings.deployment",
                "--fail-level=WARNING",
            ],
            env=env,
            cwd=settings.BASE_DIR,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class DemoRollbackTests(TestCase):
    def test_database_failure_rolls_back_records_and_new_private_files(self):
        files_before = {p for p in settings.PRIVATE_MEDIA_ROOT.rglob("*") if p.is_file()}
        with (
            patch.dict(os.environ, {"LEXFLOW_DEMO_PASSWORD": DEMO_PASSWORD}),
            patch(
                "audit.models.AuditEvent.objects.get_or_create",
                side_effect=RuntimeError("DB failure"),
            ),
            self.assertRaisesMessage(RuntimeError, "DB failure"),
        ):
            call_command("seed_demo", stdout=StringIO())
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Document.objects.count(), 0)
        self.assertEqual(
            files_before, {p for p in settings.PRIVATE_MEDIA_ROOT.rglob("*") if p.is_file()}
        )
