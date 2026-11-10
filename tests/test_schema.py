import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.template import Context, Template
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from cases.models import Case, CaseClient, CaseMembership
from cases.policies import cases_visible_to, clients_visible_to
from clients.models import Client
from config.models import ConcurrentEditError
from documents.models import Document
from tests.test_foundation import SeededTestCase
from work.models import Deadline, Task


class SchemaConstraintTests(SeededTestCase):
    def setUp(self):
        self.alpha = Case.objects.get(number="DEMO-ALPHA")
        self.beta = Case.objects.get(number="DEMO-BETA")
        self.a = self.alpha.responsible_attorney
        self.b = self.beta.responsible_attorney

    def assert_rejected(self, operation):
        # Explicitly check deferred FKs inside the savepoint, rather than at test teardown.
        with self.assertRaises(IntegrityError), transaction.atomic():
            operation()
            connection.check_constraints()

    def test_explicit_link_pairs_are_unique_and_required(self):
        link = CaseClient.objects.filter(case=self.alpha).first()
        self.assert_rejected(lambda: CaseClient.objects.create(case=self.alpha, client=link.client))
        self.assert_rejected(lambda: CaseMembership.objects.create(case=self.alpha, user=self.a))
        self.assert_rejected(lambda: CaseClient.objects.create(case=self.alpha, client_id=999999))
        self.assert_rejected(lambda: CaseMembership.objects.create(case=self.alpha, user_id=999999))

    def test_same_case_assignment_foreign_keys_cannot_be_bypassed(self):
        task = Task.objects.filter(case=self.alpha).first()
        deadline = Deadline.objects.filter(case=self.alpha).first()
        self.assert_rejected(lambda: Task.objects.filter(pk=task.pk).update(assignee=self.b))
        self.assert_rejected(
            lambda: Deadline.objects.filter(pk=deadline.pk).update(responsible_user=self.b)
        )
        self.assert_rejected(
            lambda: Case.objects.filter(pk=self.alpha.pk).update(responsible_attorney=self.b)
        )
        self.assert_rejected(lambda: Task.objects.filter(pk=task.pk).update(case=self.beta))

    def test_required_fields_and_nonblank_values_reject_raw_writes(self):
        for model, pk, field, value in [
            (User, self.a.pk, "full_name", "  \t\n"),
            (Client, self.alpha.clients.first().pk, "name", ""),
            (Case, self.alpha.pk, "number", " "),
            (Case, self.alpha.pk, "title", ""),
            (Case, self.alpha.pk, "responsible_attorney", None),
            (Task, Task.objects.first().pk, "due_at", None),
            (Deadline, Deadline.objects.first().pk, "responsible_user", None),
            (Document, Document.objects.first().pk, "file", ""),
        ]:
            with self.subTest(model=model.__name__, field=field):
                self.assert_rejected(
                    lambda model=model, pk=pk, field=field, value=value: model.objects.filter(
                        pk=pk
                    ).update(**{field: value})
                )

    def test_all_enum_and_revision_checks_apply_to_raw_updates(self):
        records = [
            (self.a, "role"),
            (Client.objects.first(), "type"),
            (Client.objects.first(), "status"),
            (self.alpha, "type"),
            (self.alpha, "status"),
            (CaseClient.objects.first(), "relationship"),
            (CaseMembership.objects.first(), "responsibility"),
            (Task.objects.first(), "priority"),
            (Task.objects.first(), "status"),
            (Deadline.objects.first(), "type"),
            (Deadline.objects.first(), "status"),
            (Document.objects.first(), "category"),
            (Document.objects.first(), "state"),
        ]
        for record, field in records:
            with self.subTest(model=record._meta.label, field=field):
                queryset = type(record).objects.filter(pk=record.pk)
                self.assert_rejected(
                    lambda queryset=queryset, field=field: queryset.update(**{field: "INVALID"})
                )
                self.assert_rejected(lambda queryset=queryset: queryset.update(revision=0))

    def test_case_dates_and_archive_require_closed_case(self):
        self.assert_rejected(lambda: Case.objects.filter(pk=self.alpha.pk).update(status="Closed"))
        self.assert_rejected(lambda: Case.objects.filter(pk=self.alpha.pk).update(is_archived=True))
        self.assert_rejected(
            lambda: Case.objects.filter(pk=self.alpha.pk).update(
                status="Closed", closed_on=self.alpha.opened_on.replace(year=2020)
            )
        )

    def test_completion_and_archive_metadata_are_consistent(self):
        task = Task.objects.first()
        deadline = Deadline.objects.first()
        document = Document.objects.get(state="Active")
        self.assert_rejected(lambda: Task.objects.filter(pk=task.pk).update(status="Done"))
        self.assert_rejected(
            lambda: Task.objects.filter(pk=task.pk).update(completed_at=timezone.now())
        )
        self.assert_rejected(
            lambda: Deadline.objects.filter(pk=deadline.pk).update(status="Completed")
        )
        self.assert_rejected(
            lambda: Document.objects.filter(pk=document.pk).update(state="Archived")
        )
        for size in [0, 10485761]:
            self.assert_rejected(
                lambda size=size: Document.objects.filter(pk=document.pk).update(size=size)
            )
        Document.objects.filter(pk=document.pk).update(size=10485760)
        document.refresh_from_db()
        self.assertEqual(document.size, 10485760)
        other = Document.objects.get(state="Archived")
        self.assert_rejected(
            lambda: Document.objects.filter(pk=other.pk).update(file=document.file.name)
        )

    def test_one_active_lead_and_distinct_internal_case_reference(self):
        member = CaseMembership.objects.get(case=self.alpha, user__role="Staff")
        self.assert_rejected(
            lambda: CaseMembership.objects.filter(pk=member.pk).update(
                responsibility="Lead attorney"
            )
        )
        self.assert_rejected(
            lambda: Case.objects.filter(pk=self.beta.pk).update(number=self.alpha.number)
        )
        # Court docket identifiers are optional and not globally unique across courts.
        Case.objects.filter(pk__in=[self.alpha.pk, self.beta.pk]).update(
            court_docket_number="C-123"
        )
        self.assertEqual(Case.objects.filter(court_docket_number="C-123").count(), 2)

    def test_relationships_are_protected_from_cascading_deletion(self):
        for record in [self.alpha, self.a, self.alpha.clients.first()]:
            with self.subTest(model=record._meta.label), self.assertRaises(ProtectedError):
                record.delete()
        membership = CaseMembership.objects.get(case=self.alpha, user=self.a)
        # Composite FK protects historical references even against direct link deletion.
        self.assert_rejected(lambda: membership.delete())

    def test_deactivation_keeps_history_and_archives_remain_authorized(self):
        staff = User.objects.get(email="staff.a@example.test")
        membership = CaseMembership.objects.get(case=self.alpha, user=staff)
        membership.update_with_revision(1, is_active=False)
        self.assertTrue(CaseMembership.objects.filter(pk=membership.pk).exists())
        self.assertFalse(cases_visible_to(staff).filter(pk=self.alpha.pk).exists())
        self.alpha.update_with_revision(
            self.alpha.revision, status="Closed", closed_on=self.alpha.opened_on, is_archived=True
        )
        client = self.alpha.clients.first()
        client.update_with_revision(client.revision, status="Archived")
        self.assertTrue(cases_visible_to(self.a).filter(pk=self.alpha.pk).exists())
        self.assertTrue(clients_visible_to(self.a).filter(pk=client.pk).exists())
        self.assertFalse(cases_visible_to(self.b).filter(pk=self.alpha.pk).exists())
        document = Document.objects.get(state="Archived")
        self.assertTrue(document.file.storage.exists(document.file.name))

    def test_expected_query_indexes_exist_in_postgresql(self):
        expected = {
            "cases_case": {"case_worklist_idx", "case_docket_idx"},
            "cases_case_members": {"membership_access_idx", "one_active_lead_per_case"},
            "work_task": {"task_worklist_idx"},
            "work_deadline": {"deadline_worklist_idx", "deadline_case_dates_idx"},
            "audit_auditevent": {"audit_target_time_idx", "audit_request_idx"},
        }
        with connection.cursor() as cursor:
            for table, names in expected.items():
                constraints = connection.introspection.get_constraints(cursor, table)
                self.assertTrue(names <= constraints.keys(), (table, names - constraints.keys()))


class RevisionAndTimezoneTests(SeededTestCase):
    def test_stale_update_fails_without_overwriting_newer_work(self):
        first = Case.objects.get(number="DEMO-ALPHA")
        stale = Case.objects.get(pk=first.pk)
        first.update_with_revision(first.revision, title="Newer title")
        self.assertEqual(first.revision, 2)
        with self.assertRaises(ConcurrentEditError):
            stale.update_with_revision(stale.revision, title="Stale title")
        stale.refresh_from_db()
        self.assertEqual(stale.title, "Newer title")
        for changes in [{"revision": 99}, {"created_at": timezone.now()}, {"unknown": 1}]:
            with self.assertRaises(ValueError):
                stale.update_with_revision(stale.revision, **changes)

    def test_timestamps_roundtrip_in_utc_and_templates_use_firm_dst(self):
        task = Task.objects.first()
        firm = ZoneInfo("America/Los_Angeles")
        for month, utc_hour in [(1, 1), (7, 0)]:
            due = datetime(2026, month, 15, 17, tzinfo=firm)
            task.update_with_revision(task.revision, due_at=due)
            self.assertEqual(task.due_at.tzinfo, UTC)
            self.assertEqual(task.due_at.hour, utc_hour)
            rendered = Template("{{ due|date:'Y-m-d H:i T' }}").render(
                Context({"due": task.due_at})
            )
            self.assertIn("2026-" + f"{month:02d}-15 17:00", rendered)


class AuditHistoryTests(TestCase):
    def event_data(self):
        return dict(
            action="case.update",
            resource_type="case",
            resource_id="42",
            result="success",
            correlation_id=uuid.uuid4(),
            changed_fields=["title", "status"],
        )

    def test_append_only_trigger_rejects_orm_and_sql_changes(self):
        event = AuditEvent.objects.create(**self.event_data())
        for operation in [
            lambda: AuditEvent.objects.filter(pk=event.pk).update(result="failure"),
            lambda: AuditEvent.objects.filter(pk=event.pk).delete(),
        ]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                operation()
        event.refresh_from_db()
        self.assertEqual(event.result, "success")

    def test_metadata_is_limited_to_field_names_and_results_are_enumerated(self):
        for changes in [
            {"changed_fields": ["password"]},
            {"changed_fields": ["title"] * 21},
            {"result": "unrecognized"},
            {"action": "  "},
        ]:
            with (
                self.subTest(changes=changes),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                AuditEvent.objects.create(**{**self.event_data(), **changes})
