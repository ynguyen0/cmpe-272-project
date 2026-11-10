import uuid
from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class SchemaUpgradeTests(TransactionTestCase):
    """Exercise the actual 0001 → current upgrade and reverse using historical models."""

    old_targets = [
        (app, "0001_initial")
        for app in ["accounts", "clients", "cases", "documents", "work", "audit"]
    ]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def setUp(self):
        super().setUp()
        self.latest = MigrationExecutor(connection).loader.graph.leaf_nodes()
        # Always restore the current schema before Django flushes the database.
        self.addCleanup(self.migrate, self.latest)

    def test_upgrade_preserves_links_files_dates_and_audit_then_roundtrips(self):
        old = self.migrate(self.old_targets)
        User = old.get_model("accounts", "User")
        attorney = User.objects.create(
            email="migration@example.test", full_name="Migration", role="Attorney"
        )
        Client = old.get_model("clients", "Client")
        client = Client.objects.create(
            name="Historical client", type="Individual", created_by=attorney
        )
        Case = old.get_model("cases", "Case")
        case = Case.objects.create(
            number="MIGRATION-1", title="Historical case", created_by=attorney
        )
        case.members.add(attorney)
        case.clients.add(client)
        Task = old.get_model("work", "Task")
        task = Task.objects.create(
            case=case,
            title="Historical task",
            assignee=attorney,
            created_by=attorney,
            due_date=date(2026, 7, 15),
            status="Done",
        )
        Deadline = old.get_model("work", "Deadline")
        deadline = Deadline.objects.create(
            case=case,
            title="Historical deadline",
            type="Filing",
            date=date(2026, 1, 15),
            created_by=attorney,
            status="Completed",
        )
        Document = old.get_model("documents", "Document")
        document = Document.objects.create(
            case=case,
            title="Historical file",
            category="Other",
            file="legacy/private-key",
            original_filename="example.txt",
            media_type="text/plain",
            size=20,
            uploaded_by=attorney,
        )
        event = old.get_model("audit", "Event").objects.create(
            actor=attorney,
            action="case.create",
            resource_type="case",
            resource_id=str(case.pk),
            result="success",
            correlation_id=uuid.uuid4(),
        )
        current = self.migrate(self.latest)
        updated = current.get_model("cases", "Case").objects.get(pk=case.pk)
        self.assertEqual(updated.updated_at, case.updated_at)
        self.assertEqual(updated.responsible_attorney_id, attorney.pk)
        self.assertEqual(updated.opened_on, timezone.localdate(case.created_at))
        self.assertEqual(
            current.get_model("cases", "CaseClient").objects.get(case_id=case.pk).client_id,
            client.pk,
        )
        member = current.get_model("cases", "CaseMembership").objects.get(case_id=case.pk)
        self.assertEqual(member.user_id, attorney.pk)
        self.assertEqual(member.responsibility, "Lead attorney")
        new_task = current.get_model("work", "Task").objects.get(pk=task.pk)
        self.assertEqual(new_task.due_at.isoformat(), "2026-07-16T00:00:00+00:00")
        self.assertIsNotNone(new_task.completed_at)
        self.assertEqual(new_task.updated_at, task.updated_at)
        new_deadline = current.get_model("work", "Deadline").objects.get(pk=deadline.pk)
        self.assertEqual(new_deadline.due_at.isoformat(), "2026-01-16T01:00:00+00:00")
        self.assertEqual(new_deadline.updated_at, deadline.updated_at)
        self.assertEqual(new_deadline.responsible_user_id, attorney.pk)
        self.assertEqual(new_deadline.completed_by_id, attorney.pk)
        self.assertEqual(
            current.get_model("documents", "Document").objects.get(pk=document.pk).file.name,
            "legacy/private-key",
        )
        self.assertTrue(
            current.get_model("audit", "AuditEvent").objects.filter(pk=event.pk).exists()
        )
        restored = self.migrate(self.old_targets)
        self.assertEqual(
            restored.get_model("work", "Task").objects.get(pk=task.pk).due_date, date(2026, 7, 15)
        )
        self.assertEqual(
            restored.get_model("work", "Deadline").objects.get(pk=deadline.pk).date,
            date(2026, 1, 15),
        )
        self.assertTrue(restored.get_model("audit", "Event").objects.filter(pk=event.pk).exists())
        self.assertEqual(
            restored.get_model("cases", "Case").objects.get(pk=case.pk).clients.count(), 1
        )
        self.migrate(self.latest)
