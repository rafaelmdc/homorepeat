from django.test import Client, TestCase
from django.urls import reverse


class RouteSmokeTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_home_page_renders(self):
        response = self.client.get(reverse("core:home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/home.html")
        self.assertContains(response, "Explore homorepeat runs in a cleaner browser, not a directory tree.")

    def test_browser_placeholder_renders(self):
        response = self.client.get(reverse("browser:home"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "browser/home.html")
        self.assertContains(response, "Canonical entity browser with imported runs kept available as provenance.")

    def test_imports_home_redirects_anonymous_users_to_login(self):
        response = self.client.get(reverse("imports:home"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response["Location"])

    def test_healthcheck_returns_json(self):
        response = self.client.get(reverse("core:healthcheck"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "app": "homorepeat-web"})
