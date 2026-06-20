from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView


urlpatterns = [
    path("", TemplateView.as_view(template_name="landing.html"), name="root"),
    path("admin/", admin.site.urls),
    path("api/card-vault/", include(("card_vault.urls", "card_vault_api"), namespace="card_vault_api")),
    path("card-vault/", include(("card_vault.web_urls", "card_vault"), namespace="card_vault")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
