"""URL configuration for the HomoRepeat web project."""

from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("", include("apps.core.urls")),
    path("admin/", admin.site.urls),
    path("browser/", include("apps.browser.urls")),
    path("imports/", include("apps.imports.urls")),
]
