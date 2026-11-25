from datetime import timedelta
from unittest.mock import patch

from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from cases.models import Case, CaseMembership
from clients.models import Client
from work.models import Deadline, Task

from .test_foundation import SeededTestCase


class CaseManagementTests(SeededTestCase):
    def setUp(self):
        self.attorney = User.objects.get(email="attorney.a@example.test")
        self.other_attorney = User.objects.get(email="attorney.b@example.test")
        self.staff = User.objects.get(email="staff.a@example.test")
        self.alpha = Case.objects.get(number="DEMO-ALPHA")
        self.beta = Case.objects.get(number="DEMO-BETA")
        self.primary = Client.objects.get(email="client.alpha@example.test")
        self.intake = Client.objects.get(email="client.unlinked.a@example.test")
        self.hidden = Client.objects.get(email="client.beta@example.test")
        self.client.force_login(self.attorney)

    def create_data(self):
        return {
            "title": "Fictional Harbor matter",
            "type": Case.Type.CIVIL,
            "summary": "Fictional description",
            "court_docket_number": "FICT-09",
            "opened_on": (timezone.localdate() - timedelta(days=1)).isoformat(),
            "client": self.primary.pk,
            "additional_clients": [self.intake.pk],
            "responsible_attorney": self.attorney.pk,
            "assigned_staff": [self.staff.pk],
        }

    def test_case_creation_validates_all_relationships_before_creating_any(self):
        url = reverse("cases:create")
        data = self.create_data()
        inactive = User.objects.get(email="inactive@example.test")
        for overrides in (
            {"additional_clients": [self.primary.pk]},
            {"additional_clients": [self.intake.pk, self.intake.pk]},
            {"additional_clients": [self.intake.pk, self.hidden.pk]},
            {"assigned_staff": [self.staff.pk, inactive.pk]},
            {"assigned_staff": [self.other_attorney.pk]},
            {"responsible_attorney": self.staff.pk},
        ):
            self.assertEqual(self.client.post(url, data | overrides).status_code, 400)
        self.assertFalse(Case.objects.filter(title=data["title"]).exists())
        self.assertFalse(self.intake.case_links.exists())
        self.assertFalse(AuditEvent.objects.filter(action="case.create").exists())

        self.assertEqual(self.client.post(url, data).status_code, 302)
        case = Case.objects.get(title=data["title"])
        self.assertTrue(case.number.startswith("CASE-"))
        self.assertEqual(case.opened_on.isoformat(), data["opened_on"])
        self.assertCountEqual(case.clients.all(), [self.primary, self.intake])
        self.assertSetEqual(
            set(case.memberships.values_list("user_id", "responsibility")),
            {
                (self.attorney.pk, CaseMembership.Responsibility.LEAD),
                (self.staff.pk, CaseMembership.Responsibility.SUPPORT),
            },
        )
        self.client.force_login(self.staff)
        self.assertContains(
            self.client.get(reverse("cases:detail", args=[case.pk])), self.intake.name
        )

    def test_case_creation_rolls_back_if_audit_cannot_commit(self):
        data = self.create_data()
        member_count = CaseMembership.objects.count()
        with (
            patch("cases.views.audit_change", side_effect=RuntimeError("audit failure")),
            self.assertRaisesMessage(RuntimeError, "audit failure"),
        ):
            self.client.post(reverse("cases:create"), data)
        self.assertFalse(Case.objects.filter(title=data["title"]).exists())
        self.assertFalse(self.intake.case_links.exists())
        self.assertEqual(CaseMembership.objects.count(), member_count)

    def test_team_transfer_preserves_membership_history_and_revokes_removed_staff_access(self):
        self.client.post(reverse("cases:create"), self.create_data())
        case = Case.objects.get(title=self.create_data()["title"])
        team_url = reverse("cases:team", args=[case.pk])
        data = {"revision": case.revision, "responsible_attorney": self.other_attorney.pk}
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(team_url, data).status_code, 403)
        self.client.force_login(self.attorney)
        self.assertEqual(self.client.post(team_url, data).status_code, 302)
        self.assertContains(self.client.post(team_url, data), "Reload", status_code=409)
        case.refresh_from_db()
        self.assertEqual(case.responsible_attorney, self.other_attorney)
        self.assertFalse(case.memberships.get(user=self.staff).is_active)
        self.assertEqual(case.memberships.get(user=self.attorney).responsibility, "Attorney")
        event = AuditEvent.objects.get(action="case.team", resource_id=str(case.pk))
        self.assertCountEqual(event.changed_fields, ["members", "responsible_attorney"])
        detail_url = reverse("cases:detail", args=[case.pk])
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(detail_url).status_code, 404)
        self.client.force_login(self.other_attorney)
        self.assertContains(self.client.get(detail_url), case.title)

    def test_team_cannot_remove_staff_with_unfinished_work(self):
        response = self.client.post(
            reverse("cases:team", args=[self.alpha.pk]),
            {"revision": self.alpha.revision, "responsible_attorney": self.attorney.pk},
        )
        self.assertContains(response, "Reassign unfinished tasks", status_code=409)
        self.assertTrue(self.alpha.memberships.get(user=self.staff).is_active)

    def test_closed_case_preserves_workspace_and_reopening_clears_date(self):
        case = self.alpha
        status_url = reverse("cases:status", args=[case.pk])
        detail_url = reverse("cases:detail", args=[case.pk])

        def change(status):
            return self.client.post(status_url, {"revision": case.revision, "status": status})

        self.client.force_login(self.staff)
        self.assertEqual(change(Case.Status.IN_PROGRESS).status_code, 403)
        self.client.force_login(self.attorney)
        self.assertEqual(change(Case.Status.IN_PROGRESS).status_code, 302)
        self.assertEqual(change(Case.Status.ON_HOLD).status_code, 409)
        case.refresh_from_db()
        self.assertEqual(case.status, Case.Status.IN_PROGRESS)
        self.assertEqual(change(Case.Status.ON_HOLD).status_code, 302)
        case.refresh_from_db()

        case.tasks.update(is_archived=True)
        blocked = change(Case.Status.CLOSED)
        self.assertContains(blocked, case.tasks.first().title, status_code=409)
        self.assertContains(blocked, case.deadlines.first().title, status_code=409)
        case.tasks.update(status=Task.Status.DONE, completed_at=timezone.now())
        case.deadlines.update(
            status=Deadline.Status.COMPLETED,
            completed_by=self.attorney,
            completed_at=timezone.now(),
            completion_notes="Fictional completion",
        )
        self.assertEqual(change(Case.Status.CLOSED).status_code, 302)
        case.refresh_from_db()
        self.assertEqual(case.closed_on, timezone.localdate())
        workspace = self.client.get(detail_url)
        self.assertContains(workspace, case.tasks.first().title)
        self.assertContains(workspace, case.deadlines.first().title)
        self.assertContains(workspace, self.staff.full_name)
        document = case.documents.filter(state="Active").get()
        download_url = reverse("cases:document_download", args=[case.pk, document.pk])
        self.assertIn(b"Fictional", b"".join(self.client.get(download_url).streaming_content))
        self.assertEqual(self.client.get(reverse("cases:edit", args=[case.pk])).status_code, 403)
        self.assertEqual(change(Case.Status.IN_PROGRESS).status_code, 400)
        self.assertEqual(change(Case.Status.OPEN).status_code, 302)
        case.refresh_from_db()
        self.assertIsNone(case.closed_on)
        self.assertEqual(change(Case.Status.CLOSED).status_code, 302)
        case.refresh_from_db()
        archive_url = reverse("cases:archive", args=[case.pk])
        self.assertEqual(
            self.client.post(archive_url, {"revision": case.revision}).status_code, 302
        )
        case.refresh_from_db()
        self.assertEqual(change(Case.Status.OPEN).status_code, 403)
        self.assertContains(self.client.get(detail_url), document.title)
        events = set(
            AuditEvent.objects.filter(resource_type="case", resource_id=str(case.pk)).values_list(
                "action", flat=True
            )
        )
        self.assertEqual(
            events,
            {
                "case.view",
                "case.in_progress",
                "case.on_hold",
                "case.close",
                "case.reopen",
                "case.archive",
                "validation.failed",
                # Staff's status change, editing the closed case and reopening the
                # archived one were all refused.
                "access.denied",
            },
        )
        denials = AuditEvent.objects.filter(
            resource_type="case", resource_id=str(case.pk), action="access.denied"
        )
        self.assertEqual(denials.count(), 3)
        self.assertEqual(set(denials.values_list("result", flat=True)), {"denied"})

    def test_assigned_administrator_can_replace_ineligible_lead_when_reopening(self):
        case = self.alpha
        case.update_with_revision(
            case.revision, status=Case.Status.CLOSED, closed_on=timezone.localdate()
        )
        self.attorney.is_active = False
        self.attorney.save(update_fields=["is_active"])
        admin = User.objects.get(email="admin@example.test")
        self.client.force_login(admin)
        url = reverse("cases:status", args=[case.pk])
        data = {
            "revision": case.revision,
            "status": Case.Status.OPEN,
            "responsible_attorney": self.other_attorney.pk,
        }
        self.assertEqual(self.client.post(url, data).status_code, 404)
        CaseMembership.objects.create(case=case, user=admin)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        case.refresh_from_db()
        self.assertEqual(case.responsible_attorney, self.other_attorney)
        self.assertIsNone(case.closed_on)
        self.assertEqual(
            case.memberships.get(user=self.other_attorney).responsibility, "Lead attorney"
        )

    def test_case_list_filters_sort_and_page_stay_in_scope(self):
        records = Case.objects.bulk_create(
            Case(
                number=f"FICT-{i:02}",
                title=f"Fictional Project {25 - i:02}",
                type=Case.Type.CIVIL,
                status=Case.Status.IN_PROGRESS,
                created_by=self.attorney,
                responsible_attorney=self.attorney,
            )
            for i in range(26)
        )
        CaseMembership.objects.bulk_create(
            CaseMembership(case=case, user=self.attorney) for case in records
        )
        url = reverse("cases:index")
        filters = {"status": "In progress", "type": "Civil", "sort": "title"}
        page = self.client.get(url, filters).context["page"]
        self.assertEqual(len(page), 25)
        self.assertEqual(page[0], records[-1])
        self.assertEqual(
            list(self.client.get(url, filters | {"page": 2}).context["page"]), [records[0]]
        )
        self.assertContains(self.client.get(url, {"q": "DEMO-BETA"}), "No matching cases.")
        self.assertEqual(self.client.get(url, filters | {"page": 3}).status_code, 400)
        self.assertEqual(self.client.get(url, {"sort": "unsupported"}).status_code, 400)
