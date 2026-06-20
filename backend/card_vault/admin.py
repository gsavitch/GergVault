from django.contrib import admin

from card_vault.models import (
    CardVaultCard,
    CardVaultImage,
    CardVaultIntakeSession,
    CardVaultLocation,
    CardVaultValuation,
    GergVaultTenant,
    GergVaultTenantMembership,
    GergVaultTrafficEvent,
    GergVaultUserProfile,
)


class CardVaultImageInline(admin.TabularInline):
    model = CardVaultImage
    extra = 0
    fields = ("role", "card", "slot_index", "image", "detection_confidence", "created_at")
    readonly_fields = ("created_at",)


class CardVaultCardInline(admin.TabularInline):
    model = CardVaultCard
    extra = 0
    fields = ("slot_index", "player_name", "team", "card_number", "confidence", "review_status", "is_draft")
    readonly_fields = ("confidence",)


@admin.register(CardVaultIntakeSession)
class CardVaultIntakeSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "session_type",
        "expected_card_count",
        "review_status",
        "extraction_status",
        "created_at",
    )
    list_filter = ("session_type", "review_status", "extraction_status", "created_at")
    search_fields = ("id", "title", "notes")
    readonly_fields = ("id", "created_at", "updated_at")
    inlines = [CardVaultImageInline, CardVaultCardInline]


@admin.register(CardVaultCard)
class CardVaultCardAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "player_name",
        "team",
        "sport",
        "year",
        "brand",
        "card_number",
        "slot_index",
        "review_status",
        "is_draft",
    )
    list_filter = ("sport", "league", "review_status", "is_draft", "rookie_status")
    search_fields = ("player_name", "team", "brand", "product", "set_name", "card_number")
    readonly_fields = ("created_at", "updated_at", "approved_at")
    autocomplete_fields = ("session", "location", "front_image_crop", "back_image_crop")


@admin.register(CardVaultImage)
class CardVaultImageAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "card", "role", "slot_index", "original_filename", "created_at")
    list_filter = ("role", "created_at")
    search_fields = ("original_filename", "session__title", "card__player_name")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("session", "card")


@admin.register(CardVaultLocation)
class CardVaultLocationAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "sort_order", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "description")
    autocomplete_fields = ("parent",)


@admin.register(CardVaultValuation)
class CardVaultValuationAdmin(admin.ModelAdmin):
    list_display = ("card", "source", "amount", "currency", "confidence", "valuation_date", "created_at")
    list_filter = ("source", "currency", "valuation_date")
    search_fields = ("card__player_name", "card__team", "notes")
    readonly_fields = ("created_at",)
    autocomplete_fields = ("card",)


class GergVaultTenantMembershipInline(admin.TabularInline):
    model = GergVaultTenantMembership
    extra = 0
    autocomplete_fields = ("user",)


@admin.register(GergVaultTenant)
class GergVaultTenantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created_by", "created_at")
    search_fields = ("name", "slug", "created_by__username", "created_by__email")
    readonly_fields = ("created_at", "updated_at")
    autocomplete_fields = ("created_by",)
    inlines = [GergVaultTenantMembershipInline]


@admin.register(GergVaultUserProfile)
class GergVaultUserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "email_verified", "verification_sent_at", "verified_at", "created_at")
    list_filter = ("email_verified", "created_at", "verified_at")
    search_fields = ("user__username", "user__email", "verification_token")
    readonly_fields = ("verification_token", "created_at", "updated_at")
    autocomplete_fields = ("user",)


@admin.register(GergVaultTrafficEvent)
class GergVaultTrafficEventAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "event_type",
        "user",
        "method",
        "status_code",
        "duration_ms",
        "path",
        "ip_address",
    )
    list_filter = ("event_type", "status_code", "method", "created_at")
    search_fields = ("path", "route_name", "user__username", "ip_address", "user_agent", "referrer")
    readonly_fields = (
        "user",
        "session_key",
        "event_type",
        "path",
        "route_name",
        "method",
        "status_code",
        "duration_ms",
        "ip_address",
        "forwarded_for",
        "user_agent",
        "referrer",
        "host",
        "query_string_present",
        "created_at",
    )
    date_hierarchy = "created_at"
    list_select_related = ("user",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
