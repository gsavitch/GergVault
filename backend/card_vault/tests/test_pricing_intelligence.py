from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase

from card_vault.models import CardVaultCard, CardVaultComp, CardVaultIntakeSession, CardVaultValuationRun
from card_vault.services.pricing.confidence import robust_range
from card_vault.services.pricing.engine import calculate_pricing, provider_readiness, update_card_pricing
from card_vault.services.pricing.normalization import comp_match_flags, normalized_card


def card_stub(**overrides):
    data = {
        "id": 1,
        "player_name": "Maya Moore",
        "team": "Minnesota Lynx",
        "sport": "basketball",
        "league": "WNBA",
        "year": "2025",
        "brand": "Panini",
        "product": "Prizm WNBA",
        "set_name": "2025 Panini Prizm WNBA",
        "card_number": "135",
        "parallel_name": "",
        "insert_name": "",
        "serial_number": "",
        "serial_total": "",
        "rookie_status": False,
        "autograph_detected": False,
        "relic_detected": False,
        "patch_detected": False,
        "estimated_raw_value": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


class PricingIntelligencePureTests(SimpleTestCase):
    def test_normalized_query_generation(self):
        norm = normalized_card(card_stub())

        self.assertIn("2025 Panini Prizm WNBA", norm.key)
        self.assertIn("Maya Moore", norm.key)
        self.assertIn("#135", norm.key)
        self.assertTrue(any("sold" in query for query in norm.variants))
        self.assertTrue(any("PSA 10" in query for query in norm.variants))

    def test_comp_match_scoring(self):
        flags = comp_match_flags(card_stub(), "2025 Panini Prizm WNBA Maya Moore #135 sold", "$8.50")

        self.assertTrue(flags["player_match"])
        self.assertTrue(flags["year_match"])
        self.assertTrue(flags["card_number_match"])
        self.assertGreater(flags["card_match_score"], 0.7)

    def test_wrong_player_exclusion(self):
        flags = comp_match_flags(card_stub(), "2025 Panini Prizm WNBA Aja Wilson #135")

        self.assertEqual(flags["exclusion_reason"], "wrong_or_missing_player")

    def test_wax_box_listing_exclusion(self):
        flags = comp_match_flags(card_stub(), "2025 Panini Prizm WNBA Hobby Box", "$749.95")

        self.assertEqual(flags["exclusion_reason"], "unopened_wax_or_sealed_product")

    def test_active_listing_discounting_and_low_confidence(self):
        comps = [
            {
                "provider": "ebay",
                "source_type": CardVaultComp.SourceType.ACTIVE_LISTING,
                "title": "2025 Panini Prizm WNBA Maya Moore #135",
                "url": "https://example.com/1",
                "price": "10.00",
                "raw_or_graded": "raw",
                "excluded": False,
                "card_match_score": 0.9,
            }
        ]

        pricing = calculate_pricing(card_stub(), comps, [], [])

        self.assertEqual(pricing["estimated_value_mid"], "7.00")
        self.assertEqual(pricing["confidence_label"], "low")

    def test_sold_comp_weighted_estimate(self):
        comps = [
            {
                "provider": "ebay",
                "source_type": CardVaultComp.SourceType.SOLD_COMP,
                "title": "2025 Panini Prizm WNBA Maya Moore #135 sold",
                "url": "https://example.com/1",
                "price": str(price),
                "raw_or_graded": "raw",
                "excluded": False,
                "card_match_score": 0.9,
            }
            for price in ("6.00", "8.00", "10.00")
        ]

        pricing = calculate_pricing(card_stub(), comps, [], [])

        self.assertEqual(pricing["sold_comp_count"], 3)
        self.assertEqual(pricing["estimated_value_mid"], "8.00")
        self.assertIn(pricing["confidence_label"], {"medium", "high"})

    def test_brave_search_hints_create_rough_low_confidence_estimate(self):
        comps = [
            {
                "provider": "brave",
                "source_type": CardVaultComp.SourceType.SEARCH_HINT,
                "title": "2025 Panini Prizm WNBA Maya Moore #135",
                "url": "https://example.com/1",
                "price": price,
                "raw_or_graded": "raw",
                "excluded": False,
                "card_match_score": 0.9,
            }
            for price in ("6.00", "10.00")
        ]

        pricing = calculate_pricing(card_stub(), comps, [], [])

        self.assertEqual(pricing["value_status"], "rough_search_estimate")
        self.assertEqual(pricing["value_status_label"], "Rough search estimate")
        self.assertEqual(pricing["estimated_value_mid"], "8.00")
        self.assertEqual(pricing["confidence_label"], "low")
        self.assertIn("No verified sold comps", pricing["pricing_explanation"])

    def test_single_search_hint_keeps_value_blank(self):
        comps = [
            {
                "provider": "brave",
                "source_type": CardVaultComp.SourceType.SEARCH_HINT,
                "title": "2025 Panini Prizm WNBA Maya Moore #135",
                "url": "https://example.com/1",
                "price": "6.00",
                "raw_or_graded": "raw",
                "excluded": False,
                "card_match_score": 0.9,
            }
        ]

        pricing = calculate_pricing(card_stub(), comps, [], [])

        self.assertEqual(pricing["value_status"], "no_reliable_estimate")
        self.assertIsNone(pricing["estimated_value_mid"])
        self.assertEqual(pricing["rough_estimate_warning"], "Needs stronger pricing source.")

    @mock.patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": "set"}, clear=True)
    def test_provider_readiness_is_secret_safe(self):
        status = provider_readiness()

        self.assertTrue(status["brave"]["configured"])
        self.assertFalse(status["ebay"]["configured"])
        self.assertEqual(status["ebay"]["missing_env_vars"], ["EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET"])

    def test_robust_range_ignores_extreme_outliers(self):
        low, mid, high, _spread = robust_range([Decimal("5"), Decimal("6"), Decimal("7"), Decimal("8"), Decimal("100")])

        self.assertEqual(str(low), "6.00")
        self.assertEqual(str(mid), "7.00")
        self.assertEqual(str(high), "8.00")


class PricingIntelligenceDbTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pricing-user", password="test-password")
        self.session = CardVaultIntakeSession.objects.create(title="Pricing", expected_card_count=1)
        self.card = CardVaultCard.objects.create(
            session=self.session,
            slot_index=1,
            player_name="Maya Moore",
            league="WNBA",
            sport="basketball",
            year="2025",
            brand="Panini",
            product="Prizm WNBA",
            set_name="2025 Panini Prizm WNBA",
            card_number="135",
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_valuation_run_creates_comps(self):
        brave_payload = {
            "provider": "brave",
            "available": True,
            "comps": [
                {
                    "provider": "ebay",
                    "source_type": CardVaultComp.SourceType.SOLD_COMP,
                    "title": "2025 Panini Prizm WNBA Maya Moore #135 sold",
                    "url": "https://example.com/1",
                    "price": "8.50",
                    "raw_or_graded": "raw",
                    "excluded": False,
                    "card_match_score": 0.9,
                }
            ],
        }

        with mock.patch.dict("card_vault.services.pricing.engine.PROVIDERS", {"brave": lambda card: brave_payload}):
            result = update_card_pricing(self.card.id, providers=["brave"], force=True)

        self.assertFalse(result.skipped)
        self.assertEqual(CardVaultValuationRun.objects.count(), 1)
        self.assertEqual(CardVaultComp.objects.count(), 1)
        self.card.refresh_from_db()
        self.assertEqual(str(self.card.estimated_raw_value), "8.50")

    def test_update_value_route_updates_card(self):
        brave_payload = {"provider": "brave", "available": True, "comps": []}

        with mock.patch.dict("card_vault.services.pricing.engine.PROVIDERS", {"brave": lambda card: brave_payload}):
            response = self.client.post(f"/card-vault/cards/{self.card.id}/update-value/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(CardVaultValuationRun.objects.count(), 1)

    def test_bulk_session_update_works(self):
        brave_payload = {"provider": "brave", "available": True, "comps": []}

        with mock.patch.dict("card_vault.services.pricing.engine.PROVIDERS", {"brave": lambda card: brave_payload}):
            response = self.client.post(f"/card-vault/intake/{self.session.id}/update-values/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(CardVaultValuationRun.objects.count(), 1)

    def test_pricing_dashboard_renders(self):
        response = self.client.get("/card-vault/pricing/dashboard/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pricing Intelligence")
