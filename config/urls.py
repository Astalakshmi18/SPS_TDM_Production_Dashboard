from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("branches/", include("apps.branches.urls")),
    path("projects/", include("apps.projects.urls")),
    path("inventory/", include("apps.inventory.urls")),
    path("mapping/", include("apps.mapping.urls")),
    path("", include("apps.dashboard.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
