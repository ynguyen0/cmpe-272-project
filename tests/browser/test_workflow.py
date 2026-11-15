import os
from io import StringIO
from unittest.mock import patch

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.management import call_command
from playwright.sync_api import expect, sync_playwright

from cases.models import Case


class SignInWorkflowTests(StaticLiveServerTestCase):
    def test_login_case_boundary_and_logout_in_browser(self):
        password = "Fictional-browser-passphrase-73!"
        with patch.dict(os.environ, {"LEXFLOW_DEMO_PASSWORD": password}):
            call_command("seed_demo", stdout=StringIO())
        beta = Case.objects.get(number="DEMO-BETA")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(self.live_server_url)
            page.get_by_label("Email", exact=True).fill("attorney.a@example.test")
            page.get_by_label("Password", exact=True).fill("wrong-password")
            page.get_by_role("button", name="Sign in", exact=True).click()
            expect(page.get_by_role("alert")).to_be_visible()
            page.get_by_label("Password", exact=True).fill(password)
            page.get_by_role("button", name="Sign in", exact=True).click()
            expect(page.get_by_role("heading", name="My cases", exact=True)).to_be_visible()
            expect(page.get_by_text("Fictional Alpha matter", exact=True)).to_be_visible()
            expect(page.get_by_text("Fictional Beta matter", exact=True)).to_have_count(0)
            # Prove the vendored stylesheet is actually served and applied.
            self.assertEqual(
                page.locator(".navbar").evaluate("element => getComputedStyle(element).display"),
                "flex",
            )
            page.get_by_role("link", name="DEMO-ALPHA", exact=True).click()
            expect(page.get_by_role("heading", name="Fictional Alpha matter")).to_be_visible()
            denied = page.goto(f"{self.live_server_url}/cases/{beta.pk}/")
            self.assertEqual(denied.status, 404)
            page.goto(self.live_server_url)
            page.get_by_role("button", name="Sign out", exact=True).click()
            expect(page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
            page.goto(self.live_server_url)
            expect(page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
            browser.close()


class ClientWorkflowTests(StaticLiveServerTestCase):
    def test_create_find_edit_link_and_archive_in_browser(self):
        password = "Fictional-browser-passphrase-73!"
        with patch.dict(os.environ, {"LEXFLOW_DEMO_PASSWORD": password}):
            call_command("seed_demo", stdout=StringIO())
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(self.live_server_url)
            page.get_by_label("Email", exact=True).fill("attorney.a@example.test")
            page.get_by_label("Password", exact=True).fill(password)
            page.get_by_role("button", name="Sign in", exact=True).click()
            page.get_by_role("link", name="Clients", exact=True).click()
            page.get_by_role("link", name="Create client", exact=True).click()
            name = "Fictional Elm Workshop"
            page.get_by_label("Name", exact=True).fill(name)
            page.get_by_label("Type", exact=True).select_option("Organization")
            page.get_by_label("Email", exact=True).fill("Elm@Example.Test")
            page.get_by_role("button", name="Create client", exact=True).click()
            expect(page.get_by_role("heading", name=name)).to_be_visible()
            page.get_by_role("link", name="Back to clients").click()
            page.get_by_label("Search clients").fill("ELM@EXAMPLE.TEST")
            page.get_by_role("button", name="Search", exact=True).click()
            page.get_by_role("link", name=name, exact=True).click()
            page.get_by_role("link", name="Edit client details").click()
            page.get_by_label("Phone", exact=True).fill("+1 (202) 555-0142")
            page.get_by_role("button", name="Save client details").click()
            expect(page.get_by_text("+12025550142", exact=True)).to_be_visible()
            page.get_by_role("link", name="Back to clients").click()
            page.get_by_role("link", name="Back to cases").click()
            page.get_by_role("link", name="DEMO-ALPHA", exact=True).click()
            page.get_by_role("link", name="Link client", exact=True).click()
            page.get_by_label("Client", exact=True).select_option(
                label=page.get_by_role("option", name=name).inner_text()
            )
            page.get_by_role("button", name="Link client", exact=True).click()
            page.get_by_role("link", name=name, exact=True).click()
            expect(page.get_by_role("link", name="DEMO-ALPHA")).to_be_visible()
            page.get_by_role("link", name="Archive client", exact=True).click()
            page.get_by_role("button", name="Archive client", exact=True).click()
            expect(page.get_by_text("Archived", exact=True)).to_be_visible()
            expect(page.get_by_role("link", name="DEMO-ALPHA")).to_be_visible()
            browser.close()


class CaseWorkflowTests(StaticLiveServerTestCase):
    def test_create_assign_team_and_close_in_browser(self):
        password = "Fictional-browser-passphrase-73!"
        with patch.dict(os.environ, {"LEXFLOW_DEMO_PASSWORD": password}):
            call_command("seed_demo", stdout=StringIO())

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(self.live_server_url)
            page.get_by_label("Email", exact=True).fill("attorney.a@example.test")
            page.get_by_label("Password", exact=True).fill(password)
            page.get_by_role("button", name="Sign in", exact=True).click()
            page.get_by_role("link", name="Create case").click()
            title = "Fictional Observatory matter"
            page.get_by_label("Title", exact=True).fill(title)
            page.get_by_label("Description", exact=True).fill("Fictional case description")
            client = page.get_by_role("option", name="Fictional Avery Lane").inner_text()
            page.get_by_label("Client", exact=True).select_option(label=client)
            page.get_by_role("button", name="Create case", exact=True).click()
            expect(page.get_by_role("heading", name=title)).to_be_visible()
            page.get_by_role("link", name="Edit case team").click()
            page.get_by_label("Staff A", exact=True).check()
            page.get_by_role("button", name="Save case team").click()
            expect(page.get_by_text("Staff A · Support")).to_be_visible()
            for status in ("In progress", "On hold", "Closed"):
                page.get_by_role("link", name="Update case status").click()
                page.get_by_label("New status").select_option(value=status)
                page.get_by_role("button", name="Update case status").click()
                expect(page.locator("dd").filter(has_text=status)).to_be_visible()
            expect(page.get_by_role("link", name="Fictional Avery Lane")).to_be_visible()
            expect(page.get_by_text("Fictional case description")).to_be_visible()
            expect(page.get_by_role("link", name="Reopen case")).to_be_visible()
            browser.close()
