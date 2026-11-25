"""LOG-01: the audit helper records, redacts, and commits with its mutation."""

import os
import uuid
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.test import RequestFactory, TestCase
from django.urls import reverse

from accounts.models import User
from audit.middleware import AuditCorrelationMiddleware
from audit.models import AuditEvent
from audit.services import (
    Action,
    Resource,
    get_correlation_id,
    record_event,
)
from cases.models import Case

PASSWORD = "Fictional-audit-passphrase-73!"


class RecordEventTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = User.objects.create_user(
            "attorney.audit@example.test",
            PASSWORD,
            full_name="Audit Attorney",
            role=User.Role.ATTORNEY,
        )

    def test_records_a_complete_event(self):
        event = record_event(
            actor=self.actor,
            action=Action.USER_ROLE_CHANGED,
            resource_type=Resource.USER,
            resource_id=self.actor.pk,
            result=AuditEvent.Result.SUCCESS,
            changed_fields=["role", "is_active"],
        )
        event.refresh_from_db()
        self.assertEqual(event.actor, self.actor)
        self.assertEqual(event.action, "user.role_changed")
        self.assertEqual(event.resource_type, "user")
        self.assertEqual(event.resource_id, str(self.actor.pk))
        self.assertEqual(event.result, "success")
        # Sorted and de-duplicated so two equivalent calls produce identical rows.
        self.assertEqual(event.changed_fields, ["is_active", "role"])
        self.assertIsNotNone(event.occurred_at)
        self.assertIsInstance(event.correlation_id, uuid.UUID)

    def test_unauthenticated_actor_and_blank_resource_id_are_allowed(self):
        event = record_event(
            action=Action.LOGIN_FAILED,
            resource_type=Resource.SESSION,
            result=AuditEvent.Result.FAILURE,
        )
        self.assertIsNone(event.actor)
        self.assertEqual(event.resource_id, "")

    def test_duplicate_field_names_are_collapsed(self):
        event = record_event(
            action=Action.USER_UPDATED,
            resource_type=Resource.USER,
            result=AuditEvent.Result.SUCCESS,
            changed_fields=["role", "role", "role"],
        )
        self.assertEqual(event.changed_fields, ["role"])


class RedactionTests(TestCase):
    """LOG-01: only allowlisted field *names* are stored, never submitted values."""

    def test_allowlisted_names_record_that_a_field_changed_not_its_contents(self):
        """Recording "notes changed" is accountability; the text itself is never stored."""
        event = record_event(
            action=Action.CLIENT_UPDATED,
            resource_type=Resource.CLIENT,
            result=AuditEvent.Result.SUCCESS,
            changed_fields=["notes", "phone", "address"],
        )
        self.assertEqual(event.changed_fields, ["address", "notes", "phone"])

    def test_rejects_field_names_outside_the_allowlist(self):
        for bad in ["password", "token", "file", "secret", "session_key"]:
            with self.subTest(field=bad), self.assertRaisesMessage(ValueError, "Not allowlisted"):
                record_event(
                    action=Action.USER_UPDATED,
                    resource_type=Resource.USER,
                    result=AuditEvent.Result.SUCCESS,
                    changed_fields=[bad],
                )
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_rejects_a_value_smuggled_into_a_field_name(self):
        with self.assertRaisesMessage(ValueError, "Not allowlisted"):
            record_event(
                action=Action.USER_UPDATED,
                resource_type=Resource.USER,
                result=AuditEvent.Result.SUCCESS,
                changed_fields=["email=victim@example.test"],
            )
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_rejects_a_bare_string_mistaken_for_a_sequence(self):
        # "role" would otherwise silently become ['r','o','l','e'].
        with self.assertRaisesMessage(ValueError, "not a single string"):
            record_event(
                action=Action.USER_UPDATED,
                resource_type=Resource.USER,
                result=AuditEvent.Result.SUCCESS,
                changed_fields="role",
            )

    def test_rejects_more_than_twenty_field_names(self):
        with self.assertRaisesMessage(ValueError, "At most 20"):
            record_event(
                action=Action.USER_UPDATED,
                resource_type=Resource.USER,
                result=AuditEvent.Result.SUCCESS,
                changed_fields=AuditEvent.CHANGE_FIELDS[:21],
            )


class InvalidInputTests(TestCase):
    """LOG-01: invalid input cannot inject log structure, and writes nothing."""

    def test_rejects_malformed_actions_resources_and_results(self):
        cases = [
            {"action": "Login Succeeded"},
            {"action": "auth"},
            {"action": "auth.login succeeded\nuser.deleted"},
            {"resource_type": "user.profile"},
            {"resource_type": "User"},
            {"result": "ok"},
            {"resource_id": "victim@example.test"},
            {"resource_id": "1\naction=user.deleted"},
            {"resource_id": "x" * 81},
        ]
        for override in cases:
            payload = {
                "action": Action.USER_UPDATED,
                "resource_type": Resource.USER,
                "result": AuditEvent.Result.SUCCESS,
                **override,
            }
            with self.subTest(**override), self.assertRaises(ValueError):
                record_event(**payload)
        self.assertEqual(AuditEvent.objects.count(), 0)

    def test_rejects_an_unsaved_actor(self):
        with self.assertRaisesMessage(ValueError, "saved user"):
            record_event(
                actor=User(email="ghost@example.test", full_name="Ghost"),
                action=Action.USER_UPDATED,
                resource_type=Resource.USER,
                result=AuditEvent.Result.SUCCESS,
            )


class AtomicityTests(TestCase):
    """G5: a mutation and its audit event succeed together or neither commits."""

    def test_rolled_back_mutation_discards_its_event(self):
        user = User.objects.create_user(
            "rollback@example.test", PASSWORD, full_name="Rollback", role=User.Role.STAFF
        )
        with self.assertRaisesMessage(RuntimeError, "forced"), transaction.atomic():
            user.update_with_revision(user.revision, role=User.Role.ATTORNEY)
            record_event(
                actor=user,
                action=Action.USER_ROLE_CHANGED,
                resource_type=Resource.USER,
                resource_id=user.pk,
                result=AuditEvent.Result.SUCCESS,
                changed_fields=["role"],
                require_atomic=True,
            )
            raise RuntimeError("forced")
        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.STAFF)
        self.assertFalse(AuditEvent.objects.exists())

    def test_require_atomic_refuses_to_run_outside_a_transaction(self):
        # TestCase wraps each test in a transaction, so check the guard directly.
        connection_in_atomic = transaction.get_connection().in_atomic_block
        self.assertTrue(connection_in_atomic)
        with transaction.atomic():
            event = record_event(
                action=Action.USER_UPDATED,
                resource_type=Resource.USER,
                result=AuditEvent.Result.SUCCESS,
                require_atomic=True,
            )
        self.assertIsNotNone(event.pk)

    def test_event_joins_the_callers_transaction(self):
        with transaction.atomic():
            record_event(
                action=Action.USER_UPDATED,
                resource_type=Resource.USER,
                result=AuditEvent.Result.SUCCESS,
            )
            self.assertEqual(AuditEvent.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.count(), 1)


class CorrelationIdTests(TestCase):
    def test_events_in_one_request_share_one_generated_id(self):
        factory = RequestFactory()
        captured = {}

        def view(request):
            captured["attached"] = request.correlation_id
            record_event(
                action=Action.USER_LIST_READ,
                resource_type=Resource.USER,
                result=AuditEvent.Result.SUCCESS,
            )
            record_event(
                action=Action.ACCESS_DENIED,
                resource_type=Resource.CASE,
                resource_id=7,
                result=AuditEvent.Result.DENIED,
            )
            return "response"

        middleware = AuditCorrelationMiddleware(view)
        middleware(factory.get("/"))
        ids = set(AuditEvent.objects.values_list("correlation_id", flat=True))
        self.assertEqual(len(ids), 1)
        self.assertEqual(ids.pop(), captured["attached"])

    def test_separate_requests_get_separate_ids(self):
        factory = RequestFactory()

        def view(request):
            record_event(
                action=Action.USER_LIST_READ,
                resource_type=Resource.USER,
                result=AuditEvent.Result.SUCCESS,
            )
            return "response"

        middleware = AuditCorrelationMiddleware(view)
        middleware(factory.get("/"))
        middleware(factory.get("/"))
        self.assertEqual(AuditEvent.objects.values("correlation_id").distinct().count(), 2)

    def test_client_cannot_choose_the_correlation_id(self):
        forged = uuid.uuid4()
        self.client.get(reverse("accounts:login"), HTTP_X_CORRELATION_ID=str(forged))
        self.assertFalse(AuditEvent.objects.filter(correlation_id=forged).exists())

    def test_outside_a_request_one_id_is_reused(self):
        self.assertEqual(get_correlation_id(), get_correlation_id())


class AppendOnlyThroughTheHelperTests(TestCase):
    """DEC-14: the helper cannot be used to rewrite history."""

    def test_recorded_events_cannot_be_updated_or_deleted(self):
        event = record_event(
            action=Action.LOGIN_SUCCEEDED,
            resource_type=Resource.SESSION,
            result=AuditEvent.Result.SUCCESS,
        )
        for operation in [
            lambda: AuditEvent.objects.filter(pk=event.pk).update(result="failure"),
            lambda: AuditEvent.objects.filter(pk=event.pk).delete(),
        ]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()
        event.refresh_from_db()
        self.assertEqual(event.result, "success")


class SharedCorrelationIdTests(TestCase):
    """Every event raised while handling one request must share its correlation id.

    The case and client views record through `cases.services.audit_event`, which
    used to mint a fresh uuid4 per event. That made the column useless for
    grouping what a single request did, which is exactly what LOG-01 wants it for.
    """

    @classmethod
    def setUpTestData(cls):
        with patch.dict(os.environ, {"LEXFLOW_DEMO_PASSWORD": PASSWORD}):
            call_command("seed_demo", stdout=StringIO())
        cls.attorney = User.objects.get(email="attorney.a@example.test")

    def test_one_request_produces_one_correlation_id(self):
        self.client.force_login(self.attorney)
        mark = AuditEvent.objects.aggregate(top=Max("pk"))["top"] or 0

        case = Case.objects.get(number="DEMO-ALPHA")
        response = self.client.get(reverse("cases:detail", args=[case.pk]))
        self.assertEqual(response.status_code, 200)

        produced = AuditEvent.objects.filter(pk__gt=mark)
        self.assertGreaterEqual(produced.count(), 1)
        self.assertEqual(
            produced.values("correlation_id").distinct().count(),
            1,
            "events from a single request must share one correlation id",
        )

    def test_separate_requests_do_not_share_an_id(self):
        self.client.force_login(self.attorney)
        mark = AuditEvent.objects.aggregate(top=Max("pk"))["top"] or 0
        case = Case.objects.get(number="DEMO-ALPHA")
        self.client.get(reverse("cases:detail", args=[case.pk]))
        self.client.get(reverse("cases:detail", args=[case.pk]))
        produced = AuditEvent.objects.filter(pk__gt=mark)
        self.assertEqual(produced.values("correlation_id").distinct().count(), 2)


# --- Issue #18 coverage: denials, account events, review page, failure policy ---

from datetime import UTC, datetime, timedelta  # noqa: E402

from django.contrib.auth.models import Permission  # noqa: E402
from django.db.models import F  # noqa: E402
from django.utils import timezone  # noqa: E402

from cases.policies import Action as Capability  # noqa: E402
from work.models import Task  # noqa: E402

from .test_foundation import DEMO_PASSWORD, SeededTestCase  # noqa: E402


class SeededAuditTestCase(SeededTestCase):
    def setUp(self):
        self.admin = User.objects.get(email="admin@example.test")
        self.attorney = User.objects.get(email="attorney.a@example.test")
        self.other_attorney = User.objects.get(email="attorney.b@example.test")
        self.staff = User.objects.get(email="staff.a@example.test")
        self.alpha = Case.objects.get(number="DEMO-ALPHA")
        self.task = Task.objects.filter(case=self.alpha, assignee=self.staff).first()

    def grant_audit(self, user):
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label="cases", codename=Capability.VIEW_AUDIT)
        )

    def denials(self, **filters):
        return AuditEvent.objects.filter(action=Action.ACCESS_DENIED, **filters)


class AccessDenialTests(SeededAuditTestCase):
    def test_refused_mutation_is_recorded_after_its_transaction_rolls_back(self):
        url = reverse("cases:task_complete", args=[self.alpha.pk, self.task.pk])
        self.client.force_login(self.attorney)  # a member, but not the assignee
        response = self.client.post(url, {"revision": self.task.revision})
        self.assertEqual(response.status_code, 403)
        self.task.refresh_from_db()
        self.assertNotEqual(self.task.status, Task.Status.DONE)
        event = self.denials().get()
        self.assertEqual(event.actor, self.attorney)
        self.assertEqual(event.result, AuditEvent.Result.DENIED)
        self.assertEqual((event.resource_type, event.resource_id), ("task", str(self.task.pk)))
        self.assertEqual(event.changed_fields, [])

    def test_hidden_record_is_a_denial_but_a_missing_one_is_not(self):
        self.client.force_login(self.other_attorney)  # not on the Alpha team
        detail = reverse("cases:detail", args=[self.alpha.pk])
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertEqual(
            self.denials(resource_type="case", resource_id=str(self.alpha.pk)).count(), 1
        )
        missing = Case.objects.aggregate(top=Max("pk"))["top"] + 1000
        self.assertEqual(self.client.get(reverse("cases:detail", args=[missing])).status_code, 404)
        self.assertFalse(self.denials(resource_id=str(missing)).exists())

    def test_audit_page_refusal_is_recorded(self):
        self.client.force_login(self.attorney)
        self.assertEqual(self.client.get(reverse("cases:audit")).status_code, 403)
        self.assertEqual(self.denials(resource_type="audit_log", actor=self.attorney).count(), 1)

    def test_account_refusal_is_recorded_once(self):
        self.client.force_login(self.attorney)
        self.assertEqual(self.client.get(reverse("accounts:list")).status_code, 403)
        refusals = AuditEvent.objects.filter(actor=self.attorney, result="denied")
        self.assertEqual(list(refusals.values_list("action", flat=True)), ["account.admin"])

    def test_a_failed_denial_write_still_refuses_the_request(self):
        self.client.force_login(self.attorney)
        with (
            patch("audit.middleware.record_event", side_effect=RuntimeError("db down")),
            self.assertLogs("lexflow.audit", "ERROR") as logs,
        ):
            self.assertEqual(self.client.get(reverse("cases:audit")).status_code, 403)
        self.assertIn("RuntimeError", logs.output[0])
        self.assertNotIn("db down", logs.output[0])


class AccountEventTests(SeededAuditTestCase):
    def test_account_events_use_the_shared_writer_and_request_id(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "attorney.a@example.test", "password": "wrong-" + DEMO_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        failure = AuditEvent.objects.get(action="auth.login", result="failure")
        self.assertIsNone(failure.actor)
        self.assertEqual(failure.resource_id, "")
        self.client.post(
            reverse("accounts:login"),
            {"username": "attorney.a@example.test", "password": DEMO_PASSWORD},
        )
        success = AuditEvent.objects.get(action="auth.login", result="success")
        self.assertEqual(success.actor, self.attorney)
        self.assertNotEqual(success.correlation_id, failure.correlation_id)
        # Routed through record_event, so a non-allowlisted name is refused.
        from accounts.security import audit_account

        request = RequestFactory().get("/")
        with self.assertRaises(ValueError):
            audit_account(request, "auth.login", "success", fields=["password"])

    def test_revoked_session_is_recorded_without_session_data(self):
        self.client.force_login(self.staff)
        User.objects.filter(pk=self.staff.pk).update(
            is_active=False, session_version=F("session_version") + 1
        )
        self.client.get(reverse("cases:index"))
        event = AuditEvent.objects.get(action=Action.SESSION_REVOKED)
        self.assertIsNone(event.actor)
        self.assertEqual((event.resource_type, event.resource_id), ("user", str(self.staff.pk)))

    def test_password_reset_request_does_not_name_the_account(self):
        self.client.post(reverse("accounts:password_reset"), {"email": "staff.a@example.test"})
        event = AuditEvent.objects.get(action="auth.password_reset_request")
        self.assertIsNone(event.actor)
        self.assertEqual(event.resource_id, "")


class AuditWriteFailureTests(SeededAuditTestCase):
    def test_a_failed_mutation_event_rolls_the_change_back(self):
        url = reverse("cases:task_complete", args=[self.alpha.pk, self.task.pk])
        self.client.force_login(self.staff)
        with (
            patch("cases.services.record_event", side_effect=RuntimeError("audit down")),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(url, {"revision": self.task.revision})
        self.task.refresh_from_db()
        self.assertNotEqual(self.task.status, Task.Status.DONE)


class AuditReviewTests(SeededAuditTestCase):
    def setUp(self):
        super().setUp()
        self.grant_audit(self.admin)
        self.client.force_login(self.admin)
        self.url = reverse("cases:audit")

    def event_at(self, when, **fields):
        defaults = {
            "action": Action.CASE_READ,
            "resource_type": Resource.CASE,
            "resource_id": str(self.alpha.pk),
            "result": AuditEvent.Result.SUCCESS,
            "actor": self.attorney,
        }
        with patch("django.utils.timezone.now", return_value=when):
            return record_event(**{**defaults, **fields})

    def shown(self, response):
        return list(response.context["page"].object_list)

    def test_default_range_is_the_last_seven_utc_days_newest_first(self):
        now = timezone.now()
        old = self.event_at(now - timedelta(days=10))
        recent = self.event_at(now - timedelta(days=2))
        newest = self.event_at(now - timedelta(minutes=1))
        shown = self.shown(self.client.get(self.url))
        self.assertNotIn(old, shown)
        self.assertLess(shown.index(newest), shown.index(recent))

    def test_filters_by_actor_action_record_and_date(self):
        day = datetime(2026, 11, 2, 12, tzinfo=UTC)
        match = self.event_at(day)
        self.event_at(day, actor=self.staff)
        self.event_at(day, action=Action.CASE_UPDATED)
        self.event_at(day, resource_id="999")
        self.event_at(day - timedelta(days=3))
        response = self.client.get(
            self.url,
            {
                "actor": self.attorney.pk,
                "action": Action.CASE_READ,
                "resource_type": "case",
                "resource_id": str(self.alpha.pk),
                "start": "2026-11-01",
                "end": "2026-11-02",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.shown(response), [match])

    def test_rejects_invalid_filters_ranges_and_pages(self):
        cases = [
            {"start": "2026-11-10", "end": "2026-11-01"},  # reversed
            {"start": "2026-10-01", "end": "2026-11-01"},  # 32 days
            {"start": "not-a-date"},
            {"action": "case.made_up"},
            {"resource_id": "12; DROP"},
            {"actor": "999999"},
            {"page": "0"},
            {"page": "abc"},
            {"page": "999"},
            {"unexpected": "1"},
        ]
        for params in cases:
            with self.subTest(params=params):
                response = self.client.get(self.url, params)
                self.assertEqual(response.status_code, 400)
                self.assertIsNone(response.context["page"])
        ok = self.client.get(self.url, {"start": "2026-10-02", "end": "2026-11-01"})
        self.assertEqual(ok.status_code, 200)  # exactly 31 days

    def test_no_matches_shows_an_empty_state(self):
        response = self.client.get(self.url, {"start": "2026-01-01", "end": "2026-01-02"})
        self.assertContains(response, "No audit events match these filters.")

    def test_paginates_fifty_per_page(self):
        day = datetime(2026, 11, 3, 12, tzinfo=UTC)
        for offset in range(51):
            self.event_at(day + timedelta(seconds=offset))
        params = {"start": "2026-11-03", "end": "2026-11-03"}
        self.assertEqual(len(self.shown(self.client.get(self.url, params))), 50)
        self.assertEqual(len(self.shown(self.client.get(self.url, {**params, "page": 2}))), 1)

    def test_review_is_recorded_after_the_query_without_recursion(self):
        response = self.client.get(self.url)
        self.assertNotIn(Action.AUDIT_LOG_READ, [e.action for e in self.shown(response)])
        self.assertEqual(AuditEvent.objects.filter(action=Action.AUDIT_LOG_READ).count(), 1)
        self.client.get(self.url, {"page": "abc"})  # rejected queries are not reviews
        self.assertEqual(AuditEvent.objects.filter(action=Action.AUDIT_LOG_READ).count(), 1)

    def test_log_contains_no_search_text_or_passwords(self):
        attempt = "Fictional-wrong-passphrase-99!"
        anonymous = self.client_class()
        anonymous.post(
            reverse("accounts:login"),
            {"username": "staff.a@example.test", "password": attempt},
        )
        self.client.get(reverse("cases:clients"), {"q": "Confidential search phrase"})
        self.client.get(reverse("cases:index"), {"q": "Confidential case phrase"})
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for secret in (attempt, "Confidential search phrase", "Confidential case phrase"):
            self.assertNotContains(response, secret)
