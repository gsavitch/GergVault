from django.urls import path

from card_vault import views

app_name = "card_vault"

urlpatterns = [
    path("intake/batch/", views.BatchCardIntakeView.as_view(), name="batch-intake"),
    path(
        "intake/sessions/<uuid:pk>/",
        views.CardVaultIntakeSessionDetailView.as_view(),
        name="intake-session-detail",
    ),
    path(
        "intake/sessions/<uuid:session_id>/cards/<int:card_id>/",
        views.CardVaultCardUpdateView.as_view(),
        name="intake-card-update",
    ),
    path(
        "intake/sessions/<uuid:session_id>/cards/<int:card_id>/approve/",
        views.CardVaultCardApproveView.as_view(),
        name="intake-card-approve",
    ),
    path(
        "cards/<int:card_id>/valuation-runs/",
        views.CardVaultCardValuationRunsView.as_view(),
        name="card-valuation-runs",
    ),
    path(
        "valuation-runs/<int:run_id>/",
        views.CardVaultValuationRunDetailView.as_view(),
        name="valuation-run-detail",
    ),
]
