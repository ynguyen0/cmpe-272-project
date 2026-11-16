"""TASK-01/02/03: task details, status transitions, and the personal work list."""

import os
from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db.models import Max
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from cases.models import Case
from work.models import Task
from work.transitions import TASK_TRANSITIONS, allows

DEMO_PASSWORD = "Fictional-tasks-passphrase-73!"


class TaskTestCase(TestCase):
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
        self.task = Task.objects.filter(case=self.alpha, assignee=self.staff).first()
        self.mark = AuditEvent.objects.aggregate(top=Max("pk"))["top"] or 0

    def new_events(self):
        return AuditEvent.objects.filter(pk__gt=self.mark)

    def edit_url(self):
        return reverse("cases:task_edit", args=[self.alpha.pk, self.task.pk])

    def status_url(self):
        return reverse("cases:task_status", args=[self.alpha.pk, self.task.pk])


class TransitionRuleTests(TestCase):
    """The map itself, independent of any view."""

    def test_permitted_moves_only(self):
        permitted = {
            (Task.Status.TODO, Task.Status.IN_PROGRESS),
            (Task.Status.TODO, Task.Status.DONE),
            (Task.Status.IN_PROGRESS, Task.Status.TODO),
            (Task.Status.IN_PROGRESS, Task.Status.DONE),
            (Task.Status.DONE, Task.Status.TODO),
        }
        for current in Task.Status:
            for target in Task.Status:
                with self.subTest(current=current, target=target):
                    self.assertEqual(
                        allows(TASK_TRANSITIONS, current, target),
                        (current, target) in permitted,
                    )

    def test_unknown_statuses_are_refused(self):
        self.assertFalse(allows(TASK_TRANSITIONS, Task.Status.TODO, "Cancelled"))
        self.assertFalse(allows(TASK_TRANSITIONS, "Nonsense", Task.Status.DONE))
        # Done must not jump straight back into progress.
        self.assertFalse(allows(TASK_TRANSITIONS, Task.Status.DONE, Task.Status.IN_PROGRESS))


class TaskEditTests(TaskTestCase):
    def test_assigned_attorney_updates_details_and_the_change_is_recorded(self):
        self.client.force_login(self.attorney)
        due = (timezone.now() + timedelta(days=3)).replace(microsecond=0)
        response = self.client.post(
            self.edit_url(),
            {
                "revision": self.task.revision,
                "title": "Revised task title",
                "description": "Revised description",
                "priority": Task.Priority.HIGH,
                "due_at": due.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        self.assertRedirects(response, reverse("cases:detail", args=[self.alpha.pk]))
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "Revised task title")
        self.assertEqual(self.task.priority, Task.Priority.HIGH)
        event = self.new_events().get(action="task.edit")
        self.assertCountEqual(
            event.changed_fields, ["title", "description", "priority", "due_at"]
        )

    def test_blank_title_is_rejected_without_changing_the_task(self):
        self.client.force_login(self.attorney)
        response = self.client.post(
            self.edit_url(),
            {
                "revision": self.task.revision,
                "title": "   ",
                "description": "",
                "priority": Task.Priority.NORMAL,
                "due_at": self.task.due_at.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        self.assertEqual(response.status_code, 400)
        title = self.task.title
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, title)

    def test_a_stale_revision_is_rejected_with_conflict(self):
        self.client.force_login(self.attorney)
        response = self.client.post(
            self.edit_url(),
            {
                "revision": self.task.revision + 5,
                "title": "Should not save",
                "description": "",
                "priority": Task.Priority.NORMAL,
                "due_at": self.task.due_at.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        self.assertEqual(response.status_code, 409)
        self.task.refresh_from_db()
        self.assertNotEqual(self.task.title, "Should not save")

    def test_unknown_submitted_fields_are_rejected(self):
        self.client.force_login(self.attorney)
        response = self.client.post(
            self.edit_url(),
            {
                "revision": self.task.revision,
                "title": "Smuggled",
                "description": "",
                "priority": Task.Priority.NORMAL,
                "due_at": self.task.due_at.strftime("%Y-%m-%d %H:%M:%S"),
                "assignee": self.attorney.pk,
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_unassigned_attorney_and_guessed_ids_get_404(self):
        self.client.force_login(self.other_attorney)
        self.assertEqual(self.client.get(self.edit_url()).status_code, 404)
        self.client.force_login(self.attorney)
        missing = reverse("cases:task_edit", args=[self.alpha.pk, 999999])
        self.assertEqual(self.client.get(missing).status_code, 404)

    def test_a_closed_case_refuses_edits(self):
        Case.objects.filter(pk=self.alpha.pk).update(
            status=Case.Status.CLOSED, closed_on=self.alpha.opened_on
        )
        self.client.force_login(self.attorney)
        self.assertEqual(self.client.get(self.edit_url()).status_code, 403)


class TaskStatusTests(TaskTestCase):
    def post_status(self, target, revision=None):
        return self.client.post(
            self.status_url(),
            {"revision": revision or self.task.revision, "status": target},
        )

    def test_assignee_moves_through_the_permitted_states(self):
        self.client.force_login(self.staff)
        self.assertRedirects(
            self.post_status(Task.Status.IN_PROGRESS),
            reverse("cases:detail", args=[self.alpha.pk]),
        )
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.IN_PROGRESS)
        self.assertIsNone(self.task.completed_at)

        self.post_status(Task.Status.DONE)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.DONE)
        self.assertIsNotNone(self.task.completed_at)

    def test_reopening_clears_the_completion_time(self):
        self.client.force_login(self.staff)
        self.post_status(Task.Status.DONE)
        self.task.refresh_from_db()
        self.post_status(Task.Status.TODO)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.TODO)
        self.assertIsNone(self.task.completed_at)

    def test_a_forbidden_transition_is_refused_without_changing_the_task(self):
        self.client.force_login(self.staff)
        self.post_status(Task.Status.DONE)
        self.task.refresh_from_db()
        response = self.post_status(Task.Status.IN_PROGRESS)
        self.assertEqual(response.status_code, 400)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.DONE)

    def test_an_unknown_status_is_refused(self):
        self.client.force_login(self.staff)
        response = self.post_status("Cancelled")
        self.assertEqual(response.status_code, 400)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.TODO)

    def test_only_the_assignee_may_change_status(self):
        # The attorney manages the case but the task is not theirs to complete.
        self.client.force_login(self.attorney)
        self.assertEqual(self.client.get(self.status_url()).status_code, 403)

    def test_status_changes_are_recorded(self):
        self.client.force_login(self.staff)
        self.post_status(Task.Status.IN_PROGRESS)
        event = self.new_events().get(action="task.status")
        self.assertCountEqual(event.changed_fields, ["status", "completed_at"])
        self.assertEqual(event.actor, self.staff)


class WorkListTests(TaskTestCase):
    def test_the_default_list_shows_only_my_own_tasks(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("cases:work"))
        self.assertEqual(response.status_code, 200)
        shown = {task.pk for task in response.context["page"]}
        self.assertSetEqual(
            shown, set(Task.objects.filter(assignee=self.staff).values_list("pk", flat=True))
        )

    def test_filters_narrow_the_list(self):
        self.client.force_login(self.staff)
        Task.objects.filter(pk=self.task.pk).update(priority=Task.Priority.HIGH)
        response = self.client.get(reverse("cases:work"), {"priority": Task.Priority.HIGH})
        self.assertEqual([t.pk for t in response.context["page"]], [self.task.pk])
        response = self.client.get(reverse("cases:work"), {"priority": Task.Priority.LOW})
        self.assertEqual(list(response.context["page"]), [])

    def test_the_overdue_filter_excludes_finished_work(self):
        self.client.force_login(self.staff)
        past = timezone.now() - timedelta(days=2)
        Task.objects.filter(pk=self.task.pk).update(due_at=past)
        response = self.client.get(reverse("cases:work"), {"overdue": "on"})
        self.assertIn(self.task.pk, [t.pk for t in response.context["page"]])
        Task.objects.filter(pk=self.task.pk).update(
            status=Task.Status.DONE, completed_at=timezone.now()
        )
        response = self.client.get(reverse("cases:work"), {"overdue": "on"})
        self.assertNotIn(self.task.pk, [t.pk for t in response.context["page"]])

    def test_the_list_never_reaches_another_team_s_work(self):
        beta_task = Task.objects.create(
            case=self.beta,
            title="Beta only task",
            assignee=self.other_attorney,
            due_at=timezone.now() + timedelta(days=1),
            created_by=self.other_attorney,
        )
        self.client.force_login(self.staff)
        response = self.client.get(reverse("cases:work"), {"status": Task.Status.TODO})
        self.assertNotIn(beta_task.pk, [t.pk for t in response.context["page"]])
        self.assertNotContains(response, "Beta only task")

    def test_an_invalid_page_is_rejected(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("cases:work"), {"page": "9999"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["page"])
        self.assertTrue(response.context["form"].errors)

    def test_anonymous_users_cannot_see_any_work(self):
        response = self.client.get(reverse("cases:work"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response["Location"])

    def test_viewing_the_list_is_recorded(self):
        self.client.force_login(self.staff)
        self.client.get(reverse("cases:work"))
        self.assertTrue(self.new_events().filter(action="task.list").exists())
