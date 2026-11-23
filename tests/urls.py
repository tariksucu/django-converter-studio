from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.urls import include, path

from .settings import WAGTAIL

urlpatterns: list[Any] = [path("admin/", admin.site.urls)]

if WAGTAIL:
    from wagtail.admin import urls as wagtailadmin_urls
    from wagtail.documents import urls as wagtaildocs_urls

    urlpatterns += [
        path("cms/", include(wagtailadmin_urls)),
        path("documents/", include(wagtaildocs_urls)),
    ]
