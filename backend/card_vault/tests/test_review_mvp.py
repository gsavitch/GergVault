from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from rest_framework.test import APIClient

from card_vault.models import CardVaultCard, CardVaultImage, CardVaultIntakeSession
from card_vault.serializers import draft_json_for_slot


@override_settings(MEDIA_ROOT="/tmp/gerg-card-vault-review-test-media")
class CardVaultReviewMvpTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="review-user",
            password="test-password",
        )
        self.session = CardVaultIntakeSession.objects.create(
            title="Review MVP session",
            expected_card_count=10,
            created_by=self.user,
        )
        CardVaultImage.objects.create(
            session=self.session,
            role=CardVaultImage.ImageRole.FRONT_GROUP_ORIGINAL,
            image="card_vault/fronts.jpg",
            original_filename="fronts.jpg",
        )
        CardVaultImage.objects.create(
            session=self.session,
            role=CardVaultImage.ImageRole.BACK_GROUP_ORIGINAL,
            image="card_vault/backs.jpg",
            original_filename="backs.jpg",
        )
        for slot_index in range(1, 11):
            CardVaultCard.objects.create(
                session=self.session,
                slot_index=slot_index,
                sport="basketball",
                extracted_json=draft_json_for_slot(slot_index),
            )
        self.client = Client()
        self.client.force_login(self.user)

    def test_review_page_loads_with_images_and_ordered_draft_rows(self):
        response = self.client.get(f"/card-vault/intake/{self.session.id}/review/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn(str(self.session.id), content)
        self.assertIn("Front Group Image", content)
        self.assertIn("Back Group Image", content)
        self.assertIn("Review Panel", content)
        self.assertIn("Front crop", content)
        self.assertIn("Back crop", content)
        self.assertIn("Save", content)
        self.assertIn("Ignore", content)
        self.assertLess(content.index("Slot 1"), content.index("Slot 10"))

    def test_card_detail_page_loads_with_metadata_and_actions(self):
        card = self.session.cards.get(slot_index=1)
        card.player_name = "A'ja Wilson"
        card.team = "Las Vegas Aces"
        card.product = "Prizm"
        card.card_number = "3"
        card.storage_recommendation = "Assign later"
        card.save()

        response = self.client.get(f"/card-vault/cards/{card.id}/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("A&#x27;ja Wilson", content)
        self.assertIn("Card #", content)
        self.assertIn("Card Summary", content)
        self.assertIn("Player Profile", content)
        self.assertIn("Card Type Explanation", content)
        self.assertIn("Market Estimate", content)
        self.assertIn("External Links", content)
        self.assertIn("Storage Recommendation", content)
        self.assertIn("Raw Extracted JSON", content)
        self.assertIn("Storage location", content)
        self.assertIn("Approve", content)
        self.assertIn("Back to intake review", content)

    def test_draft_card_patch_updates_extracted_json(self):
        api = APIClient()
        api.force_authenticate(self.user)
        card = self.session.cards.get(slot_index=1)

        response = api.patch(
            f"/api/card-vault/intake/sessions/{self.session.id}/cards/{card.id}/",
            data={
                "player_name": "A'ja Wilson",
                "team": "Las Vegas Aces",
                "league": "WNBA",
                "sport": "basketball",
                "year": "2025",
                "brand": "Panini",
                "product": "Prizm",
                "card_number": "3",
                "rookie_status": False,
                "estimated_raw_value": "12.50",
                "storage_recommendation": "Assign location during review.",
                "confidence": 0.75,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        card.refresh_from_db()
        self.assertEqual(card.player_name, "A'ja Wilson")
        self.assertEqual(card.extracted_json["player_name"], "A'ja Wilson")
        self.assertEqual(card.extracted_json["team"], "Las Vegas Aces")
        self.assertEqual(card.extracted_json["estimated_raw_value"], "12.50")
        self.assertEqual(card.extracted_json["confidence"], 0.75)
        self.assertEqual(card.extracted_json["review_status"], "needs_review")

    def test_approve_action_changes_review_status(self):
        card = self.session.cards.get(slot_index=2)

        response = self.client.post(
            f"/card-vault/intake/{self.session.id}/cards/{card.id}/",
            data={
                "action": "approve",
                "player_name": "Maya Moore",
                "team": "Minnesota Lynx",
                "league": "WNBA",
                "sport": "basketball",
                "confidence": "0.80",
            },
        )

        self.assertEqual(response.status_code, 302)
        card.refresh_from_db()
        self.assertEqual(card.review_status, CardVaultCard.ReviewStatus.APPROVED)
        self.assertFalse(card.is_draft)
        self.assertEqual(card.approved_by, self.user)
        self.assertEqual(card.extracted_json["review_status"], "approved")
        self.assertEqual(card.extracted_json["player_name"], "Maya Moore")

    def test_dashboard_counts_render(self):
        approved = self.session.cards.get(slot_index=1)
        approved.review_status = CardVaultCard.ReviewStatus.APPROVED
        approved.is_draft = False
        approved.save(update_fields=["review_status", "is_draft"])
        ignored = self.session.cards.get(slot_index=2)
        ignored.review_status = CardVaultCard.ReviewStatus.IGNORED
        ignored.is_draft = False
        ignored.save(update_fields=["review_status", "is_draft"])

        response = self.client.get("/card-vault/")

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Total cards", content)
        self.assertIn("Needs review", content)
        self.assertIn("Approved", content)
        self.assertIn("Ignored", content)
        self.assertIn(">10<", content)
        self.assertIn(">8<", content)
        self.assertIn("Review session", content)
