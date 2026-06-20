from decimal import Decimal

from rest_framework import serializers

from card_vault.models import CardVaultCard, CardVaultImage, CardVaultIntakeSession


CARD_DRAFT_FIELDS = (
    "slot_index",
    "front_image_crop_id",
    "back_image_crop_id",
    "player_name",
    "team",
    "league",
    "sport",
    "year",
    "brand",
    "product",
    "set_name",
    "card_number",
    "rookie_status",
    "insert_name",
    "parallel_name",
    "serial_number",
    "serial_total",
    "autograph_detected",
    "relic_detected",
    "patch_detected",
    "estimated_raw_value",
    "storage_recommendation",
    "confidence",
    "review_status",
)

RICH_METADATA_GROUPS = {
    "player_profile": (
        "player_full_name",
        "player_slug",
        "player_wikipedia_url",
        "player_official_profile_url",
        "league_player_profile_url",
        "team_profile_url",
        "player_position",
        "player_status",
        "hall_of_fame_status",
        "career_summary_short",
        "career_stats_summary",
        "career_stats",
        "latest_season_stats",
        "player_awards_summary",
    ),
    "card_classification": (
        "card_type",
        "card_type_explanation",
        "rarity_tier",
        "rarity_explanation",
        "collector_interest_score",
        "investment_score",
        "grading_candidate_score",
    ),
    "product_checklist": (
        "manufacturer",
        "product_line",
        "release_year",
        "checklist_url",
        "checklist_name",
        "checklist_card_title",
        "known_parallel_family",
        "possible_parallel_matches",
    ),
    "market_value": (
        "estimated_raw_value_low",
        "estimated_raw_value_mid",
        "estimated_raw_value_high",
        "value_confidence",
        "value_last_updated",
        "valuation_sources",
        "recent_comp_summary",
    ),
    "storage_protection": (
        "protection_level",
        "protection_reason",
        "recommended_supply",
        "physical_location_label",
    ),
    "external_links": (
        "wikipedia_url",
        "basketball_reference_url",
        "wnba_profile_url",
        "nba_profile_url",
        "sports_reference_url",
        "tcdb_url",
        "sportscardspro_url",
        "ebay_search_url",
        "psa_pop_report_url",
    ),
}

LIST_METADATA_FIELDS = {
    "possible_parallel_matches",
    "valuation_sources",
}

EDITABLE_CARD_FIELDS = (
    "player_name",
    "team",
    "league",
    "sport",
    "year",
    "brand",
    "product",
    "set_name",
    "card_number",
    "rookie_status",
    "insert_name",
    "parallel_name",
    "serial_number",
    "serial_total",
    "autograph_detected",
    "relic_detected",
    "patch_detected",
    "estimated_raw_value",
    "storage_recommendation",
    "confidence",
)


def draft_json_for_slot(slot_index: int, sport: str = "basketball") -> dict:
    draft = {
        "slot_index": slot_index,
        "front_image_crop_id": None,
        "back_image_crop_id": None,
        "player_name": "",
        "team": "",
        "league": "",
        "sport": sport,
        "year": "",
        "brand": "",
        "product": "",
        "set_name": "",
        "card_number": "",
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
        "confidence": 0,
        "review_status": CardVaultCard.ReviewStatus.NEEDS_REVIEW,
    }
    draft.update(rich_metadata_defaults())
    return draft


def extracted_json_for_card(card: CardVaultCard) -> dict:
    draft = draft_json_for_slot(slot_index=card.slot_index, sport=card.sport)
    existing = card.extracted_json or {}
    for field in draft:
        if field == "front_image_crop_id":
            draft[field] = card.front_image_crop_id
        elif field == "back_image_crop_id":
            draft[field] = card.back_image_crop_id
        elif hasattr(card, field):
            value = getattr(card, field)
            if field == "estimated_raw_value" and value is not None:
                value = str(value)
            draft[field] = value
    for key, value in existing.items():
        if key not in draft or not hasattr(card, key):
            draft[key] = value
    draft.update(inferred_metadata_for_card(card, draft))
    return draft


def rich_metadata_defaults() -> dict:
    defaults = {}
    for fields in RICH_METADATA_GROUPS.values():
        for field in fields:
            defaults[field] = [] if field in LIST_METADATA_FIELDS else None
    defaults["card_type"] = "unknown"
    defaults["rarity_tier"] = "unknown"
    return defaults


def rich_metadata_sections(card: CardVaultCard) -> dict:
    data = extracted_json_for_card(card)
    return {
        group: {field: data.get(field) for field in fields}
        for group, fields in RICH_METADATA_GROUPS.items()
    }


def inferred_metadata_for_card(card: CardVaultCard, data: dict | None = None) -> dict:
    data = data or {}
    inferred = {}
    player = (card.player_name or data.get("player_name") or "").strip()
    product = (card.product or data.get("product") or "").strip()
    brand = (card.brand or data.get("brand") or "").strip()
    set_name = (card.set_name or data.get("set_name") or "").strip()
    year = (card.year or data.get("year") or "").strip()
    parallel = (card.parallel_name or data.get("parallel_name") or "").strip()
    serial_number = (card.serial_number or data.get("serial_number") or "").strip()
    serial_total = (card.serial_total or data.get("serial_total") or "").strip()

    if not data.get("player_full_name") and player:
        inferred["player_full_name"] = player
    if not data.get("player_slug") and player:
        inferred["player_slug"] = _slug(player)
    if not data.get("manufacturer") and brand:
        inferred["manufacturer"] = brand
    if not data.get("product_line") and product:
        inferred["product_line"] = product
    if not data.get("release_year") and year:
        inferred["release_year"] = year
    if not data.get("checklist_card_title") and player:
        title_parts = [year, brand, product, set_name, player]
        if card.card_number or data.get("card_number"):
            title_parts.append(f"#{card.card_number or data.get('card_number')}")
        inferred["checklist_card_title"] = " ".join(part for part in title_parts if part)

    if not data.get("card_type") or data.get("card_type") == "unknown":
        inferred["card_type"] = _card_type_for(card, data)
    if not data.get("card_type_explanation"):
        inferred["card_type_explanation"] = _card_type_explanation(card, data)
    if not data.get("rarity_tier") or data.get("rarity_tier") == "unknown":
        inferred["rarity_tier"] = _rarity_tier_for(card, data)
    if not data.get("rarity_explanation"):
        if parallel or serial_number or serial_total:
            inferred["rarity_explanation"] = "Parallel or serial-numbered attributes may make this scarcer than a base card; confirm against a checklist."
        else:
            inferred["rarity_explanation"] = "No parallel, short print, autograph, relic, patch, or serial numbering is currently detected."
    if data.get("collector_interest_score") is None:
        inferred["collector_interest_score"] = _collector_interest_score(player)
    if data.get("investment_score") is None:
        inferred["investment_score"] = _investment_score(card, data)
    if data.get("grading_candidate_score") is None:
        inferred["grading_candidate_score"] = _grading_candidate_score(card, data)
    if not data.get("career_summary_short") and player.lower() == "maya moore":
        inferred["career_summary_short"] = "Maya Moore is a major WNBA historical player, which can create stronger collector interest than a typical veteran card."

    if not data.get("protection_level"):
        inferred["protection_level"] = "standard"
    if not data.get("protection_reason"):
        inferred["protection_reason"] = "Use standard soft sleeve and top loader until value, condition, and rarity are confirmed."
    if not data.get("recommended_supply"):
        inferred["recommended_supply"] = "penny sleeve + top loader"
    return inferred


def _card_type_for(card: CardVaultCard, data: dict) -> str:
    if card.rookie_status or data.get("rookie_status"):
        return "rookie"
    if card.autograph_detected or data.get("autograph_detected"):
        return "autograph"
    if card.patch_detected or data.get("patch_detected"):
        return "patch"
    if card.relic_detected or data.get("relic_detected"):
        return "relic"
    if card.serial_number or card.serial_total or data.get("serial_number") or data.get("serial_total"):
        return "numbered"
    if card.parallel_name or data.get("parallel_name"):
        return "parallel"
    if card.insert_name or data.get("insert_name"):
        return "insert"
    return "base"


def _card_type_explanation(card: CardVaultCard, data: dict) -> str:
    product_label = " ".join(part for part in [card.brand or data.get("brand"), card.product or data.get("product"), card.league or data.get("league")] if part)
    prefix = f"This is a {product_label} card. " if product_label else ""
    if _card_type_for(card, data) == "base":
        return (
            prefix
            + "It appears to be a base card unless a parallel is detected. It is not currently marked as a rookie, autograph, jersey, patch, or numbered card."
        )
    return prefix + "Classification is based on the currently detected rookie, insert, parallel, autograph, relic, patch, or serial-number fields."


def _rarity_tier_for(card: CardVaultCard, data: dict) -> str:
    card_type = _card_type_for(card, data)
    if card_type in {"autograph", "patch", "case_hit", "short_print"}:
        return "ultra_rare"
    if card_type in {"relic", "numbered"}:
        return "scarce"
    if card_type in {"parallel", "insert", "rookie"}:
        return "rare"
    if card_type == "base":
        return "common"
    return "unknown"


def _collector_interest_score(player: str) -> int | None:
    if not player:
        return None
    return 85 if player.lower() == "maya moore" else 50


def _investment_score(card: CardVaultCard, data: dict) -> int | None:
    if not card.player_name and not data.get("player_name"):
        return None
    score = 45
    if card.rookie_status or data.get("rookie_status"):
        score += 15
    if card.autograph_detected or data.get("autograph_detected"):
        score += 15
    if (card.player_name or data.get("player_name") or "").lower() == "maya moore":
        score += 10
    return min(score, 100)


def _grading_candidate_score(card: CardVaultCard, data: dict) -> int | None:
    if not card.player_name and not data.get("player_name"):
        return None
    score = 45
    if card.estimated_raw_value:
        score += 10
    if _rarity_tier_for(card, data) in {"rare", "scarce", "ultra_rare"}:
        score += 15
    return min(score, 100)


def _slug(value: str) -> str:
    return "-".join("".join(ch.lower() if ch.isalnum() else " " for ch in value).split())


class CardVaultBatchIntakeSerializer(serializers.Serializer):
    front_group_image = serializers.FileField()
    back_group_image = serializers.FileField()
    title = serializers.CharField(required=False, allow_blank=True, max_length=255)
    sport = serializers.CharField(required=False, allow_blank=True, default="basketball")
    expected_card_count = serializers.IntegerField(required=False, min_value=1, max_value=10, default=10)
    notes = serializers.CharField(required=False, allow_blank=True)


class CardVaultImageSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = CardVaultImage
        fields = (
            "id",
            "role",
            "url",
            "original_filename",
            "slot_index",
            "crop_box",
            "detection_confidence",
            "metadata",
            "created_at",
        )

    def get_url(self, obj: CardVaultImage) -> str:
        if not obj.image:
            return ""
        request = self.context.get("request")
        url = obj.protected_url
        return request.build_absolute_uri(url) if request else url


class CardVaultCardSerializer(serializers.ModelSerializer):
    front_image_crop_id = serializers.PrimaryKeyRelatedField(
        source="front_image_crop",
        queryset=CardVaultImage.objects.all(),
        allow_null=True,
        required=False,
    )
    back_image_crop_id = serializers.PrimaryKeyRelatedField(
        source="back_image_crop",
        queryset=CardVaultImage.objects.all(),
        allow_null=True,
        required=False,
    )

    class Meta:
        model = CardVaultCard
        fields = (
            "id",
            "slot_index",
            "front_image_crop_id",
            "back_image_crop_id",
            "player_name",
            "team",
            "league",
            "sport",
            "year",
            "brand",
            "product",
            "set_name",
            "card_number",
            "rookie_status",
            "insert_name",
            "parallel_name",
            "serial_number",
            "serial_total",
            "autograph_detected",
            "relic_detected",
            "patch_detected",
            "estimated_raw_value",
            "storage_recommendation",
            "extracted_json",
            "confidence",
            "review_status",
            "is_draft",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "extracted_json", "is_draft", "created_at", "updated_at")

    def to_representation(self, instance):
        data = super().to_representation(instance)
        value = data.get("estimated_raw_value")
        if isinstance(value, Decimal):
            data["estimated_raw_value"] = str(value)
        return data


class CardVaultIntakeSessionSerializer(serializers.ModelSerializer):
    images = CardVaultImageSerializer(many=True, read_only=True)
    cards = CardVaultCardSerializer(many=True, read_only=True)
    review_url = serializers.SerializerMethodField()

    class Meta:
        model = CardVaultIntakeSession
        fields = (
            "id",
            "session_type",
            "title",
            "sport",
            "expected_card_count",
            "detected_front_count",
            "detected_back_count",
            "review_status",
            "extraction_status",
            "extraction_summary",
            "ai_raw_response",
            "notes",
            "review_url",
            "images",
            "cards",
            "created_at",
            "updated_at",
        )

    def get_review_url(self, obj: CardVaultIntakeSession) -> str:
        request = self.context.get("request")
        path = f"/card-vault/intake/{obj.pk}/review/"
        return request.build_absolute_uri(path) if request else path
