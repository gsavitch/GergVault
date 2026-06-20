from django.urls import path

from card_vault import views

app_name = "card_vault"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("pricing/dashboard/", views.pricing_dashboard, name="pricing-dashboard"),
    path("cards/<int:card_id>/", views.card_detail, name="card-detail"),
    path("cards/<int:card_id>/valuations/", views.card_valuations, name="card-valuations"),
    path("cards/<int:card_id>/enrich/", views.run_card_ai_enrichment, name="card-ai-enrich"),
    path("cards/<int:card_id>/update-value/", views.update_card_value, name="card-update-value"),
    path("intake/<uuid:session_id>/review/", views.intake_review, name="intake-review"),
    path("intake/<uuid:session_id>/update-values/", views.update_session_values, name="intake-update-values"),
    path(
        "intake/<uuid:session_id>/extract/",
        views.run_ai_extraction_from_review,
        name="intake-run-ai-extraction",
    ),
    path(
        "intake/<uuid:session_id>/extract/status/",
        views.ai_extraction_status,
        name="intake-ai-extraction-status",
    ),
    path(
        "intake/<uuid:session_id>/recrop/",
        views.regenerate_crops_from_review,
        name="intake-regenerate-crops",
    ),
    path(
        "intake/<uuid:session_id>/cards/<int:card_id>/",
        views.update_card_from_review,
        name="review-card-update",
    ),
]
