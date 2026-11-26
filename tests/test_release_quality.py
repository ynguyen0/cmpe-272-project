"""DEL-01: HTTP authorization inventory and cross-feature regressions."""

from datetime import UTC, datetime

from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client as Browser
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from cases import urls
from cases.forms import TaskAssignmentForm
from cases.models import Case, CaseClient, CaseMembership
from clients.models import Client
from documents.models import Document
from work.models import Deadline, Task

from .test_foundation import SeededTestCase


class ProtectedOperationTests(SeededTestCase):
    def setUp(self):
        self.actor = User.objects.get(email="attorney.a@example.test")
        self.staff = User.objects.get(email="staff.a@example.test")
        self.case = Case.objects.get(number="DEMO-ALPHA")
        self.document = Document.objects.get(case=self.case, state="Active")
        self.task = Task.objects.filter(case=self.case).first()
        self.contact = Client.objects.get(email="client.alpha@example.test")
        self.deadline = Deadline.objects.filter(case=self.case).first()
        # Every case/client endpoint has an explicit HTTP permission test below.
        self.routes = {
            "dashboard": ([], False),
            "search": ([], False),
            "work": ([], False),
            "deadlines": ([], False),
            "index": ([], False),
            "clients": ([], False),
            "client_create": ([], True),
            "client_detail": ([self.contact.pk], False),
            "client_edit": ([self.contact.pk], True),
            "client_archive": ([self.contact.pk], True),
            "audit": ([], False),
            "create": ([], True),
            "detail": ([self.case.pk], False),
            "link_client": ([self.case.pk], True),
            "edit": ([self.case.pk], True),
            "team": ([self.case.pk], True),
            "status": ([self.case.pk], True),
            "archive": ([self.case.pk], True),
            "documents": ([self.case.pk], False),
            "document_upload": ([self.case.pk], True),
            "document_download": ([self.case.pk, self.document.pk], False),
            "document_edit": ([self.case.pk, self.document.pk], True),
            "document_archive": ([self.case.pk, self.document.pk], True),
            "task_assign": ([self.case.pk], True),
            "task_reassign": ([self.case.pk, self.task.pk], True),
            "task_complete": ([self.case.pk, self.task.pk], True),
            "task_edit": ([self.case.pk, self.task.pk], True),
            "task_status": ([self.case.pk, self.task.pk], True),
            "deadline_create": ([self.case.pk], True),
            "deadline_edit": ([self.case.pk, self.deadline.pk], True),
            "deadline_resolve": ([self.case.pk, self.deadline.pk], True),
            "deadline_reopen": ([self.case.pk, self.deadline.pk], True),
        }

    def business_state(self):
        return {
            model._meta.label: list(
                model.objects.order_by("pk").values(
                    *(
                        field.attname
                        for field in model._meta.concrete_fields
                        if field.name != "last_login"
                    )
                )
            )
            for model in (User, Case, CaseClient, CaseMembership, Client, Document, Task, Deadline)
        }

    def test_route_inventory_cannot_silently_omit_new_protected_operations(self):
        self.assertSetEqual(set(self.routes), {route.name for route in urls.urlpatterns})

    def test_every_operation_rejects_anonymous_and_deactivated_sessions(self):
        original = self.business_state()
        for state in ("anonymous", "deactivated"):
            browser = Browser()
            if state == "deactivated":
                browser.force_login(self.actor)
                User.objects.filter(pk=self.actor.pk).update(is_active=False)
                original = self.business_state()
            for name, (args, mutates) in self.routes.items():
                for method in ("get", "post") if mutates else ("get",):
                    with self.subTest(state=state, route=name, method=method):
                        response = getattr(browser, method)(reverse(f"cases:{name}", args=args))
                        self.assertEqual(response.status_code, 302)
                        self.assertTrue(response.url.startswith(reverse("accounts:login")))
            for name, args in (("list", []), ("create", []), ("access", [self.staff.pk])):
                with self.subTest(state=state, account_route=name):
                    self.assertEqual(
                        browser.get(reverse(f"accounts:{name}", args=args)).status_code, 302
                    )
                    if name != "list":
                        self.assertEqual(
                            browser.post(reverse(f"accounts:{name}", args=args)).status_code, 302
                        )
            self.assertEqual(self.business_state(), original)

    def test_every_record_operation_rejects_wrong_case_and_removed_membership(self):
        for state in ("wrong case", "membership removed"):
            actor = User.objects.get(email="attorney.b@example.test")
            if state == "membership removed":
                actor = self.actor
                CaseMembership.objects.filter(case=self.case, user=actor).update(is_active=False)
            self.client.force_login(actor)
            original = self.business_state()
            for name, (args, mutates) in self.routes.items():
                if not args:
                    continue
                for method in ("get", "post") if mutates else ("get",):
                    with self.subTest(state=state, route=name, method=method):
                        response = getattr(self.client, method)(reverse(f"cases:{name}", args=args))
                        self.assertEqual(response.status_code, 404)
                        for secret in (self.case.title, self.contact.name, self.document.title):
                            self.assertNotContains(response, secret, status_code=404)
            self.assertEqual(self.business_state(), original)

    def test_every_nested_record_rejects_a_child_from_another_accessible_case(self):
        # Membership in both cases must not allow a child ID to be used under
        # the wrong parent. Exercise every nested GET/POST route in the inventory.
        beta = Case.objects.get(number="DEMO-BETA")
        CaseMembership.objects.create(case=beta, user=self.actor)
        self.client.force_login(self.actor)
        original = self.business_state()
        for name, (args, mutates) in self.routes.items():
            if len(args) != 2:
                continue
            swapped = [beta.pk, args[1]]
            for method in ("get", "post") if mutates else ("get",):
                with self.subTest(route=name, method=method):
                    response = getattr(self.client, method)(reverse(f"cases:{name}", args=swapped))
                    self.assertEqual(response.status_code, 404)
                    for secret in (self.document.title, self.task.title, self.deadline.title):
                        self.assertNotContains(response, secret, status_code=404)
        self.assertEqual(self.business_state(), original)

    def test_staff_cannot_invoke_role_restricted_operations_directly(self):
        self.client.force_login(self.staff)
        original = self.business_state()
        restricted = (
            "client_create",
            "client_archive",
            "create",
            "audit",
            "link_client",
            "team",
            "status",
            "archive",
            "document_upload",
            "document_edit",
            "document_archive",
            "task_assign",
            "task_reassign",
            "task_edit",
            "deadline_create",
            "deadline_edit",
            "deadline_resolve",
            "deadline_reopen",
        )
        for name in restricted:
            args, mutates = self.routes[name]
            for method in ("get", "post") if mutates else ("get",):
                with self.subTest(route=name, method=method):
                    response = getattr(self.client, method)(reverse(f"cases:{name}", args=args))
                    self.assertEqual(response.status_code, 403)
        for name, args in (("list", []), ("create", []), ("access", [self.actor.pk])):
            for method in ("get",) if name == "list" else ("get", "post"):
                with self.subTest(account_route=name, method=method):
                    self.assertEqual(
                        getattr(self.client, method)(
                            reverse(f"accounts:{name}", args=args)
                        ).status_code,
                        403,
                    )
        self.assertEqual(self.business_state(), original)

    def test_all_mutation_routes_require_csrf_and_reject_unsafe_methods(self):
        browser = Browser(enforce_csrf_checks=True)
        browser.force_login(self.actor)
        original = self.business_state()
        protected = [
            reverse(f"cases:{name}", args=args)
            for name, (args, mutates) in self.routes.items()
            if mutates
        ] + [
            reverse("accounts:create"),
            reverse("accounts:access", args=[self.staff.pk]),
            reverse("accounts:password_change"),
            reverse("accounts:logout"),
        ]
        for url in protected:
            with self.subTest(url=url):
                self.assertEqual(browser.post(url).status_code, 403)
        self.client.force_login(self.actor)
        for name, (args, _) in self.routes.items():
            with self.subTest(route=name):
                self.assertEqual(
                    self.client.delete(reverse(f"cases:{name}", args=args)).status_code, 405
                )
        self.assertEqual(self.business_state(), original)


class WorkValidationTests(SeededTestCase):
    def setUp(self):
        self.actor = User.objects.get(email="attorney.a@example.test")
        self.case = Case.objects.get(number="DEMO-ALPHA")
        self.client.force_login(self.actor)
        self.url = reverse("cases:task_assign", args=[self.case.pk])
        self.data = {
            "title": "Fictional boundary task",
            "description": "Synthetic",
            "assignee": self.actor.pk,
            "priority": "Normal",
            "due_at": "2026-11-25T17:00",
        }

    def test_invalid_dates_and_dst_gaps_and_folds_leave_no_task(self):
        for value in ("", "2026-02-30T17:00", "2026-03-08T02:30", "2026-11-01T01:30", "2026-11-25"):
            with self.subTest(value=value), timezone.override(settings.TIME_ZONE):
                response = self.client.post(self.url, {**self.data, "due_at": value})
                self.assertEqual(response.status_code, 400)
                self.assertIn("due_at", response.context["form"].errors)
        self.assertFalse(Task.objects.filter(title=self.data["title"]).exists())

    def test_new_work_forms_reject_date_only_input(self):
        task = Task.objects.filter(case=self.case).first()
        deadline = Deadline.objects.filter(case=self.case).first()
        for name, args, data in (
            (
                "task_edit",
                [self.case.pk, task.pk],
                {
                    **self.data,
                    "revision": task.revision,
                },
            ),
            (
                "deadline_create",
                [self.case.pk],
                {
                    "title": "Synthetic date validation",
                    "type": "Filing",
                    "responsible_user": self.actor.pk,
                },
            ),
            (
                "deadline_edit",
                [self.case.pk, deadline.pk],
                {
                    "title": deadline.title,
                    "type": deadline.type,
                    "responsible_user": self.actor.pk,
                    "revision": deadline.revision,
                },
            ),
        ):
            data.pop("assignee", None)
            with self.subTest(route=name):
                response = self.client.post(
                    reverse(f"cases:{name}", args=args),
                    {
                        **data,
                        "due_at": "2026-11-25",
                    },
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("due_at", response.context["form"].errors)

    def test_local_and_offset_inputs_resolve_to_the_same_utc_instant(self):
        for value in ("2026-11-25T17:00", "2026-11-26T01:00:00+00:00"):
            with self.subTest(value=value), timezone.override(settings.TIME_ZONE):
                form = TaskAssignmentForm({**self.data, "due_at": value}, case=self.case)
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["due_at"], datetime(2026, 11, 26, 1, tzinfo=UTC))

    def test_unexpected_multipart_field_is_rejected_without_business_changes(self):
        task = Task.objects.filter(case=self.case).first()
        deadline = Deadline.objects.filter(case=self.case).first()
        deadline_data = {
            "title": "Synthetic multipart deadline",
            "type": "Filing",
            "due_at": self.data["due_at"],
            "responsible_user": self.actor.pk,
        }
        task_data = {key: value for key, value in self.data.items() if key != "assignee"}
        attempts = [
            (
                reverse("cases:task_edit", args=[self.case.pk, task.pk]),
                {**task_data, "revision": task.revision},
            ),
            (reverse("cases:deadline_create", args=[self.case.pk]), deadline_data),
            (
                reverse("cases:deadline_edit", args=[self.case.pk, deadline.pk]),
                {**deadline_data, "revision": deadline.revision},
            ),
            (
                reverse("cases:deadline_resolve", args=[self.case.pk, deadline.pk]),
                {
                    "revision": deadline.revision,
                    "status": "Completed",
                    "completion_notes": "Synthetic",
                },
            ),
            (self.url, self.data),
            (
                reverse("cases:task_reassign", args=[self.case.pk, task.pk]),
                {"revision": task.revision, "assignee": self.actor.pk},
            ),
            (
                reverse("cases:client_create"),
                {"name": "Fictional forged intake", "type": "Individual"},
            ),
        ]
        original = (
            Task.objects.count(),
            Client.objects.count(),
            task.revision,
            task.assignee_id,
            list(Deadline.objects.order_by("pk").values()),
        )
        for url, data in attempts:
            with self.subTest(url=url):
                response = self.client.post(
                    url,
                    {**data, "unexpected_file": SimpleUploadedFile("unexpected.txt", b"Synthetic")},
                )
                self.assertEqual(response.status_code, 400)
                self.assertContains(response, "unsupported fields", status_code=400)
        task.refresh_from_db()
        self.assertEqual(
            (
                Task.objects.count(),
                Client.objects.count(),
                task.revision,
                task.assignee_id,
                list(Deadline.objects.order_by("pk").values()),
            ),
            original,
        )

    def test_two_sessions_cannot_reassign_over_each_others_changes(self):
        task = Task.objects.filter(case=self.case).first()
        url = reverse("cases:task_reassign", args=[self.case.pk, task.pk])
        other = Browser()
        other.force_login(self.actor)
        revision = self.client.get(url).context["form"].initial["revision"]
        self.assertEqual(other.get(url).context["form"].initial["revision"], revision)
        data = {"revision": revision, "assignee": self.actor.pk}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(other.post(url, {**data, "assignee": task.assignee_id}).status_code, 409)
        task.refresh_from_db()
        self.assertEqual(task.assignee, self.actor)
        self.assertEqual(task.revision, revision + 1)


class ValidationAuditTests(SeededTestCase):
    def setUp(self):
        self.actor = User.objects.get(email="attorney.a@example.test")
        self.case = Case.objects.get(number="DEMO-ALPHA")
        self.client.force_login(self.actor)

    def failure(self, response, resource_type, resource_id):
        self.assertIn(response.status_code, (400, 409))
        event = AuditEvent.objects.get(action="validation.failed")
        self.assertEqual(event.actor, self.actor)
        self.assertEqual(event.result, AuditEvent.Result.FAILURE)
        self.assertEqual(event.resource_type, resource_type)
        self.assertEqual(event.resource_id, str(resource_id))
        self.assertEqual(event.changed_fields, [])
        self.assertNotIn("Confidential synthetic input", str(event.__dict__))
        return event

    def test_invalid_deadline_records_a_redacted_failure(self):
        before = Deadline.objects.count()
        response = self.client.post(
            reverse("cases:deadline_create", args=[self.case.pk]),
            {
                "title": "",
                "type": "Filing",
                "due_at": "not a date",
                "responsible_user": self.actor.pk,
                "notes": "Confidential synthetic input",
            },
        )
        self.failure(response, "case", self.case.pk)
        self.assertEqual(Deadline.objects.count(), before)

    def test_stale_task_write_records_failure_and_preserves_saved_assignee(self):
        task = Task.objects.filter(case=self.case).first()
        revision = task.revision
        task.update_with_revision(revision, assignee=self.actor)
        response = self.client.post(
            reverse("cases:task_reassign", args=[self.case.pk, task.pk]),
            {
                "revision": revision,
                "assignee": task.created_by_id,
            },
        )
        self.failure(response, "task", task.pk)
        task.refresh_from_db()
        self.assertEqual(task.assignee, self.actor)
        self.assertEqual(task.revision, revision + 1)

    def test_invalid_audit_filter_records_failure_without_filter_text(self):
        self.actor = User.objects.get(email="admin@example.test")
        self.actor.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="cases", codename="view_organization_audit"
            )
        )
        self.client.force_login(self.actor)
        response = self.client.get(
            reverse("cases:audit"),
            {
                "resource_id": "Confidential synthetic input",
            },
        )
        self.failure(response, "audit_log", "")
