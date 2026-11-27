from django.test import SimpleTestCase
from django.urls import reverse

from accounts.models import User

from .test_foundation import SeededTestCase


class PublicLandingTests(SimpleTestCase):
    def test_landing_renders_without_database_access(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "landing.html")
        self.assertContains(response, reverse("accounts:login"))
        self.assertContains(response, "lexflow-mark.svg")
        self.assertContains(response, "fictional records")

    def test_landing_accepts_head_and_rejects_post(self):
        self.assertEqual(self.client.head(reverse("home")).status_code, 200)
        self.assertEqual(self.client.post(reverse("home")).status_code, 405)


class LandingEntryTests(SeededTestCase):
    def test_signed_in_visitors_go_to_the_protected_dashboard(self):
        self.client.force_login(User.objects.get(email="attorney.a@example.test"))
        self.assertRedirects(self.client.get(reverse("home")), reverse("cases:dashboard"))

    def test_landing_does_not_make_the_dashboard_public(self):
        response = self.client.get(reverse("cases:dashboard"))
        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('cases:dashboard')}",
        )
