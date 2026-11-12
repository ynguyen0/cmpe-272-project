from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from playwright.sync_api import expect, sync_playwright


class WireframeTests(StaticLiveServerTestCase):
    databases = set()

    def test_client_to_completed_task_on_mobile(self):
        with sync_playwright() as playwright, playwright.chromium.launch() as browser:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(f"{self.live_server_url}/wireframe/")
            page.get_by_role("link", name="Open wireframe").click()
            page.get_by_role("button", name="Continue").click()
            expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()
            page.get_by_role("link", name="Clients", exact=True).click()
            page.get_by_role("link", name="New client").click()
            page.get_by_role("button", name="Save client").click()
            expect(page.locator("[data-errors]")).to_be_focused()

            page.get_by_label("Client name").fill("Fictional West Studio")
            page.get_by_role("link", name="Cases", exact=True).click()
            expect(page.get_by_role("dialog")).to_be_visible()
            expect(page.get_by_role("button", name="Keep editing")).to_be_focused()
            page.keyboard.press("Escape")
            expect(page.get_by_label("Client name")).to_have_value("Fictional West Studio")
            page.get_by_label("Client type").select_option("Organization")
            page.get_by_role("button", name="Save client").click()

            page.get_by_role("link", name="Edit client").click()
            page.get_by_label("Email").fill("west@example.test")
            page.get_by_role("button", name="Save client").click()
            expect(page.get_by_text("west@example.test")).to_be_visible()
            page.get_by_role("link", name="Open case for this client").click()
            expect(page.get_by_label("Client (required)", exact=True)).to_have_value("client-1")
            page.get_by_label("Case title").fill("Fictional contract review")
            page.get_by_role("button", name="Open case", exact=True).click()

            page.get_by_role("link", name="Documents", exact=True).click()
            page.get_by_role("link", name="Upload document").click()
            page.get_by_label("Document title").fill("Draft agreement")
            file_input = page.get_by_label("Choose file")
            file_input.set_input_files(
                {"name": "draft.exe", "mimeType": "application/octet-stream", "buffer": b"demo"}
            )
            page.get_by_role("button", name="Save document").click()
            expect(page.locator("#field-file-error")).to_contain_text("Choose a supported file")
            file_input.set_input_files(
                {"name": "draft.txt", "mimeType": "text/plain", "buffer": b"fictional draft"}
            )
            page.get_by_role("button", name="Save document").click()
            expect(page.get_by_role("cell", name="draft.txt")).to_be_visible()

            page.get_by_role("link", name="Archive", exact=True).click()
            page.get_by_label("Archive reason").fill("Superseded draft")
            page.get_by_role("button", name="Archive document").click()
            expect(page.get_by_role("cell", name="draft.txt")).to_have_count(0)
            page.get_by_label("Include archived").check()
            page.get_by_role("button", name="Apply filters").click()
            expect(page.get_by_role("cell", name="Archived. Superseded draft")).to_be_visible()

            page.get_by_role("link", name="Tasks", exact=True).click()
            page.get_by_role("link", name="Assign task").click()
            page.get_by_label("Task title").fill("Confirm next steps")
            page.get_by_role("button", name="Assign task").click()
            page.get_by_role("link", name="My tasks", exact=True).click()
            page.get_by_role("button", name="Complete", exact=True).click()
            page.get_by_role("button", name="Mark done").click()
            expect(page.get_by_role("cell", name="Done", exact=True)).to_be_visible()
            self.assertTrue(
                page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            )

    def test_recovery_preview_and_restricted_routes(self):
        with sync_playwright() as playwright, playwright.chromium.launch() as browser:
            page = browser.new_page()
            url = f"{self.live_server_url}/wireframe/"
            page.goto(url + "#/login")
            page.get_by_role("link", name="Forgot your password?").click()
            page.get_by_label("Work email").fill("sample@example.test")
            page.get_by_role("button", name="Request reset link").click()
            expect(page.get_by_role("heading", name="Check your email")).to_be_visible()
            page.get_by_role("link", name="Preview reset link").click()
            page.get_by_label("New password", exact=False).first.fill("fictional-password")
            page.get_by_label("Confirm new password").fill("different-password")
            page.get_by_role("button", name="Reset password").click()
            expect(page.locator("#field-repeat-error")).to_have_text("The passwords must match.")
            page.get_by_label("Confirm new password").fill("fictional-password")
            page.get_by_role("button", name="Reset password").click()
            expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
            page.get_by_label("Demo account").select_option("eli")
            page.get_by_role("button", name="Continue").click()
            expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()
            page.evaluate("location.hash = '#/admin/audit'")
            expect(page.get_by_role("heading", name="Permission denied")).to_be_visible()
            page.evaluate("location.hash = '#/cases/beta/overview'")
            expect(page.get_by_role("heading", name="Record unavailable")).to_be_visible()
            page.get_by_text("Wireframe preview controls").click()
            page.get_by_role("button", name="Preview error").click()
            expect(page.get_by_role("alert")).to_contain_text("The request failed")
            page.get_by_role("button", name="Try again").click()
            expect(page.get_by_role("heading", name="Record unavailable")).to_be_visible()
