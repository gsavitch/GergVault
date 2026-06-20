from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import resolve

from card_vault.models import GergVaultTrafficEvent


@override_settings(GERGVAULT_TRACK_TRAFFIC=True)
class GergVaultTrafficTrackingTests(TestCase):
    def setUp(self):
        self.client = Client(HTTP_USER_AGENT="GergVault QA Browser", HTTP_CF_CONNECTING_IP="203.0.113.25")

    def test_anonymous_landing_page_tracks_page_view(self):
        response = self.client.get("/", HTTP_REFERER="https://example.com/cards")

        self.assertEqual(response.status_code, 200)
        event = GergVaultTrafficEvent.objects.get(path="/")
        self.assertEqual(event.event_type, GergVaultTrafficEvent.EventType.PAGE_VIEW)
        self.assertIsNone(event.user)
        self.assertEqual(event.method, "GET")
        self.assertEqual(event.status_code, 200)
        self.assertEqual(str(event.ip_address), "203.0.113.25")
        self.assertIn("GergVault QA Browser", event.user_agent)
        self.assertEqual(event.referrer, "https://example.com/cards")

    def test_authenticated_dashboard_tracks_user(self):
        user = get_user_model().objects.create_user(username="traffic-user", password="test-password")
        self.client.force_login(user)

        response = self.client.get("/card-vault/")

        self.assertEqual(response.status_code, 200)
        event = GergVaultTrafficEvent.objects.filter(path="/card-vault/").latest("created_at")
        self.assertEqual(event.user, user)
        self.assertEqual(event.event_type, GergVaultTrafficEvent.EventType.PAGE_VIEW)
        self.assertEqual(event.route_name, "card_vault:dashboard")

    def test_static_media_paths_are_not_tracked(self):
        self.client.get("/static/app.css")
        self.client.get("/media/card_vault/demo.jpg")
        self.client.get("/favicon.ico")

        self.assertFalse(GergVaultTrafficEvent.objects.exists())

    @override_settings(GERGVAULT_TRACK_TRAFFIC=False)
    def test_tracking_can_be_disabled(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(GergVaultTrafficEvent.objects.exists())

    def test_privacy_page_loads_and_mentions_first_party_tracking(self):
        response = self.client.get("/privacy/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("GergVault Privacy", content)
        self.assertIn("first-party operational analytics", content)
        self.assertIn("does not store request bodies", content)

    @override_settings(DEBUG=False, GERGVAULT_SERVE_MEDIA=True)
    def test_media_route_is_available_when_explicitly_enabled(self):
        match = resolve("/media/card_vault/demo.jpg")

        self.assertEqual(match.func.__name__, "serve")
