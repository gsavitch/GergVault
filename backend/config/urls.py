from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path


urlpatterns = [
    path("", lambda request: redirect("card_vault:dashboard"), name="root"),
    path("admin/", admin.site.urls),
    path("api/card-vault/", include(("card_vault.urls", "card_vault_api"), namespace="card_vault_api")),
    path("card-vault/", include(("card_vault.web_urls", "card_vault"), namespace="card_vault")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
