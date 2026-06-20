from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import TemplateView

from card_vault import views as card_vault_views


urlpatterns = [
    path("", TemplateView.as_view(template_name="landing.html"), name="root"),
    path("accounts/signup/", card_vault_views.signup, name="signup"),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
    path("api/card-vault/", include(("card_vault.urls", "card_vault_api"), namespace="card_vault_api")),
    path("card-vault/", include(("card_vault.web_urls", "card_vault"), namespace="card_vault")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
