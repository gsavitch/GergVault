from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from card_vault.models import CardVaultCard, CardVaultImage, CardVaultIntakeSession


@override_settings(MEDIA_ROOT="/tmp/open-card-vault-test-media")
class BatchCardIntakeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="card-vault-user",
            password="test-password",
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_batch_front_back_upload_creates_session_images_and_draft_cards(self):
        response = self.client.post(
            "/api/card-vault/intake/batch/",
            data={
                "title": "WNBA Prizm 10-card test",
                "front_group_image": SimpleUploadedFile(
                    "fronts.jpg",
                    b"front image bytes",
                    content_type="image/jpeg",
                ),
                "back_group_image": SimpleUploadedFile(
                    "backs.jpg",
                    b"back image bytes",
                    content_type="image/jpeg",
                ),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 201)
        session = CardVaultIntakeSession.objects.get()
        self.assertEqual(session.session_type, CardVaultIntakeSession.SessionType.BATCH_FRONT_BACK)
        self.assertEqual(session.expected_card_count, 10)
        self.assertEqual(session.review_status, CardVaultIntakeSession.ReviewStatus.NEEDS_REVIEW)
        self.assertEqual(session.created_by, self.user)

        self.assertEqual(CardVaultImage.objects.count(), 2)
        self.assertTrue(
            CardVaultImage.objects.filter(
                session=session,
                role=CardVaultImage.ImageRole.FRONT_GROUP_ORIGINAL,
                original_filename="fronts.jpg",
            ).exists()
        )
        self.assertTrue(
            CardVaultImage.objects.filter(
                session=session,
                role=CardVaultImage.ImageRole.BACK_GROUP_ORIGINAL,
                original_filename="backs.jpg",
            ).exists()
        )

        cards = list(CardVaultCard.objects.order_by("slot_index"))
        self.assertEqual(len(cards), 10)
        self.assertEqual([card.slot_index for card in cards], list(range(1, 11)))
        for card in cards:
            self.assertTrue(card.is_draft)
            self.assertEqual(card.review_status, CardVaultCard.ReviewStatus.NEEDS_REVIEW)
            self.assertEqual(card.sport, "basketball")
            self.assertEqual(card.confidence, 0)
            self.assertEqual(card.extracted_json["slot_index"], card.slot_index)
            self.assertIsNone(card.extracted_json["front_image_crop_id"])
            self.assertIsNone(card.extracted_json["back_image_crop_id"])
            self.assertEqual(card.extracted_json["review_status"], "needs_review")

        payload = response.json()
        self.assertEqual(payload["session_type"], "batch_front_back")
        self.assertEqual(len(payload["cards"]), 10)
        self.assertEqual(len(payload["images"]), 2)
        self.assertIn("/card-vault/intake/", payload["review_url"])

    def test_batch_intake_rejects_more_than_ten_slots(self):
        response = self.client.post(
            "/api/card-vault/intake/batch/",
            data={
                "expected_card_count": 11,
                "front_group_image": SimpleUploadedFile("fronts.jpg", b"x", content_type="image/jpeg"),
                "back_group_image": SimpleUploadedFile("backs.jpg", b"x", content_type="image/jpeg"),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, 400)
