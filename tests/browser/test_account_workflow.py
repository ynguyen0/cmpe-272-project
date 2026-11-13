import re
from urllib.parse import urlsplit

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core import mail
from playwright.sync_api import expect, sync_playwright

from accounts.models import User


class AccountBrowserTests(StaticLiveServerTestCase):
    def test_administrator_creates_account_and_user_recovers_password(self):
        password = "Fictional-browser-passphrase-73!"
        new_password = "Fictional-recovery-passphrase-41!"
        email = "colleague@example.test"
        User.objects.create_superuser("admin@example.test", password, full_name="Administrator")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            admin = browser.new_page()
            admin.goto(self.live_server_url)
            admin.get_by_label("Email", exact=True).fill("admin@example.test")
            admin.get_by_label("Password", exact=True).fill(password)
            admin.get_by_role("button", name="Sign in", exact=True).click()
            admin.get_by_role("link", name="Accounts", exact=True).click()
            admin.get_by_role("link", name="Create account", exact=True).click()
            admin.get_by_label("Full name").fill("Colleague")
            admin.get_by_label("Email", exact=True).fill(email)
            admin.get_by_label("Role").select_option("Staff")
            admin.get_by_label("Password", exact=True).fill(password)
            admin.get_by_label("Password confirmation", exact=True).fill(password)
            admin.get_by_role("button", name="Create account").click()
            expect(admin.get_by_role("row", name=re.compile(email))).to_contain_text("Active")

            colleague = browser.new_page()
            colleague.goto(self.live_server_url)
            colleague.get_by_role("link", name="Forgot your password?").click()
            colleague.get_by_label("Email").fill(email)
            colleague.get_by_role("button", name="Send reset link").click()
            expect(colleague.get_by_role("heading", name="Check your email")).to_be_visible()
            link = re.search(r"https?://\S+", mail.outbox[-1].body)[0]
            colleague.goto(self.live_server_url + urlsplit(link).path)
            colleague.get_by_label("New password", exact=True).fill(new_password)
            colleague.get_by_label("New password confirmation", exact=True).fill(new_password)
            colleague.get_by_role("button", name="Reset password").click()
            colleague.get_by_role("link", name="Sign in with your new password").click()
            colleague.get_by_label("Email", exact=True).fill(email)
            colleague.get_by_label("Password", exact=True).fill(new_password)
            colleague.get_by_role("button", name="Sign in", exact=True).click()
            expect(colleague.get_by_role("heading", name="My cases")).to_be_visible()

            admin.get_by_role("link", name="Edit access for Colleague").click()
            admin.get_by_label("Status").select_option("inactive")
            admin.get_by_role("button", name="Save changes").click()
            expect(admin.get_by_role("row", name=re.compile(email))).to_contain_text("Deactivated")
            colleague.reload()
            expect(colleague.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
            browser.close()
