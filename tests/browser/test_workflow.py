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
