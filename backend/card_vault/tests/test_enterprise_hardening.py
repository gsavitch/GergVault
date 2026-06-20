from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings

from card_vault.models import CardVaultCard, CardVaultImage, CardVaultIntakeSession
from card_vault.tenancy import default_tenant_for_user


@override_settings(MEDIA_ROOT="/tmp/gergvault-enterprise-test-media")
class EnterpriseHardeningTests(TestCase):
    def setUp(self):
        cache.clear()
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner", email="owner@example.com", password="test-password")
        self.other = User.objects.create_user(username="other", email="other@example.com", password="test-password")
        self.owner_tenant = default_tenant_for_user(self.owner)
        self.other_tenant = default_tenant_for_user(self.other)
        self.session = CardVaultIntakeSession.objects.create(
            tenant=self.owner_tenant,
            title="Tenant owned intake",
            expected_card_count=10,
            created_by=self.owner,
        )
        self.image = CardVaultImage.objects.create(
            session=self.session,
            role=CardVaultImage.ImageRole.FRONT_GROUP_ORIGINAL,
            image=SimpleUploadedFile("front.jpg", b"front image bytes", content_type="image/jpeg"),
            original_filename="front.jpg",
        )
        for slot in range(1, 11):
            CardVaultCard.objects.create(
                tenant=self.owner_tenant,
                session=self.session,
                slot_index=slot,
                sport="basketball",
            )

    def test_other_user_cannot_open_review_session(self):
        client = Client()
        client.force_login(self.other)

        response = client.get(f"/card-vault/intake/{self.session.id}/review/")

        self.assertEqual(response.status_code, 404)

    def test_other_user_cannot_open_card_detail(self):
        card = self.session.cards.first()
        client = Client()
        client.force_login(self.other)

        response = client.get(f"/card-vault/cards/{card.id}/")

        self.assertEqual(response.status_code, 404)

    def test_private_media_requires_owner_tenant(self):
        owner_client = Client()
        owner_client.force_login(self.owner)
        other_client = Client()
        other_client.force_login(self.other)

        owner_response = owner_client.get(self.image.protected_url)
        other_response = other_client.get(self.image.protected_url)

        self.assertEqual(owner_response.status_code, 200)
        self.assertEqual(other_response.status_code, 404)

    @override_settings(
        GERGVAULT_RATE_LIMIT_ENABLED=True,
        GERGVAULT_RATE_LIMITS={"/accounts/signup/": (1, 60)},
    )
    def test_signup_rate_limit_returns_429(self):
        client = Client(HTTP_CF_CONNECTING_IP="198.51.100.20")

        first = client.post("/accounts/signup/", data={})
        second = client.post("/accounts/signup/", data={})

        self.assertNotEqual(first.status_code, 429)
        self.assertEqual(second.status_code, 429)
