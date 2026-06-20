import uuid

from django.conf import settings
from django.db import models


class CardVaultLocation(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class CardVaultIntakeSession(models.Model):
    class SessionType(models.TextChoices):
        BATCH_FRONT_BACK = "batch_front_back", "Batch front/back"

    class ReviewStatus(models.TextChoices):
        NEEDS_REVIEW = "needs_review", "Needs review"
        IN_REVIEW = "in_review", "In review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_type = models.CharField(
        max_length=64,
        choices=SessionType.choices,
        default=SessionType.BATCH_FRONT_BACK,
        db_index=True,
    )
    title = models.CharField(max_length=255, blank=True)
    sport = models.CharField(max_length=64, default="basketball")
    expected_card_count = models.PositiveSmallIntegerField(default=10)
    detected_front_count = models.PositiveSmallIntegerField(default=0)
    detected_back_count = models.PositiveSmallIntegerField(default=0)
    review_status = models.CharField(
        max_length=32,
        choices=ReviewStatus.choices,
        default=ReviewStatus.NEEDS_REVIEW,
        db_index=True,
    )
    extraction_status = models.CharField(max_length=64, default="not_started", db_index=True)
    extraction_summary = models.JSONField(default=dict, blank=True)
    ai_raw_response = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="card_vault_intake_sessions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["session_type", "review_status"], name="cv_session_type_status_idx"),
            models.Index(fields=["created_by", "-created_at"], name="cv_session_user_created_idx"),
        ]

    def __str__(self) -> str:
        return self.title or f"Card Vault intake {self.pk}"


class CardVaultImage(models.Model):
    class ImageRole(models.TextChoices):
        FRONT_GROUP_ORIGINAL = "front_group_original", "Front group original"
        BACK_GROUP_ORIGINAL = "back_group_original", "Back group original"
        FRONT_CROP = "front_crop", "Front crop"
        BACK_CROP = "back_crop", "Back crop"

    session = models.ForeignKey(
        CardVaultIntakeSession,
        on_delete=models.CASCADE,
        related_name="images",
    )
    card = models.ForeignKey(
        "CardVaultCard",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="images",
    )
    role = models.CharField(max_length=64, choices=ImageRole.choices, db_index=True)
    image = models.FileField(upload_to="card_vault/%Y/%m/%d/")
    original_filename = models.CharField(max_length=512, blank=True)
    slot_index = models.PositiveSmallIntegerField(null=True, blank=True, db_index=True)
    crop_box = models.JSONField(
        default=dict,
        blank=True,
        help_text="Future crop geometry, e.g. {'x': 0, 'y': 0, 'width': 0, 'height': 0}.",
    )
    detection_confidence = models.FloatField(default=0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["session", "role", "slot_index", "id"]
        indexes = [
            models.Index(fields=["session", "role"], name="cv_image_session_role_idx"),
            models.Index(fields=["session", "slot_index"], name="cv_image_session_slot_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.get_role_display()} {self.original_filename or self.pk}"


class CardVaultCard(models.Model):
    class ReviewStatus(models.TextChoices):
        NEEDS_REVIEW = "needs_review", "Needs review"
        APPROVED = "approved", "Approved"
        IGNORED = "ignored", "Ignored"
        REJECTED = "rejected", "Rejected"

    session = models.ForeignKey(
        CardVaultIntakeSession,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cards",
    )
    slot_index = models.PositiveSmallIntegerField(default=1, db_index=True)
    front_image_crop = models.ForeignKey(
        CardVaultImage,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="front_for_cards",
    )
    back_image_crop = models.ForeignKey(
        CardVaultImage,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="back_for_cards",
    )
    location = models.ForeignKey(
        CardVaultLocation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cards",
    )
    player_name = models.CharField(max_length=255, blank=True)
    team = models.CharField(max_length=255, blank=True)
    league = models.CharField(max_length=64, blank=True)
    sport = models.CharField(max_length=64, default="basketball")
    year = models.CharField(max_length=32, blank=True)
    brand = models.CharField(max_length=128, blank=True)
    product = models.CharField(max_length=128, blank=True)
    set_name = models.CharField(max_length=255, blank=True)
    card_number = models.CharField(max_length=64, blank=True)
    rookie_status = models.BooleanField(default=False)
    insert_name = models.CharField(max_length=255, blank=True)
    parallel_name = models.CharField(max_length=255, blank=True)
    serial_number = models.CharField(max_length=64, blank=True)
    serial_total = models.CharField(max_length=64, blank=True)
    autograph_detected = models.BooleanField(default=False)
    relic_detected = models.BooleanField(default=False)
    patch_detected = models.BooleanField(default=False)
    estimated_raw_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    storage_recommendation = models.TextField(blank=True)
    extracted_json = models.JSONField(default=dict, blank=True)
    confidence = models.FloatField(default=0)
    review_status = models.CharField(
        max_length=32,
        choices=ReviewStatus.choices,
        default=ReviewStatus.NEEDS_REVIEW,
        db_index=True,
    )
    is_draft = models.BooleanField(default=True, db_index=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_card_vault_cards",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "slot_index"]
        indexes = [
            models.Index(fields=["review_status", "is_draft"], name="cv_card_review_draft_idx"),
            models.Index(fields=["session", "slot_index"], name="cv_card_session_slot_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "slot_index"],
                name="card_vault_unique_session_slot",
            ),
        ]

    def __str__(self) -> str:
        label = self.player_name or "Draft card"
        return f"{label} #{self.slot_index}"


class CardVaultValuation(models.Model):
    card = models.ForeignKey(
        CardVaultCard,
        on_delete=models.CASCADE,
        related_name="valuations",
    )
    source = models.CharField(max_length=128)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=8, default="USD")
    confidence = models.FloatField(default=0)
    valuation_date = models.DateField(null=True, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-valuation_date", "-created_at"]

    def __str__(self) -> str:
        return f"{self.card_id} {self.amount} {self.currency}"


class CardVaultValuationRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        PARTIAL = "partial", "Partial"

    class ConfidenceLabel(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"

    card = models.ForeignKey(
        CardVaultCard,
        on_delete=models.CASCADE,
        related_name="valuation_runs",
    )
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    query_used = models.TextField(blank=True)
    normalized_card_key = models.CharField(max_length=512, blank=True, db_index=True)
    estimated_value_low = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    estimated_value_mid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    estimated_value_high = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    estimated_psa9_value_low = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    estimated_psa9_value_mid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    estimated_psa9_value_high = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    estimated_psa10_value_low = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    estimated_psa10_value_mid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    estimated_psa10_value_high = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    value_confidence = models.FloatField(default=0)
    confidence_label = models.CharField(
        max_length=16,
        choices=ConfidenceLabel.choices,
        default=ConfidenceLabel.LOW,
        db_index=True,
    )
    comp_count_total = models.PositiveIntegerField(default=0)
    sold_comp_count = models.PositiveIntegerField(default=0)
    active_listing_count = models.PositiveIntegerField(default=0)
    guide_source_count = models.PositiveIntegerField(default=0)
    scarcity_source_count = models.PositiveIntegerField(default=0)
    grading_upside_score = models.FloatField(default=0)
    grading_recommendation = models.TextField(blank=True)
    pricing_summary = models.TextField(blank=True)
    pricing_explanation = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    raw_provider_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-started_at", "-created_at"]
        indexes = [
            models.Index(fields=["card", "-started_at"], name="cv_valrun_card_started_idx"),
            models.Index(fields=["status", "confidence_label"], name="cv_valrun_status_conf_idx"),
        ]

    def __str__(self) -> str:
        return f"valuation run {self.pk} for card {self.card_id}"


class CardVaultComp(models.Model):
    class SourceType(models.TextChoices):
        SOLD_COMP = "sold_comp", "Sold comp"
        ACTIVE_LISTING = "active_listing", "Active listing"
        PRICE_GUIDE = "price_guide", "Price guide"
        POP_REPORT = "pop_report", "Population report"
        SEARCH_HINT = "search_hint", "Search hint"
        MANUAL = "manual", "Manual"

    valuation_run = models.ForeignKey(
        CardVaultValuationRun,
        on_delete=models.CASCADE,
        related_name="comps",
    )
    provider = models.CharField(max_length=128)
    source_type = models.CharField(max_length=32, choices=SourceType.choices, db_index=True)
    title = models.TextField(blank=True)
    url = models.URLField(max_length=1200, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=8, default="USD")
    sale_date = models.DateField(null=True, blank=True)
    listing_status = models.CharField(max_length=64, blank=True)
    grade = models.CharField(max_length=64, blank=True)
    raw_or_graded = models.CharField(max_length=32, default="raw", db_index=True)
    card_match_score = models.FloatField(default=0)
    player_match = models.BooleanField(default=False)
    year_match = models.BooleanField(default=False)
    brand_match = models.BooleanField(default=False)
    product_match = models.BooleanField(default=False)
    card_number_match = models.BooleanField(default=False)
    parallel_match = models.BooleanField(default=False)
    rookie_match = models.BooleanField(default=False)
    auto_match = models.BooleanField(default=False)
    relic_match = models.BooleanField(default=False)
    numbered_match = models.BooleanField(default=False)
    excluded = models.BooleanField(default=False, db_index=True)
    exclusion_reason = models.CharField(max_length=255, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["excluded", "-card_match_score", "price"]
        indexes = [
            models.Index(fields=["valuation_run", "source_type"], name="cv_comp_run_type_idx"),
            models.Index(fields=["excluded", "card_match_score"], name="cv_comp_excluded_score_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.provider} {self.source_type} {self.price or ''}".strip()


class CardVaultPriceSnapshot(models.Model):
    card = models.ForeignKey(
        CardVaultCard,
        on_delete=models.CASCADE,
        related_name="price_snapshots",
    )
    valuation_run = models.ForeignKey(
        CardVaultValuationRun,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="snapshots",
    )
    estimated_value_low = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    estimated_value_mid = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    estimated_value_high = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    confidence_label = models.CharField(max_length=16, default="low", db_index=True)
    comp_count = models.PositiveIntegerField(default=0)
    source_summary = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["card", "-created_at"], name="cv_snapshot_card_created_idx"),
            models.Index(fields=["confidence_label", "-created_at"], name="cv_snapshot_conf_created_idx"),
        ]

    def __str__(self) -> str:
        return f"snapshot {self.pk} for card {self.card_id}"
