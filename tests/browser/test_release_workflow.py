"""DEL-01: integrated work, deadline, dashboard, and audit acceptance journeys."""

import os
from datetime import timedelta
from io import StringIO
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth.models import Permission
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from playwright.sync_api import expect, sync_playwright

from accounts.models import User
from cases.models import Case
from work.models import Deadline, Task

PASSWORD = "Fictional-browser-passphrase-73!"


class ReleaseWorkflowTests(StaticLiveServerTestCase):
    def setUp(self):
        with patch.dict(os.environ, {"LEXFLOW_DEMO_PASSWORD": PASSWORD}):
            call_command("seed_demo", stdout=StringIO())

    def sign_in(self, page, email):
        page.goto(self.live_server_url)
        page.get_by_label("Email", exact=True).fill(email)
        # Exercise sequential keyboard focus and submit without using a mouse.
        page.get_by_label("Email", exact=True).focus()
        page.keyboard.press("Tab")
        expect(page.get_by_label("Password", exact=True)).to_be_focused()
        page.keyboard.type(PASSWORD)
        page.keyboard.press("Enter")
        expect(page.get_by_role("heading", name="Dashboard", exact=True)).to_be_visible()
        self.assert_fits(page)
        page.get_by_role("link", name="Cases", exact=True).click()
        expect(page.get_by_role("heading", name="My cases", exact=True)).to_be_visible()

    def assert_fits(self, page):
        self.assertTrue(
            page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
            )
        )

    def test_intake_case_upload_assignment_completion_and_revocation(self):
        staff_pk = User.objects.get(email="staff.a@example.test").pk
        attorney_pk = User.objects.get(email="attorney.a@example.test").pk
        due_value = (timezone.localtime() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            attorney = browser.new_page(viewport={"width": 390, "height": 844})
            staff = browser.new_page(viewport={"width": 390, "height": 844})
            self.sign_in(attorney, "attorney.a@example.test")
            attorney.get_by_role("link", name="Clients", exact=True).click()
            attorney.get_by_role("link", name="Create client", exact=True).click()
            attorney.get_by_label("Name", exact=True).fill("Fictional Integrated Intake")
            attorney.get_by_label("Type", exact=True).select_option("Individual")
            attorney.get_by_label("Phone", exact=True).fill("invalid phone")
            attorney.get_by_role("button", name="Create client", exact=True).click()
            expect(attorney.get_by_text("Enter 7 to 15 digits", exact=False)).to_be_visible()
            expect(attorney.get_by_label("Name", exact=True)).to_have_value(
                "Fictional Integrated Intake"
            )
            attorney.get_by_label("Phone", exact=True).fill("2025550199")
            attorney.get_by_role("button", name="Create client", exact=True).click()
            expect(
                attorney.get_by_role("heading", name="Fictional Integrated Intake")
            ).to_be_visible()
            contact_pk = urlsplit(attorney.url).path.rstrip("/").split("/")[-1]
            attorney.goto(self.live_server_url + reverse("cases:create"))
            attorney.get_by_label("Title", exact=True).fill("Fictional Integrated Matter")
            attorney.get_by_label("Client", exact=True).select_option(contact_pk)
            attorney.get_by_label("Staff A", exact=True).check()
            attorney.get_by_role("button", name="Create case", exact=True).click()
            expect(
                attorney.get_by_role("heading", name="Fictional Integrated Matter")
            ).to_be_visible()
            case_url = attorney.url
            expect(attorney.get_by_text("No tasks.", exact=True)).to_be_visible()
            expect(attorney.get_by_text("No deadlines.", exact=True)).to_be_visible()
            self.assert_fits(attorney)
            attorney.get_by_role("link", name="Upload document", exact=True).click()
            attorney.get_by_label("Title", exact=True).fill("Fictional Integrated Evidence")
            attorney.get_by_label("Category", exact=True).select_option("Evidence")
            content = b"Fictional isolated integration evidence."
            attorney.get_by_label("File", exact=True).set_input_files(
                {"name": "integration.txt", "mimeType": "text/plain", "buffer": content}
            )
            attorney.get_by_role("button", name="Upload document", exact=True).click()
            download_link = attorney.get_by_role(
                "link", name="Download Fictional Integrated Evidence"
            )
            download_url = self.live_server_url + download_link.get_attribute("href")
            with attorney.expect_download() as pending:
                attorney.get_by_role("link", name="Download Fictional Integrated Evidence").click()
            self.assertEqual(pending.value.path().read_bytes(), content)
            attorney.goto(case_url)
            attorney.get_by_role("link", name="Assign task", exact=True).click()
            attorney.get_by_label("Title", exact=True).fill("Fictional Integrated Review")
            attorney.get_by_label("Assignee", exact=True).select_option(str(staff_pk))
            attorney.get_by_label("Priority", exact=True).select_option("Normal")
            attorney.get_by_label("Due at", exact=True).fill("2026-03-08T02:30")
            attorney.get_by_role("button", name="Assign task", exact=True).click()
            expect(attorney.locator(".errorlist")).to_be_visible()
            attorney.get_by_label("Due at", exact=True).fill(due_value)
            attorney.get_by_role("button", name="Assign task", exact=True).click()
            expect(attorney.get_by_text("Fictional Integrated Review", exact=False)).to_be_visible()
            attorney.get_by_role("link", name="Edit task", exact=True).click()
            attorney.get_by_label("Description", exact=True).fill("Synthetic task details edited")
            attorney.get_by_role("button", name="Edit task", exact=True).click()
            attorney.get_by_role("link", name="Add deadline", exact=True).click()
            attorney.get_by_label("Title", exact=True).fill("Fictional Integrated Filing")
            attorney.get_by_label("Type", exact=True).select_option("Filing")
            attorney.get_by_label("Due at", exact=True).fill(due_value)
            attorney.get_by_label("Responsible user", exact=True).select_option(str(attorney_pk))
            attorney.get_by_role("button", name="Add deadline", exact=True).click()
            expect(
                attorney.get_by_text("Fictional Integrated Filing", exact=False)
            ).to_contain_text("Pending")
            attorney.get_by_role("link", name="Dashboard", exact=True).click()
            deadline_card = attorney.locator('section[aria-labelledby="card-upcoming_deadlines"]')
            expect(deadline_card).to_contain_text("Fictional Integrated Filing")
            attorney.goto(case_url)
            self.sign_in(staff, "staff.a@example.test")
            staff.get_by_role("link", name="Dashboard", exact=True).click()
            task_card = staff.locator('section[aria-labelledby="card-upcoming_tasks"]')
            expect(task_card).to_contain_text("Fictional Integrated Review")
            staff.goto(case_url)
            expect(staff.get_by_role("link", name="Assign task", exact=True)).to_have_count(0)
            for target in ("In progress", "Done", "To do", "Done"):
                staff.get_by_role("link", name="Change status", exact=True).click()
                staff.get_by_label("Status", exact=True).select_option(target)
                staff.get_by_role("button", name="Change task status", exact=True).click()
                expect(
                    staff.get_by_text("Fictional Integrated Review", exact=False)
                ).to_contain_text(target)
            expect(staff.get_by_text("Fictional Integrated Review", exact=False)).to_contain_text(
                "Done"
            )
            self.assert_fits(staff)
            staff.get_by_role("link", name="Dashboard", exact=True).click()
            expect(task_card).not_to_contain_text("Fictional Integrated Review")
            # Pending deadlines block closure until explicitly resolved.
            attorney.goto(case_url)
            attorney.get_by_role("link", name="Update case status").click()
            attorney.get_by_label("New status").select_option("Closed")
            attorney.get_by_role("button", name="Update case status", exact=True).click()
            expect(
                attorney.get_by_text("Resolve these tasks and deadlines before closing the case.")
            ).to_be_visible()
            attorney.get_by_role("link", name="Return to current case").click()
            attorney.get_by_role("link", name="Edit deadline", exact=True).click()
            attorney.get_by_label("Notes", exact=True).fill("Synthetic deadline details edited")
            attorney.get_by_role("button", name="Edit deadline", exact=True).click()
            attorney.get_by_role("link", name="Resolve", exact=True).click()
            attorney.get_by_label("Status", exact=True).select_option("Completed")
            attorney.get_by_label("Reason", exact=True).fill("Synthetic filing completed")
            attorney.get_by_role("button", name="Resolve deadline", exact=True).click()
            expect(
                attorney.get_by_text("Fictional Integrated Filing", exact=False)
            ).to_contain_text("Completed")
            attorney.get_by_role("link", name="Dashboard", exact=True).click()
            expect(deadline_card).not_to_contain_text("Fictional Integrated Filing")
            attorney.goto(case_url)
            attorney.get_by_role("link", name="Reopen", exact=True).click()
            attorney.get_by_role("button", name="Reopen deadline", exact=True).click()
            expect(
                attorney.get_by_text("Fictional Integrated Filing", exact=False)
            ).to_contain_text("Pending")
            attorney.get_by_role("link", name="Resolve", exact=True).click()
            attorney.get_by_label("Status", exact=True).select_option("Cancelled")
            attorney.get_by_label("Reason", exact=True).fill(
                "Synthetic cancellation after reopening"
            )
            attorney.get_by_role("button", name="Resolve deadline", exact=True).click()
            expect(
                attorney.get_by_text("Fictional Integrated Filing", exact=False)
            ).to_contain_text("Cancelled")
            # A copied private URL must stop working on the very next request.
            attorney.goto(case_url)
            attorney.get_by_role("link", name="Edit case team").click()
            attorney.get_by_label("Staff A", exact=True).uncheck()
            attorney.get_by_role("button", name="Save case team").click()
            expect(attorney.get_by_text("Staff A · Support", exact=True)).to_have_count(0)
            self.assertEqual(staff.goto(case_url).status, 404)
            self.assertEqual(staff.goto(download_url).status, 404)
            self.assertNotIn("Fictional Integrated Matter", staff.locator("body").inner_text())
            attorney.goto(case_url)
            attorney.get_by_role("link", name="Update case status").click()
            attorney.get_by_label("New status").select_option("Closed")
            attorney.get_by_role("button", name="Update case status", exact=True).click()
            expect(attorney.get_by_role("link", name="Reopen case")).to_be_visible()
            attorney.get_by_role("button", name="Sign out", exact=True).click()
            attorney.goto(case_url)
            expect(attorney.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
            browser.close()
        task = Task.objects.get(case__title="Fictional Integrated Matter")
        self.assertEqual(task.status, Task.Status.DONE)
        self.assertIsNotNone(task.completed_at)
        self.assertEqual(task.description, "Synthetic task details edited")
        deadline = Deadline.objects.get(case=task.case)
        self.assertEqual(deadline.status, Deadline.Status.CANCELLED)
        self.assertIsNotNone(deadline.completed_at)
        self.assertEqual(deadline.completed_by_id, attorney_pk)
        self.assertEqual(deadline.notes, "Synthetic deadline details edited")

    def test_each_role_has_scoped_empty_states_and_readable_access_denial(self):
        case = Case.objects.get(number="DEMO-ALPHA")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            for email in ("admin@example.test", "attorney.b@example.test", "staff.a@example.test"):
                with self.subTest(role=email):
                    page = browser.new_page(viewport={"width": 320, "height": 740})
                    self.sign_in(page, email)
                    if email.startswith("admin"):
                        expect(page.get_by_text("No matching cases.", exact=True)).to_be_visible()
                        page.get_by_role("link", name="Accounts", exact=True).click()
                        expect(
                            page.get_by_role("heading", name="Accounts", exact=True)
                        ).to_be_visible()
                    else:
                        self.assertEqual(
                            page.goto(self.live_server_url + reverse("accounts:list")).status, 403
                        )
                        expect(page.get_by_role("heading", name="Access denied")).to_be_visible()
                        expect(page.get_by_role("link", name="Return to my cases")).to_be_visible()
                    status = page.goto(
                        self.live_server_url + reverse("cases:detail", args=[case.pk])
                    ).status
                    self.assertEqual(status, 200 if email.startswith("staff") else 404)
                    self.assert_fits(page)
                    page.close()
            browser.close()

    def test_administrator_filters_audit_and_rejects_invalid_range(self):
        admin = User.objects.get(email="admin@example.test")
        admin.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="cases", codename="view_organization_audit"
            )
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            self.sign_in(page, admin.email)
            page.goto(self.live_server_url + reverse("cases:audit"))
            page.get_by_label("Actor").select_option(str(admin.pk))
            page.get_by_label("Action").select_option("demo.seed")
            page.get_by_label("Record type").select_option("demo")
            page.get_by_label("Record ID").fill("baseline")
            page.get_by_role("button", name="Filter", exact=True).click()
            rows = page.locator("tbody tr")
            expect(rows).to_have_count(1)
            expect(rows).to_contain_text("demo.seed")
            expect(rows).not_to_contain_text("auth.login")
            self.assert_fits(page)
            page.get_by_label("From (UTC)").fill("2026-11-25")
            page.get_by_label("To (UTC)").fill("2026-11-24")
            page.get_by_role("button", name="Filter", exact=True).click()
            expect(
                page.get_by_text("The start date must be on or before the end date.")
            ).to_be_visible()
            expect(page.locator("tbody")).to_have_count(0)
            browser.close()
