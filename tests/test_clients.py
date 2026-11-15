from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from cases.models import Case, CaseClient, CaseMembership
from clients.models import Client

from .test_foundation import SeededTestCase


class ClientManagementTests(SeededTestCase):
    def setUp(self):
        self.attorney = User.objects.get(email="attorney.a@example.test")
        self.staff = User.objects.get(email="staff.a@example.test")
        self.alpha = Case.objects.get(number="DEMO-ALPHA")
        self.beta = Case.objects.get(number="DEMO-BETA")
        self.intake = Client.objects.get(email="client.unlinked.a@example.test")
        self.hidden = Client.objects.get(email="client.beta@example.test")
        self.client.force_login(self.attorney)

    def test_contact_validation_normalization_and_revision(self):
        url = reverse("cases:client_create")
        data = {
            "name": "  Fictional Violet Co. ",
            "type": Client.Type.ORGANIZATION,
            "email": "  VIOLET@EXAMPLE.TEST  ",
            "phone": " +1 (202) 555-0140 ",
        }
        for invalid in (
            {"name": " "},
            {"type": "Unknown"},
            {"email": "invalid"},
            {"phone": "1-800-BAD-NUM"},
            {"address": "a" * 501},
            {"status": Client.Status.ARCHIVED},
        ):
            self.assertEqual(self.client.post(url, data | invalid).status_code, 400)
        self.assertFalse(Client.objects.filter(email="violet@example.test").exists())

        self.assertEqual(self.client.post(url, data).status_code, 302)
        client = Client.objects.get(email="violet@example.test")
        self.assertEqual((client.name, client.phone), ("Fictional Violet Co.", "+12025550140"))
        detail = reverse("cases:client_detail", args=[client.pk])
        edit = reverse("cases:client_edit", args=[client.pk])
        self.assertContains(self.client.get(detail), "violet@example.test")
        self.assertEqual(self.client.get(edit).context["form"]["revision"].value(), client.revision)
        changes = {
            "name": client.name,
            "type": client.type,
            "email": "",
            "phone": "202-555-0141",
            "address": "Fictional address",
            "notes": "Fictional notes",
            "revision": client.revision,
        }
        self.assertRedirects(self.client.post(edit, changes), detail)
        self.assertContains(self.client.post(edit, changes), "Reload", status_code=409)
        client.refresh_from_db()
        self.assertEqual(
            (client.email, client.phone, client.created_by), ("", "2025550141", self.attorney)
        )
        events = AuditEvent.objects.filter(resource_type="client", resource_id=str(client.pk))
        self.assertSetEqual(
            set(events.values_list("action", flat=True)),
            {"client.create", "client.view", "client.edit"},
        )
        self.assertCountEqual(
            events.get(action="client.edit").changed_fields, ["email", "phone", "address", "notes"]
        )

    def test_duplicate_warnings_use_visible_records_and_allow_confirmation(self):
        url = reverse("cases:client_create")
        data = {"type": Client.Type.INDIVIDUAL, "name": "Fictional Averi Lane"}
        self.assertContains(self.client.post(url, data), "Fictional Avery Lane")
        self.assertFalse(Client.objects.filter(name=data["name"]).exists())
        contact = data | {"name": "Fictional New Name", "phone": "+1 (202) 555-0101"}
        self.assertContains(self.client.post(url, contact), "Possible duplicates")
        self.assertEqual(
            self.client.post(url, contact | {"confirm_duplicate": "on"}).status_code, 302
        )
        response = self.client.post(
            url, data | {"name": self.hidden.name, "email": self.hidden.email}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Client.objects.filter(email=self.hidden.email).count(), 2)

    def test_search_pagination_contact_scope_and_intake_visibility(self):
        url = reverse("cases:clients")
        visible = Client.objects.get(email="client.alpha@example.test")
        for term in ("avery", "CLIENT.ALPHA@EXAMPLE.TEST", "(202) 555-0101", str(visible.pk)):
            self.assertContains(self.client.get(url, {"q": term}), visible.name)
        for term in (self.hidden.name, self.hidden.email, "(202) 555-0102"):
            self.assertContains(self.client.get(url, {"q": term}), "No matching clients.")
        for params in ({"page": -1}, {"page": 2}, {"q": "a" * 151}, {"status": "Other"}):
            self.assertEqual(self.client.get(url, params).status_code, 400)
        Client.objects.bulk_create(
            Client(
                name=f"Fictional Page {i:02}", type=Client.Type.INDIVIDUAL, created_by=self.attorney
            )
            for i in range(26)
        )
        self.assertEqual(len(self.client.get(url, {"q": "Fictional Page"}).context["page"]), 25)
        self.assertEqual(
            len(self.client.get(url, {"q": "Fictional Page", "page": 2}).context["page"]), 1
        )
        self.assertTrue(AuditEvent.objects.filter(action="client.search", resource_id="").exists())
        for email in ("staff.a@example.test", "admin@example.test", "attorney.b@example.test"):
            self.client.force_login(User.objects.get(email=email))
            self.assertNotContains(self.client.get(url), self.intake.name)
            for name in ("client_detail", "client_edit", "client_archive"):
                self.assertEqual(
                    self.client.get(reverse(f"cases:{name}", args=[self.intake.pk])).status_code,
                    404,
                )

    def test_case_link_scope_and_archive_preserve_history(self):
        link_url = reverse("cases:link_client", args=[self.alpha.pk])
        archive_url = reverse("cases:client_archive", args=[self.intake.pk])
        detail = reverse("cases:client_detail", args=[self.intake.pk])
        data = {"client": self.intake.pk}
        self.assertEqual(
            self.client.post(reverse("cases:link_client", args=[self.beta.pk]), data).status_code,
            404,
        )
        self.assertEqual(self.client.post(link_url, {"client": self.hidden.pk}).status_code, 400)
        self.assertEqual(self.client.post(link_url, data).status_code, 302)
        self.assertEqual(self.client.post(link_url, data).status_code, 400)
        self.assertContains(self.client.get(detail), self.alpha.title)
        link = CaseClient.objects.get(case=self.alpha, client=self.intake)
        self.assertTrue(
            AuditEvent.objects.filter(action="case.client.link", resource_id=str(link.pk)).exists()
        )

        self.client.force_login(self.staff)
        self.assertContains(self.client.get(detail), self.alpha.title)
        self.assertEqual(
            self.client.post(archive_url, {"revision": self.intake.revision}).status_code, 403
        )
        self.assertEqual(self.client.post(link_url, data).status_code, 403)

        self.client.force_login(self.attorney)
        self.assertRedirects(
            self.client.post(archive_url, {"revision": self.intake.revision}), detail
        )
        self.assertEqual(
            self.client.post(archive_url, {"revision": self.intake.revision}).status_code, 409
        )
        self.assertTrue(
            AuditEvent.objects.filter(
                action="client.archive", resource_id=str(self.intake.pk)
            ).exists()
        )
        link.refresh_from_db()
        self.assertTrue(link.is_active)
        list_url = reverse("cases:clients")
        self.assertNotContains(self.client.get(list_url), self.intake.name)
        self.assertContains(self.client.get(list_url, {"status": "Archived"}), self.intake.name)
        self.assertContains(self.client.get(detail), self.alpha.title)
        self.assertNotIn(
            self.intake,
            self.client.get(reverse("cases:create")).context["form"].fields["client"].queryset,
        )

        CaseMembership.objects.filter(case=self.alpha, user=self.attorney).update(is_active=False)
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertEqual(
            self.client.post(archive_url, {"revision": self.intake.revision}).status_code, 404
        )

    def test_closed_case_cannot_accept_client_links(self):
        self.alpha.update_with_revision(
            self.alpha.revision, status=Case.Status.CLOSED, closed_on=timezone.localdate()
        )
        response = self.client.post(
            reverse("cases:link_client", args=[self.alpha.pk]), {"client": self.intake.pk}
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(CaseClient.objects.filter(client=self.intake).exists())
