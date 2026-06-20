from django.conf import settings
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, re_path
from django.views.static import serve
from django.views.generic import TemplateView

from card_vault import views as card_vault_views


urlpatterns = [
    path("", TemplateView.as_view(template_name="landing.html"), name="root"),
    path("privacy/", TemplateView.as_view(template_name="privacy.html"), name="privacy"),
    path("terms/", TemplateView.as_view(template_name="terms.html"), name="terms"),
    path("accounts/signup/", card_vault_views.signup, name="signup"),
    path("accounts/verify-email/<uuid:token>/", card_vault_views.verify_email, name="verify-email"),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path(
        "accounts/password-reset/",
        auth_views.PasswordResetView.as_view(template_name="registration/password_reset.html"),
        name="password_reset",
    ),
    path(
        "accounts/password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(template_name="registration/password_reset_done.html"),
        name="password_reset_done",
    ),
    path(
        "accounts/reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(template_name="registration/password_reset_confirm.html"),
        name="password_reset_confirm",
    ),
    path(
        "accounts/reset/done/",
        auth_views.PasswordResetCompleteView.as_view(template_name="registration/password_reset_complete.html"),
        name="password_reset_complete",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
    path("api/card-vault/", include(("card_vault.urls", "card_vault_api"), namespace="card_vault_api")),
    path("card-vault/", include(("card_vault.web_urls", "card_vault"), namespace="card_vault")),
]

if settings.GERGVAULT_SERVE_MEDIA:
    urlpatterns += [
        re_path(
            r"^media/(?P<path>.*)$",
            serve,
            {"document_root": settings.MEDIA_ROOT},
            name="gergvault-media",
        )
    ]
