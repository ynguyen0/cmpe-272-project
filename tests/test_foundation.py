import os
import subprocess
import sys
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from audit.models import AuditEvent
from cases.models import Case, CaseMembership
from cases.policies import cases_visible_to, clients_visible_to
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


class PermissionTests(SeededTestCase):
    def setUp(self):
        self.a = User.objects.get(email="attorney.a@example.test")
        self.b = User.objects.get(email="attorney.b@example.test")
        self.staff = User.objects.get(email="staff.a@example.test")
        self.alpha = Case.objects.get(number="DEMO-ALPHA")
        self.beta = Case.objects.get(number="DEMO-BETA")

    def test_roles_and_membership_scope_case_reads(self):
        for email, expected in [
            ("admin@example.test", {self.alpha.pk, self.beta.pk}),
            ("attorney.a@example.test", {self.alpha.pk}),
            ("attorney.b@example.test", {self.beta.pk}),
            ("staff.a@example.test", {self.alpha.pk}),
            ("inactive@example.test", set()),
        ]:
            with self.subTest(email=email):
                user = User.objects.get(email=email)
                self.assertSetEqual(
                    set(cases_visible_to(user).values_list("pk", flat=True)), expected
                )
        self.assertFalse(cases_visible_to(AnonymousUser()).exists())

    def test_client_scope_shared_and_unlinked(self):
        visible = set(clients_visible_to(self.a).values_list("email", flat=True))
        self.assertSetEqual(
            visible,
            {
                "client.alpha@example.test",
                "client.shared@example.test",
                "client.unlinked.a@example.test",
            },
        )
        self.assertFalse(clients_visible_to(AnonymousUser()).exists())

    def test_direct_url_and_list_do_not_leak_other_cases(self):
        self.client.force_login(self.a)
        response = self.client.get(reverse("cases:index"))
        self.assertContains(response, self.alpha.title)
        self.assertNotContains(response, self.beta.title)
        self.assertEqual(
            self.client.get(reverse("cases:detail", args=[self.beta.pk])).status_code, 404
        )
        self.assertEqual(self.client.get(reverse("cases:detail", args=[999999])).status_code, 404)

    def test_removal_and_deactivation_apply_to_existing_sessions(self):
        self.client.force_login(self.staff)
        url = reverse("cases:detail", args=[self.alpha.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        membership = CaseMembership.objects.get(case=self.alpha, user=self.staff)
        membership.update_with_revision(membership.revision, is_active=False)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.staff.is_active = False
        self.staff.save()
        self.assertRedirects(
            self.client.get(url), f"/accounts/login/?next={url}", fetch_redirect_response=False
        )


class AuthenticationTests(SeededTestCase):
    def test_login_normalizes_email_and_logout_invalidates_session(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "ATTORNEY.A@EXAMPLE.TEST", "password": DEMO_PASSWORD},
        )
        self.assertRedirects(response, reverse("cases:index"))
        cookie = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        self.assertRedirects(
            self.client.post(reverse("accounts:logout")), reverse("accounts:login")
        )
        self.client.cookies[settings.SESSION_COOKIE_NAME] = cookie
        self.assertEqual(self.client.get(reverse("cases:index")).status_code, 302)

    def test_wrong_and_inactive_credentials_share_error(self):
        errors = []
        for email in ["unknown@example.test", "inactive@example.test", "attorney.a@example.test"]:
            response = self.client.post(
                reverse("accounts:login"), {"username": email, "password": "incorrect"}
            )
            self.assertEqual(response.status_code, 200)
            errors.append(list(response.context["form"].non_field_errors()))
        self.assertEqual(errors[0], errors[1])
        self.assertEqual(errors[1], errors[2])
        self.assertFalse(
            self.client.login(username="inactive@example.test", password=DEMO_PASSWORD)
        )

    def test_csrf_required_and_sensitive_pages_not_cached(self):
        from django.test import Client as HttpClient

        csrf_client = HttpClient(enforce_csrf_checks=True)
        self.assertEqual(csrf_client.post(reverse("accounts:login"), {}).status_code, 403)
        response = self.client.get(reverse("accounts:login"))
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.client.force_login(User.objects.get(email="attorney.a@example.test"))
        self.assertIn("no-store", self.client.get(reverse("cases:index")).headers["Cache-Control"])


class DemoCommandTests(SeededTestCase):
    def test_rerun_preserves_counts_passwords_and_dates(self):
        models = [User, Client, Case, Document, Task, Deadline, AuditEvent]
        before = [model.objects.count() for model in models]
        hashes = list(User.objects.order_by("pk").values_list("password", flat=True))
        dates = list(Task.objects.order_by("pk").values_list("due_at", flat=True))
        with patch.dict(os.environ, {"LEXFLOW_DEMO_PASSWORD": "Another-valid-passphrase-81!"}):
            call_command("seed_demo", stdout=StringIO())
        self.assertEqual(before, [model.objects.count() for model in models])
        self.assertEqual(
            hashes, list(User.objects.order_by("pk").values_list("password", flat=True))
        )
        self.assertEqual(dates, list(Task.objects.order_by("pk").values_list("due_at", flat=True)))
        self.assertEqual(before, [5, 5, 2, 2, 4, 4, 1])

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
