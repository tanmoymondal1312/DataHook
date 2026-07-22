"""Root URL configuration for DataHook.

  /api/...        -> JWT-protected admin API (accounts + endpoints)
  /ingest/{slug}/ -> public data ingest (API-key authenticated, no JWT)
  /admin/         -> Django admin site
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from endpoints.ingest import IngestView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("accounts.urls")),
    path("api/", include("endpoints.urls")),
    # Public ingest — deliberately outside /api/ and JWT-free.
    path("ingest/<slug:slug>/", IngestView.as_view(), name="ingest"),
]

# In production nginx serves /media/ directly; this is only for local dev.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
