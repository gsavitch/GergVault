import json
import os
from io import BytesIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from PIL import Image

from card_vault.models import CardVaultCard, CardVaultImage, CardVaultIntakeSession
from card_vault.serializers import draft_json_for_slot
from card_vault.services.ai_extraction import (
    CardVaultExtractionError,
    MissingOpenAIKey,
    run_extraction_for_session,
)


class FakeOpenAIResponse:
    def __init__(self, cards):
        self.cards = cards

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "id": "resp_card_vault_test",
            "output_text": json.dumps(self.cards),
        }


class FakeMalformedOpenAIResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "id": "resp_bad_json",
            "output_text": "[{\"slot_index\": 1,",
        }


def jpeg_bytes(width=1000, height=400):
    image = Image.new("RGB", (width, height), color=(210, 220, 214))
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def sample_cards():
    cards = []
    for slot_index in range(1, 11):
        cards.append(
            {
                "slot_index": slot_index,
                "player_name": f"Player {slot_index}",
                "team": f"Team {slot_index}",
                "league": "WNBA",
                "sport": "basketball",
                "year": "2025",
                "brand": "Panini",
                "product": "Prizm",
                "set_name": "2025 Panini Prizm WNBA",
                "card_number": str(slot_index),
                "rookie_status": False,
                "insert_name": "",
                "parallel_name": "",
                "serial_number": "",
                "serial_total": "",
                "autograph_detected": False,
                "relic_detected": False,
                "patch_detected": False,
                "estimated_raw_value": None,
                "storage_recommendation": "",
                "confidence": 0.9,
                "review_status": "needs_review",
            }
        )
    return cards


@override_settings(MEDIA_ROOT="/tmp/open-card-vault-ai-test-media")
class CardVaultAiExtractionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="ai-user",
            password="test-password",
        )
        self.session = CardVaultIntakeSession.objects.create(
            title="AI Extraction session",
            expected_card_count=10,
            created_by=self.user,
        )
        CardVaultImage.objects.create(
            session=self.session,
            role=CardVaultImage.ImageRole.FRONT_GROUP_ORIGINAL,
            image=SimpleUploadedFile("fronts.jpg", jpeg_bytes(), content_type="image/jpeg"),
            original_filename="fronts.jpg",
        )
        CardVaultImage.objects.create(
            session=self.session,
            role=CardVaultImage.ImageRole.BACK_GROUP_ORIGINAL,
            image=SimpleUploadedFile("backs.jpg", jpeg_bytes(), content_type="image/jpeg"),
            original_filename="backs.jpg",
        )
        for slot_index in range(1, 11):
            CardVaultCard.objects.create(
                session=self.session,
                slot_index=slot_index,
                sport="basketball",
                extracted_json=draft_json_for_slot(slot_index),
            )

    @mock.patch("card_vault.services.ai_extraction.requests.post")
    @mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    def test_mock_openai_response_updates_10_draft_cards(self, post):
        post.return_value = FakeOpenAIResponse(sample_cards())

        with mock.patch("card_vault.services.ai_extraction.create_grid_crops_for_session", return_value=20):
            result = run_extraction_for_session(self.session)

        self.assertEqual(result.updated_count, 10)
        self.assertEqual(result.skipped_approved_count, 0)
        self.assertEqual(result.crop_count, 20)
        self.session.refresh_from_db()
        self.assertEqual(self.session.extraction_status, "completed")
        self.assertEqual(self.session.ai_raw_response["id"], "resp_card_vault_test")
        cards = list(self.session.cards.order_by("slot_index"))
        self.assertEqual(cards[0].player_name, "Player 1")
        self.assertEqual(cards[9].player_name, "Player 10")
        for card in cards:
            self.assertEqual(card.review_status, CardVaultCard.ReviewStatus.NEEDS_REVIEW)
            self.assertTrue(card.is_draft)
            self.assertEqual(card.extracted_json["player_name"], f"Player {card.slot_index}")
            self.assertEqual(card.extracted_json["review_status"], "needs_review")

    @mock.patch("card_vault.services.ai_extraction.requests.post")
    @mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    def test_approved_cards_are_not_overwritten_without_force(self, post):
        approved = self.session.cards.get(slot_index=1)
        approved.player_name = "Already Approved"
        approved.review_status = CardVaultCard.ReviewStatus.APPROVED
        approved.is_draft = False
        approved.save()
        post.return_value = FakeOpenAIResponse(sample_cards())

        result = run_extraction_for_session(self.session)

        self.assertEqual(result.updated_count, 9)
        self.assertEqual(result.skipped_approved_count, 1)
        approved.refresh_from_db()
        self.assertEqual(approved.player_name, "Already Approved")
        self.assertEqual(approved.review_status, CardVaultCard.ReviewStatus.APPROVED)

    @mock.patch("card_vault.services.ai_extraction.requests.post")
    @mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    def test_malformed_ai_response_is_marked_failed(self, post):
        post.return_value = FakeMalformedOpenAIResponse()

        with self.assertRaises(CardVaultExtractionError):
            run_extraction_for_session(self.session)

        self.session.refresh_from_db()
        self.assertEqual(self.session.extraction_status, "failed")
        self.assertEqual(self.session.extraction_summary["error_type"], "CardVaultExtractionError")
        self.assertIn("JSON", self.session.extraction_summary["error"])

    @mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""})
    def test_missing_api_key_is_handled_gracefully(self):
        with self.assertRaises(MissingOpenAIKey):
            run_extraction_for_session(self.session)

        self.session.refresh_from_db()
        self.assertEqual(self.session.extraction_status, "failed")
        self.assertEqual(self.session.extraction_summary["error_type"], "missing_openai_key")
        self.assertIn("OPENAI_API_KEY is not set", self.session.extraction_summary["error"])

    @mock.patch("card_vault.services.ai_extraction.requests.post")
    @mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"})
    def test_review_page_shows_extracted_values(self, post):
        post.return_value = FakeOpenAIResponse(sample_cards())
        run_extraction_for_session(self.session)
        client = Client()
        client.force_login(self.user)

        response = client.get(f"/card-vault/intake/{self.session.id}/review/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Player 1", content)
        self.assertIn("Team 10", content)
        self.assertIn("Run AI Extraction", content)
