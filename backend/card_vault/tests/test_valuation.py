from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings

from card_vault.models import CardVaultCard, CardVaultComp, CardVaultIntakeSession, CardVaultValuationRun
from card_vault.serializers import draft_json_for_slot
from card_vault.services.valuation import (
    _extract_price,
    update_card_estimated_value,
)


class FakeBraveResponse:
    def __init__(self, results):
        self.results = results

    def raise_for_status(self):
        return None

    def json(self):
        return {"web": {"results": self.results}}


def brave_results():
    return [
        {
            "title": "2025 Panini Prizm WNBA A'ja Wilson #3 sold eBay",
            "url": "https://www.ebay.com/itm/example-sold",
            "description": "Sold for $12.50 with similar raw condition.",
        },
        {
            "title": "A'ja Wilson 2025 Prizm card completed listing",
            "url": "https://www.ebay.com/itm/example-completed",
            "description": "Completed at US $20.00 plus shipping.",
        },
        {
            "title": "SportsCardsPro A'ja Wilson 2025 Prizm #3",
            "url": "https://www.sportscardspro.com/game/basketball-cards-2025-panini-prizm/aja-wilson-3",
            "description": "Ungraded price $8.00 from recent sales.",
        },
    ]


def weak_results():
    return [
        {
            "title": "Checklist for 2025 Panini Prizm WNBA",
            "url": "https://example.com/checklist",
            "description": "No price in this snippet.",
        }
    ]


def pricing_payload():
    return {
        "provider": "brave",
        "available": True,
        "comps": [
            {
                "provider": "ebay",
                "source_type": CardVaultComp.SourceType.SEARCH_HINT,
                "title": "2025 Panini Prizm WNBA A'ja Wilson #3 sold eBay",
                "url": "https://www.ebay.com/itm/example-sold",
                "price": "12.50",
                "raw_or_graded": "raw",
                "excluded": False,
                "card_match_score": 0.95,
                "player_match": True,
                "year_match": True,
                "brand_match": True,
                "product_match": True,
                "card_number_match": True,
            },
            {
                "provider": "ebay",
                "source_type": CardVaultComp.SourceType.SEARCH_HINT,
                "title": "A'ja Wilson 2025 Prizm #3 completed listing",
                "url": "https://www.ebay.com/itm/example-completed",
                "price": "20.00",
                "raw_or_graded": "raw",
                "excluded": False,
                "card_match_score": 0.9,
                "player_match": True,
                "year_match": True,
                "brand_match": True,
                "product_match": True,
                "card_number_match": True,
            },
            {
                "provider": "sportscardspro",
                "source_type": CardVaultComp.SourceType.SEARCH_HINT,
                "title": "SportsCardsPro A'ja Wilson 2025 Prizm #3",
                "url": "https://www.sportscardspro.com/game/basketball-cards-2025-panini-prizm/aja-wilson-3",
                "price": "8.00",
                "raw_or_graded": "raw",
                "excluded": False,
                "card_match_score": 0.9,
                "player_match": True,
                "year_match": True,
                "brand_match": True,
                "product_match": True,
                "card_number_match": True,
            },
        ],
    }


def weak_pricing_payload():
    return {
        "provider": "brave",
        "available": True,
        "comps": [
            {
                "provider": "brave",
                "source_type": CardVaultComp.SourceType.MANUAL,
                "title": "Checklist for 2025 Panini Prizm WNBA",
                "url": "https://example.com/checklist",
                "price": None,
                "raw_or_graded": "raw",
                "excluded": False,
                "card_match_score": 0.2,
            }
        ],
    }


@override_settings(MEDIA_ROOT="/tmp/open-card-vault-valuation-test-media")
class CardVaultValuationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="valuation-user",
            password="test-password",
        )
        self.session = CardVaultIntakeSession.objects.create(
            title="Valuation session",
            expected_card_count=10,
            created_by=self.user,
        )
        for slot_index in range(1, 11):
            CardVaultCard.objects.create(
                session=self.session,
                slot_index=slot_index,
                player_name=f"Player {slot_index}",
                team="Las Vegas Aces",
                league="WNBA",
                sport="basketball",
                year="2025",
                brand="Panini",
                product="Prizm",
                card_number=str(slot_index),
                extracted_json=draft_json_for_slot(slot_index),
            )
        self.card = self.session.cards.get(slot_index=1)
        self.card.player_name = "A'ja Wilson"
        self.card.card_number = "3"
        self.card.save()
        self.client = Client()
        self.client.force_login(self.user)

    def test_price_extraction_works(self):
        self.assertEqual(str(_extract_price("Sold for $12.50 yesterday")), "12.50")
        self.assertEqual(str(_extract_price("Completed at USD 1,250.00")), "1250.00")

    @mock.patch.dict("card_vault.services.pricing.engine.PROVIDERS", {"brave": lambda card: pricing_payload(), "manual": lambda card: {"provider": "manual", "available": True, "comps": []}})
    def test_mock_brave_response_updates_card_value_and_history(self):

        result = update_card_estimated_value(self.card.id, force=True)

        self.assertFalse(result.skipped)
        self.card.refresh_from_db()
        self.assertEqual(str(self.card.estimated_raw_value), "12.50")
        self.assertEqual(self.card.extracted_json["estimated_raw_value"], "12.50")
        self.assertEqual(self.card.extracted_json["valuation"]["provider"], "pricing_intelligence_v2")
        self.assertEqual(CardVaultValuationRun.objects.filter(card=self.card).count(), 1)
        self.assertEqual(self.card.valuation_runs.first().comps.count(), 3)

    def test_missing_api_key_handled(self):
        result = update_card_estimated_value(self.card.id, force=True)

        self.assertFalse(result.skipped)
        self.assertIsNone(result.valuation["estimated_raw_value"])
        self.assertLess(result.valuation["confidence"], 0.5)
        self.card.refresh_from_db()
        self.assertIsNone(self.card.estimated_raw_value)

    @mock.patch.dict("card_vault.services.pricing.engine.PROVIDERS", {"brave": lambda card: pricing_payload(), "manual": lambda card: {"provider": "manual", "available": True, "comps": []}})
    def test_session_bulk_value_update_works(self):

        response = self.client.post(f"/card-vault/intake/{self.session.id}/update-values/")

        self.assertEqual(response.status_code, 302)
        self.session.refresh_from_db()
        self.assertEqual(self.session.extraction_summary["valuation_updated_count"], 10)
        self.assertEqual(CardVaultValuationRun.objects.count(), 10)

    @mock.patch.dict("card_vault.services.pricing.engine.PROVIDERS", {"brave": lambda card: pricing_payload(), "manual": lambda card: {"provider": "manual", "available": True, "comps": []}})
    def test_card_detail_update_button_works(self):

        response = self.client.post(f"/card-vault/cards/{self.card.id}/update-value/")

        self.assertEqual(response.status_code, 302)
        self.card.refresh_from_db()
        self.assertEqual(str(self.card.estimated_raw_value), "12.50")

    @mock.patch.dict("card_vault.services.pricing.engine.PROVIDERS", {"brave": lambda card: weak_pricing_payload(), "manual": lambda card: {"provider": "manual", "available": True, "comps": []}})
    def test_weak_comps_create_low_confidence(self):

        result = update_card_estimated_value(self.card.id, force=True)

        self.assertLess(result.valuation["confidence"], 0.5)
        self.assertIn("no sold comps", result.valuation["warning"])
        self.card.refresh_from_db()
        self.assertIsNone(self.card.estimated_raw_value)
