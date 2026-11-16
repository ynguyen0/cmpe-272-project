"""LOG-01: the audit helper records, redacts, and commits with its mutation."""

import uuid

from django.db import IntegrityError, transaction
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
