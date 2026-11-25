from django.contrib.auth.models import AnonymousUser, Permission
from django.test import Client as Browser
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from cases.models import Case, CaseClient, CaseMembership
from cases.policies import Action, case_allows, has_capability
from clients.models import Client
from documents.models import Document
from work.models import Task

from .test_foundation import SeededTestCase


class PermissionMatrixTests(SeededTestCase):
    def setUp(self):
        self.admin = User.objects.get(email="admin@example.test")
        User.objects.filter(pk=self.admin.pk).update(is_superuser=True, is_staff=True)
        self.admin.refresh_from_db()
        self.attorney = User.objects.get(email="attorney.a@example.test")
        self.other_attorney = User.objects.get(email="attorney.b@example.test")
        self.staff = User.objects.get(email="staff.a@example.test")
        self.inactive = User.objects.get(email="inactive@example.test")
        self.alpha = Case.objects.get(number="DEMO-ALPHA")
        self.beta = Case.objects.get(number="DEMO-BETA")
        self.alpha_client = Client.objects.get(email="client.alpha@example.test")
        self.beta_client = Client.objects.get(email="client.beta@example.test")
        self.shared_client = Client.objects.get(email="client.shared@example.test")
        self.document = Document.objects.get(case=self.alpha, state=Document.State.ACTIVE)
        self.task = Task.objects.filter(case=self.alpha).first()

    def grant(self, user, *actions):
        user.user_permissions.add(
            *Permission.objects.filter(
                content_type__app_label="cases", content_type__model="case", codename__in=actions
            )
        )

    def test_matrix_with_and_without_grants(self):
        common = {Action.VIEW_CASE, Action.EDIT_CASE, Action.COMPLETE_TASK}
        defaults = {
            self.admin: common
            | {
                Action.MANAGE_ACCOUNTS,
                Action.CREATE_RECORDS,
                Action.MANAGE_DOCUMENTS,
                Action.ASSIGN_TASKS,
            },
            self.attorney: common
            | {
                Action.CREATE_RECORDS,
                Action.MANAGE_DOCUMENTS,
                Action.ASSIGN_TASKS,
                Action.ARCHIVE_CASE,
            },
            self.staff: common,
            self.inactive: set(),
            AnonymousUser(): set(),
        }
        extra = {
            self.admin: {Action.ARCHIVE_CASE, Action.VIEW_AUDIT},
            self.staff: {Action.CREATE_RECORDS, Action.MANAGE_DOCUMENTS, Action.ASSIGN_TASKS},
        }
        for user, defaults_for_user in defaults.items():
            with self.subTest(user=user):
                self.assertSetEqual(
                    {action for action in Action if has_capability(user, action)}, defaults_for_user
                )
                self.assertFalse(has_capability(user, "delete_everything"))
                if user.is_authenticated:
                    self.grant(user, *Action)
                    self.assertSetEqual(
                        {action for action in Action if has_capability(user, action)},
                        defaults_for_user | extra.get(user, set()),
                    )

    def test_case_actions_require_current_membership_for_all_roles(self):
        self.grant(self.admin, Action.ARCHIVE_CASE)
        self.grant(self.staff, Action.MANAGE_DOCUMENTS, Action.ASSIGN_TASKS)
        actions = (
            Action.VIEW_CASE,
            Action.EDIT_CASE,
            Action.MANAGE_DOCUMENTS,
            Action.ASSIGN_TASKS,
            Action.COMPLETE_TASK,
        )
        for user in (self.admin, self.attorney, self.staff):
            if user == self.admin:
                self.assertFalse(case_allows(user, Action.VIEW_CASE, self.alpha))
                CaseMembership.objects.create(case=self.alpha, user=user)
            for action in actions:
                with self.subTest(user=user, action=action):
                    self.assertTrue(case_allows(user, action, self.alpha))
                    self.assertFalse(case_allows(user, action, self.beta))
        self.assertTrue(case_allows(self.admin, Action.ARCHIVE_CASE, self.alpha))
        self.assertFalse(case_allows(self.admin, Action.ARCHIVE_CASE, self.beta))
        self.assertTrue(case_allows(self.attorney, Action.ARCHIVE_CASE, self.alpha))
        CaseMembership.objects.create(case=self.alpha, user=self.other_attorney)
        self.assertFalse(case_allows(self.other_attorney, Action.ARCHIVE_CASE, self.alpha))
        self.assertFalse(case_allows(self.staff, Action.ARCHIVE_CASE, self.alpha))
        CaseMembership.objects.create(case=self.alpha, user=self.inactive)
        self.assertFalse(case_allows(self.inactive, Action.VIEW_CASE, self.alpha))

    def test_account_and_audit_routes_have_independent_permissions(self):
        self.client.force_login(self.admin)
        accounts_url = reverse("accounts:list")
        audit_url = reverse("cases:audit")
        self.assertEqual(self.client.get(accounts_url).status_code, 200)
        self.assertEqual(self.client.get(audit_url).status_code, 403)
        self.assertEqual(
            self.client.get(reverse("cases:detail", args=[self.alpha.pk])).status_code, 404
        )
        self.grant(self.admin, Action.VIEW_AUDIT)
        self.assertContains(self.client.get(audit_url), "demo.seed")
        self.admin.user_permissions.clear()
        self.assertEqual(self.client.get(audit_url).status_code, 403)
        for user in (self.attorney, self.staff):
            with self.subTest(user=user):
                self.grant(user, Action.VIEW_AUDIT)
                self.client.force_login(user)
                self.assertEqual(self.client.get(accounts_url).status_code, 403)
                self.assertEqual(self.client.get(audit_url).status_code, 403)

    def test_search_shared_client_and_dashboard_totals_are_scoped(self):
        self.client.force_login(self.other_attorney)
        index = reverse("cases:index")
        self.assertNotContains(self.client.get(index, {"q": "ALPHA"}), self.alpha.title)
        self.assertContains(self.client.get(index, {"q": "BETA"}), self.beta.title)
        self.assertEqual(
            self.client.get(index).context["totals"],
            {
                "Cases": 1,
                "Clients": 3,
                "Documents": 0,
                "Tasks": 0,
                "Deadlines": 0,
            },
        )
        shared = self.client.get(reverse("cases:client_detail", args=[self.shared_client.pk]))
        self.assertContains(shared, self.beta.title)
        self.assertNotContains(shared, self.alpha.title)
        self.assertEqual(
            self.client.get(
                reverse("cases:client_detail", args=[self.alpha_client.pk])
            ).status_code,
            404,
        )
        CaseClient.objects.filter(case=self.beta, client=self.shared_client).update(is_active=False)
        self.assertEqual(
            self.client.get(
                reverse("cases:client_detail", args=[self.shared_client.pk])
            ).status_code,
            404,
        )
        self.client.force_login(self.admin)
        self.assertEqual(set(self.client.get(index).context["totals"].values()), {0})

    def test_direct_download_edit_and_task_requests_reject_swapped_identifiers(self):
        beta_task = Task.objects.create(
            case=self.beta,
            title="Beta task",
            assignee=self.other_attorney,
            due_at=timezone.now(),
            created_by=self.other_attorney,
        )
        beta_doc = Document.objects.create(
            case=self.beta,
            title="Beta document",
            category=Document.Category.OTHER,
            file="cases/beta-private-test",
            original_filename="beta-private.txt",
            size=1,
            media_type="text/plain",
            uploaded_by=self.other_attorney,
        )
        self.client.force_login(self.attorney)
        attempts = (
            ("get", "detail", [self.beta.pk]),
            ("get", "detail", [999999]),
            ("get", "documents", [self.beta.pk]),
            ("post", "document_upload", [self.beta.pk]),
            ("get", "document_download", [self.beta.pk, beta_doc.pk]),
            ("get", "document_download", [self.alpha.pk, beta_doc.pk]),
            ("get", "document_download", [self.beta.pk, self.document.pk]),
            ("post", "document_edit", [self.alpha.pk, beta_doc.pk]),
            ("post", "document_edit", [self.beta.pk, beta_doc.pk]),
            ("post", "edit", [self.beta.pk]),
            ("post", "archive", [self.beta.pk]),
            ("post", "task_assign", [self.beta.pk]),
            ("post", "task_reassign", [self.alpha.pk, beta_task.pk]),
            ("post", "task_complete", [self.beta.pk, beta_task.pk]),
            ("post", "task_complete", [self.alpha.pk, beta_task.pk]),
            ("post", "task_status", [self.alpha.pk, beta_task.pk]),
            ("post", "document_archive", [self.alpha.pk, beta_doc.pk]),
        )
        for method, name, ids in attempts:
            with self.subTest(name=name, ids=ids):
                response = getattr(self.client, method)(reverse(f"cases:{name}", args=ids))
                self.assertEqual(response.status_code, 404)
                self.assertNotContains(response, beta_doc.original_filename, status_code=404)
        beta_task.refresh_from_db()
        beta_doc.refresh_from_db()
        self.assertEqual(beta_task.revision, 1)
        self.assertEqual(beta_doc.revision, 1)

    def test_copied_download_and_form_lose_access_on_membership_revocation(self):
        archived = Document.objects.get(case=self.alpha, state=Document.State.ARCHIVED)
        url = reverse("cases:document_download", args=[self.alpha.pk, archived.pk])
        self.client.force_login(self.other_attorney)
        self.assertEqual(self.client.get(url).status_code, 404)

        self.client.force_login(self.staff)
        self.grant(self.staff, Action.MANAGE_DOCUMENTS)
        case_url = reverse("cases:detail", args=[self.alpha.pk])
        self.assertEqual(self.client.get(case_url).status_code, 200)
        edit_url = reverse("cases:document_edit", args=[self.alpha.pk, self.document.pk])
        self.assertEqual(self.client.get(edit_url).status_code, 200)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Fictional LexFlow sample", b"".join(response.streaming_content))
        self.assertIn("attachment;", response.headers["Content-Disposition"])
        self.assertIn("no-store", response.headers["Cache-Control"])
        CaseMembership.objects.filter(case=self.alpha, user=self.staff).update(is_active=False)
        self.assertEqual(self.client.get(case_url).status_code, 404)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(
            self.client.post(edit_url, {"revision": self.document.revision}).status_code, 404
        )
        self.assertEqual(
            self.client.post(
                reverse("cases:document_archive", args=[self.alpha.pk, self.document.pk]),
                {"revision": self.document.revision},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse("cases:task_status", args=[self.alpha.pk, self.task.pk]),
                {"revision": self.task.revision, "status": Task.Status.DONE},
            ).status_code,
            404,
        )
        self.assertEqual(
            set(self.client.get(reverse("cases:index")).context["totals"].values()), {0}
        )
        self.assertEqual(
            self.client.get(
                reverse("cases:client_detail", args=[self.shared_client.pk])
            ).status_code,
            404,
        )

    def test_staff_case_field_allowlist_and_document_grant_apply_on_post(self):
        self.client.force_login(self.staff)
        edit = reverse("cases:edit", args=[self.alpha.pk])
        data = {"revision": self.alpha.revision, "summary": "Updated", "court_docket_number": "D-7"}
        self.assertEqual(self.client.post(edit, {**data, "title": "Forged"}).status_code, 400)
        self.alpha.refresh_from_db()
        self.assertEqual(self.alpha.revision, data["revision"])
        self.assertEqual(self.client.post(edit, data).status_code, 302)
        self.alpha.refresh_from_db()
        self.assertEqual(self.alpha.summary, "Updated")
        self.assertEqual(self.client.post(edit, data).status_code, 409)
        doc = reverse("cases:document_edit", args=[self.alpha.pk, self.document.pk])
        doc_data = {"revision": self.document.revision, "title": "New title", "category": "Other"}
        self.assertEqual(self.client.post(doc, doc_data).status_code, 403)
        self.grant(self.staff, Action.MANAGE_DOCUMENTS)
        self.assertEqual(self.client.post(doc, {**doc_data, "case": self.beta.pk}).status_code, 400)
        self.assertEqual(self.client.post(doc, doc_data).status_code, 302)
        self.staff.user_permissions.clear()
        self.assertEqual(self.client.post(doc, doc_data).status_code, 403)

    def test_creation_requires_grant_and_valid_scoped_client_and_attorney(self):
        self.client.force_login(self.staff)
        create = reverse("cases:create")
        create_client = reverse("cases:client_create")
        client_data = {"name": "New intake", "type": Client.Type.INDIVIDUAL}
        data = {
            "client": self.alpha_client.pk,
            "responsible_attorney": self.attorney.pk,
            "title": "New case",
            "type": Case.Type.CIVIL,
        }
        self.assertEqual(self.client.post(create_client, client_data).status_code, 403)
        self.assertEqual(self.client.post(create, data).status_code, 403)
        self.grant(self.staff, Action.CREATE_RECORDS)
        self.assertEqual(self.client.post(create_client, client_data).status_code, 302)
        self.assertEqual(
            self.client.post(create, {**data, "client": self.beta_client.pk}).status_code, 400
        )
        self.assertEqual(
            self.client.post(
                create, {**data, "responsible_attorney": self.inactive.pk}
            ).status_code,
            400,
        )
        self.assertFalse(Case.objects.filter(title="New case").exists())
        result = self.client.post(create, data)
        case = Case.objects.get(title="New case")
        self.assertRedirects(result, reverse("cases:detail", args=[case.pk]))
        self.assertSetEqual(
            set(case.memberships.filter(is_active=True).values_list("user_id", flat=True)),
            {self.staff.pk, self.attorney.pk},
        )
        self.assertEqual(case.clients.get(), self.alpha_client)

    def test_task_assignment_requires_grant_and_active_same_case_member(self):
        self.client.force_login(self.staff)
        assign = reverse("cases:task_assign", args=[self.alpha.pk])
        data = {
            "title": "New task",
            "priority": "Normal",
            "due_at": timezone.now().isoformat(),
            "assignee": self.staff.pk,
        }
        self.assertEqual(self.client.post(assign, data).status_code, 403)
        self.grant(self.staff, Action.ASSIGN_TASKS)
        for user in (self.other_attorney, self.inactive):
            self.assertEqual(
                self.client.post(assign, {**data, "assignee": user.pk}).status_code, 400
            )
        self.assertEqual(self.client.post(assign, {**data, "case": self.beta.pk}).status_code, 400)
        self.assertFalse(Task.objects.filter(title="New task").exists())
        self.assertEqual(self.client.post(assign, data).status_code, 302)
        task = Task.objects.get(title="New task")
        self.assertEqual(task.assignee, self.staff)
        reassign = reverse("cases:task_reassign", args=[self.alpha.pk, task.pk])
        data = {"revision": task.revision, "assignee": self.other_attorney.pk}
        self.assertEqual(self.client.post(reassign, data).status_code, 400)
        self.assertEqual(
            self.client.post(reassign, {**data, "assignee": self.attorney.pk}).status_code, 302
        )
        task.refresh_from_db()
        self.assertEqual(task.assignee, self.attorney)

    def test_completion_requires_assignment_and_membership_even_for_admin(self):
        url = reverse("cases:task_complete", args=[self.alpha.pk, self.task.pk])
        data = {"revision": self.task.revision}
        self.client.force_login(self.attorney)
        self.assertEqual(self.client.post(url, data).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.post(url, data).status_code, 404)
        CaseMembership.objects.create(case=self.alpha, user=self.admin)
        self.assertEqual(self.client.post(url, data).status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.task.refresh_from_db()
        self.assertEqual(self.task.status, Task.Status.DONE)

    def test_archive_requires_responsibility_or_explicit_administrator_grant(self):
        Case.objects.filter(pk__in=[self.alpha.pk, self.beta.pk]).update(
            status=Case.Status.CLOSED, closed_on=timezone.localdate()
        )
        CaseMembership.objects.create(case=self.alpha, user=self.other_attorney)
        archive = reverse("cases:archive", args=[self.alpha.pk])
        data = {"revision": self.alpha.revision}
        for user in (self.other_attorney, self.staff):
            self.client.force_login(user)
            self.assertEqual(self.client.post(archive, data).status_code, 403)
        self.client.force_login(self.attorney)
        self.assertEqual(self.client.post(archive, data).status_code, 302)
        self.alpha.refresh_from_db()
        self.assertTrue(self.alpha.is_archived)
        self.client.force_login(self.admin)
        CaseMembership.objects.create(case=self.beta, user=self.admin)
        archive = reverse("cases:archive", args=[self.beta.pk])
        data = {"revision": self.beta.revision}
        self.assertEqual(self.client.post(archive, data).status_code, 403)
        self.grant(self.admin, Action.ARCHIVE_CASE)
        self.assertEqual(self.client.post(archive, data).status_code, 302)
        self.beta.refresh_from_db()
        self.assertTrue(self.beta.is_archived)

    def test_django_admin_flags_do_not_grant_downloads_and_role_change_takes_effect(self):
        download = reverse("cases:document_download", args=[self.alpha.pk, self.document.pk])
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(download).status_code, 404)
        membership = CaseMembership.objects.create(case=self.alpha, user=self.admin)
        response = self.client.get(download)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Fictional", b"".join(response.streaming_content))
        membership.update_with_revision(membership.revision, is_active=False)
        self.assertEqual(self.client.get(download).status_code, 404)

        self.client.force_login(self.attorney)
        edit = reverse("cases:document_edit", args=[self.alpha.pk, self.document.pk])
        self.assertEqual(self.client.get(edit).status_code, 200)
        User.objects.filter(pk=self.attorney.pk).update(role=User.Role.STAFF)
        self.assertEqual(self.client.get(edit).status_code, 403)
        response = self.client.get(download)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Fictional", b"".join(response.streaming_content))

    def test_mutations_still_require_csrf(self):
        browser = Browser(enforce_csrf_checks=True)
        browser.force_login(self.staff)
        url = reverse("cases:task_complete", args=[self.alpha.pk, self.task.pk])
        self.assertEqual(browser.post(url, {"revision": self.task.revision}).status_code, 403)
