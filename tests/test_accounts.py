import logging
import re
from datetime import datetime, timedelta
from unittest.mock import patch
from urllib.parse import urlsplit

from django.conf import settings
from django.core import mail
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.middleware import SESSION_STARTED_AT
from accounts.models import LoginThrottle, User
from accounts.security import reset_tokens
from audit.models import AuditEvent
from config.logging import RedactRecoveryURL

PASSWORD = "Fictional-starting-passphrase-73!"
NEW_PASSWORD = "Different-private-passphrase-27!"


class AccountWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            "admin@example.test", PASSWORD, full_name="Administrator"
        )
        cls.staff = User.objects.create_user("staff@example.test", PASSWORD, full_name="Staff")

    def sign_in(self, client, *, email=None, password=PASSWORD):
        return client.post(
            reverse("accounts:login"), {"username": email or self.staff.email, "password": password}
        )

    def change_access(self, user, *, role=None, state="active", revision=None):
        return self.client.post(
            reverse("accounts:access", args=[user.pk]),
            {
                "role": role or user.role,
                "is_active": state,
                "revision": revision or user.revision,
            },
        )

    def request_reset(self, email):
        return self.client.post(reverse("accounts:password_reset"), {"email": email})

    def recovery_link(self):
        return urlsplit(re.search(r"https?://\S+", mail.outbox[-1].body)[0]).path

    def test_throttles_normalized_identity_and_resets_after_window_and_success(self):
        for _ in range(5):
            self.assertEqual(self.sign_in(self.client, password="wrong").status_code, 200)
        self.assertEqual(self.sign_in(self.client, email=self.staff.email.upper()).status_code, 429)
        self.assertEqual(self.sign_in(self.client, email=self.admin.email).status_code, 302)
        self.assertEqual(LoginThrottle.objects.count(), 1)
        with patch(
            "accounts.services.timezone.now", return_value=timezone.now() + timedelta(minutes=15)
        ):
            self.assertEqual(self.sign_in(self.client, password="wrong").status_code, 200)
            self.assertEqual(LoginThrottle.objects.get().failures, 1)
            self.assertEqual(self.sign_in(self.client).status_code, 302)
        self.assertFalse(LoginThrottle.objects.exists())
        self.assertEqual(AuditEvent.objects.filter(action="auth.login", result="denied").count(), 1)
        self.assertEqual(
            AuditEvent.objects.filter(action="auth.login", result="failure").count(), 6
        )

    def test_unknown_and_inactive_with_correct_password_share_generic_login_error(self):
        User.objects.filter(pk=self.staff.pk).update(is_active=False)
        unknown = self.sign_in(self.client, email="unknown@example.test")
        inactive = self.sign_in(self.client)
        wrong = self.sign_in(self.client, email=self.admin.email, password="wrong")
        for response in (inactive, wrong):
            self.assertEqual(
                list(response.context["form"].non_field_errors()),
                list(unknown.context["form"].non_field_errors()),
            )

    def test_account_creation_is_restricted_and_validates_passwords_and_email(self):
        url = reverse("accounts:create")
        data = {
            "email": "Colleague@Example.test",
            "full_name": "Colleague",
            "role": "Attorney",
            "password1": PASSWORD,
            "password2": PASSWORD,
        }
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("accounts:list")).status_code, 403)
        self.assertEqual(self.client.post(url, data).status_code, 403)
        self.assertEqual(self.change_access(self.staff, role="Administrator").status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.post(url, {**data, "password1": "short", "password2": "short"}).status_code,
            400,
        )
        self.assertEqual(self.client.post(url, {**data, "role": "invalid"}).status_code, 400)
        self.assertRedirects(self.client.post(url, data), reverse("accounts:list"))
        target = User.objects.get(email="colleague@example.test")
        self.assertTrue(target.is_active)
        self.assertTrue(target.check_password(PASSWORD))
        self.assertEqual(self.client.post(url, data).status_code, 400)
        event = AuditEvent.objects.get(action="account.create", result="success")
        self.assertEqual(event.actor_id, self.admin.pk)
        self.assertEqual(event.resource_id, str(target.pk))
        self.assertEqual(set(event.changed_fields), {"name", "email", "role", "is_active"})

    def test_role_changes_take_effect_in_existing_sessions_and_reject_stale_edits(self):
        other_session = Client()
        self.sign_in(other_session)
        self.client.force_login(self.admin)
        list_url = reverse("accounts:list")
        self.assertEqual(other_session.get(list_url).status_code, 403)
        self.assertRedirects(self.change_access(self.staff, role="Administrator"), list_url)
        self.assertEqual(other_session.get(list_url).status_code, 200)
        self.assertEqual(self.change_access(self.staff, role="Attorney").status_code, 409)
        self.staff.refresh_from_db()
        self.assertRedirects(self.change_access(self.staff, role="Staff"), list_url)
        self.assertEqual(other_session.get(list_url).status_code, 403)
        self.assertEqual(
            AuditEvent.objects.filter(action="account.role_change", result="success").count(), 2
        )

    def test_last_administrator_cannot_be_deactivated_or_demoted(self):
        self.client.force_login(self.admin)
        for role, state in [("Administrator", "inactive"), ("Staff", "active")]:
            self.assertContains(
                self.change_access(self.admin, role=role, state=state),
                "Keep at least one active administrator",
                status_code=409,
            )
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_administrator)

    def test_deactivation_revokes_existing_sessions_even_if_account_is_reactivated(self):
        first, second = Client(), Client()
        self.sign_in(first)
        self.sign_in(second)
        self.client.force_login(self.admin)
        list_url = reverse("accounts:list")
        cases = reverse("cases:index")
        self.assertRedirects(self.change_access(self.staff, state="inactive"), list_url)
        self.assertEqual(first.get(cases).status_code, 302)
        self.assertEqual(self.sign_in(first).status_code, 200)
        self.staff.refresh_from_db()
        self.assertRedirects(self.change_access(self.staff), list_url)
        self.assertEqual(second.get(cases).status_code, 302)
        self.assertEqual(self.sign_in(second).status_code, 302)
        self.assertTrue(
            AuditEvent.objects.filter(action="account.deactivate", result="success").exists()
        )

    def test_session_has_sliding_idle_timeout_and_absolute_limit(self):
        cases = reverse("cases:index")
        self.sign_in(self.client)
        start = self.client.session[SESSION_STARTED_AT]
        with patch(
            "accounts.middleware.now",
            return_value=datetime.fromtimestamp(
                start + 29 * 60, tz=timezone.get_current_timezone()
            ),
        ):
            self.assertEqual(self.client.get(cases).status_code, 200)
        with patch(
            "accounts.middleware.now",
            return_value=datetime.fromtimestamp(
                start + 59 * 60, tz=timezone.get_current_timezone()
            ),
        ):
            self.assertEqual(self.client.get(cases).status_code, 302)
        self.sign_in(self.client)
        session = self.client.session
        session[SESSION_STARTED_AT] -= settings.SESSION_ABSOLUTE_AGE
        session.save()
        self.assertEqual(self.client.get(cases).status_code, 302)
        self.assertEqual(AuditEvent.objects.filter(action="auth.session_expired").count(), 2)

    def test_password_change_requires_current_password_and_revokes_other_sessions(self):
        other_session = Client()
        self.sign_in(other_session)
        self.sign_in(self.client)
        url = reverse("accounts:password_change")
        data = {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD}
        self.assertContains(self.client.post(url, {**data, "old_password": "wrong"}), "incorrect")
        self.assertRedirects(self.client.post(url, {**data, "old_password": PASSWORD}), url)
        cases = reverse("cases:index")
        self.assertEqual(self.client.get(cases).status_code, 200)
        self.assertEqual(other_session.get(cases).status_code, 302)
        self.assertEqual(self.sign_in(other_session, password=NEW_PASSWORD).status_code, 302)

    def test_recovery_is_generic_expires_and_is_single_use_across_sessions(self):
        sent = reverse("accounts:password_reset_done")
        for email in ("unknown@example.test", self.staff.email.upper()):
            self.assertRedirects(self.request_reset(email), sent)
        self.assertEqual(len(mail.outbox), 1)
        link = self.recovery_link()
        with patch.object(
            reset_tokens,
            "_now",
            return_value=reset_tokens._now()
            + timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT + 1),
        ):
            self.assertContains(self.client.get(link), "Reset link unavailable")
        second = Client()
        confirm = self.client.get(link)
        self.assertEqual(confirm.headers["Referrer-Policy"], "no-referrer")
        self.assertEqual(second.get(link).url, confirm.url)
        data = {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD}
        self.assertRedirects(
            self.client.post(confirm.url, data), reverse("accounts:password_reset_complete")
        )
        self.assertContains(second.post(confirm.url, data), "Reset link unavailable")
        self.assertContains(self.client.get(link), "Reset link unavailable")
        self.assertEqual(self.sign_in(self.client, password=NEW_PASSWORD).status_code, 302)
        self.assertEqual(AuditEvent.objects.filter(action="auth.password_reset").count(), 1)

    def test_deactivation_invalidates_prior_recovery_links(self):
        self.request_reset(self.staff.email)
        link = self.recovery_link()
        self.client.force_login(self.admin)
        self.change_access(self.staff, state="inactive")
        self.staff.refresh_from_db()
        self.client.logout()
        self.request_reset(self.staff.email)
        self.assertEqual(len(mail.outbox), 1)
        self.client.force_login(self.admin)
        self.change_access(self.staff)
        self.client.logout()
        self.assertContains(self.client.get(link), "Reset link unavailable")

    def test_account_and_password_forms_require_csrf(self):
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(self.admin)
        for name in ("create", "password_change", "password_reset", "logout"):
            self.assertEqual(browser.post(reverse(f"accounts:{name}")).status_code, 403)
        self.assertEqual(
            browser.post(reverse("accounts:access", args=[self.staff.pk])).status_code, 403
        )
        self.request_reset(self.staff.email)
        confirm = browser.get(self.recovery_link()).url
        self.assertEqual(browser.post(confirm).status_code, 403)

    def test_request_logging_redacts_recovery_tokens(self):
        self.request_reset(self.staff.email)
        link = self.recovery_link()
        for path in (link, link.rstrip("/")):
            record = logging.LogRecord(
                "django.server", logging.INFO, "", 0, "%s", (f"GET {path}",), None
            )
            RedactRecoveryURL().filter(record)
            self.assertNotIn(path, record.getMessage())
            self.assertIn("[redacted]", record.getMessage())
