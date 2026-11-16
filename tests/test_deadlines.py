"""DATE-01/02: recording, revising, resolving and monitoring deadlines."""

import os
from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.db.models import Max
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from cases.models import Case
from cases.views import upcoming_filter
from work.models import Deadline
from work.transitions import DEADLINE_TRANSITIONS, allows

DEMO_PASSWORD = "Fictional-dates-passphrase-73!"
FIRM = ZoneInfo("America/Los_Angeles")


class DeadlineTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        with patch.dict(os.environ, {"LEXFLOW_DEMO_PASSWORD": DEMO_PASSWORD}):
            call_command("seed_demo", stdout=StringIO())
        cls.attorney = User.objects.get(email="attorney.a@example.test")
        cls.other_attorney = User.objects.get(email="attorney.b@example.test")
        cls.staff = User.objects.get(email="staff.a@example.test")
        cls.alpha = Case.objects.get(number="DEMO-ALPHA")
        cls.beta = Case.objects.get(number="DEMO-BETA")

    def setUp(self):
        self.deadline = Deadline.objects.filter(case=self.alpha).order_by("pk").first()
        self.mark = AuditEvent.objects.aggregate(top=Max("pk"))["top"] or 0

    def new_events(self):
        return AuditEvent.objects.filter(pk__gt=self.mark)

    def url(self, name, *args):
        return reverse(name, args=[self.alpha.pk, *args])


class TransitionRuleTests(TestCase):
    def test_resolution_is_reversible_but_never_sideways(self):
        permitted = {
            (Deadline.Status.PENDING, Deadline.Status.COMPLETED),
            (Deadline.Status.PENDING, Deadline.Status.CANCELLED),
            (Deadline.Status.COMPLETED, Deadline.Status.PENDING),
            (Deadline.Status.CANCELLED, Deadline.Status.PENDING),
        }
        for current in Deadline.Status:
            for target in Deadline.Status:
                with self.subTest(current=current, target=target):
                    self.assertEqual(
                        allows(DEADLINE_TRANSITIONS, current, target),
                        (current, target) in permitted,
                    )


class DeadlineCreateTests(DeadlineTestCase):
    def payload(self, **overrides):
        return {
            "title": "Fictional filing deadline",
            "type": Deadline.Type.FILING,
            "due_at": (timezone.now() + timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S"),
            "responsible_user": self.attorney.pk,
            "notes": "",
            **overrides,
        }

    def test_a_case_member_records_a_pending_deadline(self):
        self.client.force_login(self.attorney)
        response = self.client.post(self.url("cases:deadline_create"), self.payload())
        self.assertRedirects(response, reverse("cases:detail", args=[self.alpha.pk]))
        created = Deadline.objects.get(title="Fictional filing deadline")
        self.assertEqual(created.status, Deadline.Status.PENDING)
        self.assertEqual(created.created_by, self.attorney)
        self.assertIsNone(created.completed_at)
        self.assertTrue(self.new_events().filter(action="deadline.create").exists())

    def test_missing_title_and_invalid_type_are_rejected(self):
        self.client.force_login(self.attorney)
        before = Deadline.objects.count()
        for bad in [{"title": "  "}, {"type": "Nonsense"}, {"due_at": "not-a-date"}]:
            with self.subTest(**bad):
                response = self.client.post(self.url("cases:deadline_create"), self.payload(**bad))
                self.assertEqual(response.status_code, 400)
        self.assertEqual(Deadline.objects.count(), before)

    def test_a_user_outside_the_case_team_cannot_be_made_responsible(self):
        self.client.force_login(self.attorney)
        response = self.client.post(
            self.url("cases:deadline_create"),
            self.payload(responsible_user=self.other_attorney.pk),
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Deadline.objects.filter(responsible_user=self.other_attorney).exists())

    def test_unassigned_users_and_closed_cases_are_refused(self):
        self.client.force_login(self.other_attorney)
        self.assertEqual(self.client.get(self.url("cases:deadline_create")).status_code, 404)
        Case.objects.filter(pk=self.alpha.pk).update(
            status=Case.Status.CLOSED, closed_on=self.alpha.opened_on
        )
        self.client.force_login(self.attorney)
        self.assertEqual(self.client.get(self.url("cases:deadline_create")).status_code, 403)

    def test_anonymous_creation_fails(self):
        response = self.client.post(self.url("cases:deadline_create"), self.payload())
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Deadline.objects.filter(title="Fictional filing deadline").exists())


class DeadlineEditTests(DeadlineTestCase):
    def test_moving_the_date_is_saved_and_recorded(self):
        self.client.force_login(self.attorney)
        moved = (timezone.now() + timedelta(days=30)).replace(microsecond=0)
        response = self.client.post(
            self.url("cases:deadline_edit", self.deadline.pk),
            {
                "revision": self.deadline.revision,
                "title": self.deadline.title,
                "type": self.deadline.type,
                "due_at": moved.strftime("%Y-%m-%d %H:%M:%S"),
                "responsible_user": self.deadline.responsible_user_id,
                "notes": "Moved by agreement",
            },
        )
        self.assertRedirects(response, reverse("cases:detail", args=[self.alpha.pk]))
        self.deadline.refresh_from_db()
        self.assertEqual(self.deadline.due_at.date(), moved.date())
        event = self.new_events().get(action="deadline.edit")
        self.assertIn("due_at", event.changed_fields)

    def test_a_stale_revision_is_rejected(self):
        self.client.force_login(self.attorney)
        response = self.client.post(
            self.url("cases:deadline_edit", self.deadline.pk),
            {
                "revision": self.deadline.revision + 9,
                "title": "Should not save",
                "type": self.deadline.type,
                "due_at": self.deadline.due_at.strftime("%Y-%m-%d %H:%M:%S"),
                "responsible_user": self.deadline.responsible_user_id,
                "notes": "",
            },
        )
        self.assertEqual(response.status_code, 409)
        self.deadline.refresh_from_db()
        self.assertNotEqual(self.deadline.title, "Should not save")


class DeadlineResolutionTests(DeadlineTestCase):
    def resolve(self, status=Deadline.Status.COMPLETED, notes="Filed with the court"):
        return self.client.post(
            self.url("cases:deadline_resolve", self.deadline.pk),
            {"revision": self.deadline.revision, "status": status, "completion_notes": notes},
        )

    def test_resolution_records_actor_instant_and_reason(self):
        self.client.force_login(self.attorney)
        self.assertRedirects(self.resolve(), reverse("cases:detail", args=[self.alpha.pk]))
        self.deadline.refresh_from_db()
        self.assertEqual(self.deadline.status, Deadline.Status.COMPLETED)
        self.assertEqual(self.deadline.completed_by, self.attorney)
        self.assertIsNotNone(self.deadline.completed_at)
        self.assertEqual(self.deadline.completion_notes, "Filed with the court")

    def test_a_blank_reason_is_refused(self):
        self.client.force_login(self.attorney)
        response = self.resolve(notes="   ")
        self.assertEqual(response.status_code, 400)
        self.deadline.refresh_from_db()
        self.assertEqual(self.deadline.status, Deadline.Status.PENDING)

    def test_resolving_twice_reports_conflict(self):
        self.client.force_login(self.attorney)
        self.resolve()
        self.deadline.refresh_from_db()
        self.assertEqual(self.resolve().status_code, 409)

    def test_reopening_clears_the_completion_details(self):
        self.client.force_login(self.attorney)
        self.resolve(status=Deadline.Status.CANCELLED, notes="No longer required")
        self.deadline.refresh_from_db()
        response = self.client.post(
            self.url("cases:deadline_reopen", self.deadline.pk),
            {"revision": self.deadline.revision},
        )
        self.assertRedirects(response, reverse("cases:detail", args=[self.alpha.pk]))
        self.deadline.refresh_from_db()
        self.assertEqual(self.deadline.status, Deadline.Status.PENDING)
        self.assertIsNone(self.deadline.completed_at)
        self.assertIsNone(self.deadline.completed_by)
        self.assertEqual(self.deadline.completion_notes, "")

    def test_reopening_a_pending_deadline_reports_conflict(self):
        self.client.force_login(self.attorney)
        response = self.client.post(
            self.url("cases:deadline_reopen", self.deadline.pk),
            {"revision": self.deadline.revision},
        )
        self.assertEqual(response.status_code, 409)


class DeadlineListTests(DeadlineTestCase):
    def test_the_list_shows_only_authorized_deadlines(self):
        hidden = Deadline.objects.create(
            case=self.beta,
            title="Beta only deadline",
            type=Deadline.Type.HEARING,
            due_at=timezone.now() + timedelta(days=2),
            responsible_user=self.other_attorney,
            created_by=self.other_attorney,
        )
        self.client.force_login(self.staff)
        response = self.client.get(reverse("cases:deadlines"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(hidden.pk, [d.pk for d in response.context["page"]])
        self.assertNotContains(response, "Beta only deadline")

    def test_overdue_excludes_resolved_items(self):
        self.client.force_login(self.attorney)
        Deadline.objects.filter(pk=self.deadline.pk).update(
            due_at=timezone.now() - timedelta(days=3)
        )
        response = self.client.get(reverse("cases:deadlines"), {"window": "overdue"})
        self.assertIn(self.deadline.pk, [d.pk for d in response.context["page"]])
        Deadline.objects.filter(pk=self.deadline.pk).update(
            status=Deadline.Status.COMPLETED,
            completed_at=timezone.now(),
            completed_by=self.attorney,
            completion_notes="done",
        )
        response = self.client.get(reverse("cases:deadlines"), {"window": "overdue"})
        self.assertNotIn(self.deadline.pk, [d.pk for d in response.context["page"]])

    def test_an_invalid_filter_and_page_are_rejected(self):
        self.client.force_login(self.attorney)
        response = self.client.get(reverse("cases:deadlines"), {"status": "Nonsense"})
        self.assertIsNone(response.context["page"])
        self.assertTrue(response.context["form"].errors)
        response = self.client.get(reverse("cases:deadlines"), {"page": "9999"})
        self.assertIsNone(response.context["page"])

    def test_anonymous_access_is_refused(self):
        response = self.client.get(reverse("cases:deadlines"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])


class UpcomingBoundaryTests(TestCase):
    """DATE-02 boundaries, including the daylight-saving transitions."""

    @classmethod
    def setUpTestData(cls):
        with patch.dict(os.environ, {"LEXFLOW_DEMO_PASSWORD": DEMO_PASSWORD}):
            call_command("seed_demo", stdout=StringIO())
        cls.case = Case.objects.get(number="DEMO-ALPHA")
        cls.attorney = User.objects.get(email="attorney.a@example.test")

    def make(self, local_dt, title):
        return Deadline.objects.create(
            case=self.case,
            title=title,
            type=Deadline.Type.OTHER,
            due_at=local_dt.astimezone(ZoneInfo("UTC")),
            responsible_user=self.attorney,
            created_by=self.attorney,
        )

    def included(self, now):
        window = upcoming_filter(Deadline.objects.all(), now=now)
        return set(window.values_list("title", flat=True))

    def test_window_runs_through_the_end_of_firm_local_day_plus_seven(self):
        now = datetime(2026, 6, 1, 9, 0, tzinfo=FIRM)
        self.make(now + timedelta(minutes=1), "in one minute")
        self.make(now - timedelta(minutes=1), "already past")
        self.make(datetime(2026, 6, 8, 23, 59, tzinfo=FIRM), "end of day plus seven")
        self.make(datetime(2026, 6, 9, 0, 1, tzinfo=FIRM), "day plus eight")
        self.assertSetEqual(
            self.included(now.astimezone(ZoneInfo("UTC"))),
            {"in one minute", "end of day plus seven"},
        )

    def test_the_boundary_holds_across_the_spring_forward_change(self):
        # 2026-03-08 is the US spring-forward date; the window still ends at a
        # real local midnight rather than drifting by an hour.
        now = datetime(2026, 3, 2, 12, 0, tzinfo=FIRM)
        self.make(datetime(2026, 3, 9, 23, 59, tzinfo=FIRM), "inside after spring forward")
        self.make(datetime(2026, 3, 10, 0, 30, tzinfo=FIRM), "outside after spring forward")
        self.assertSetEqual(
            self.included(now.astimezone(ZoneInfo("UTC"))), {"inside after spring forward"}
        )

    def test_the_boundary_holds_across_the_autumn_change(self):
        now = datetime(2026, 10, 27, 12, 0, tzinfo=FIRM)
        self.make(datetime(2026, 11, 3, 23, 59, tzinfo=FIRM), "inside after fall back")
        self.make(datetime(2026, 11, 4, 0, 30, tzinfo=FIRM), "outside after fall back")
        self.assertSetEqual(
            self.included(now.astimezone(ZoneInfo("UTC"))), {"inside after fall back"}
        )
