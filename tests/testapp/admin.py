from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib import admin

from django_converter_studio.admin import ConverterStudioAdminMixin, convert_with_converter_studio

from .models import Clip, Photo, Report

if TYPE_CHECKING:
    Base = admin.ModelAdmin[Any]
else:
    Base = admin.ModelAdmin


@admin.register(Photo)
class PhotoAdmin(ConverterStudioAdminMixin, Base):
    list_display = ("title", "image")


@admin.register(Report)
class ReportAdmin(Base):
    actions = (convert_with_converter_studio,)


admin.site.register(Clip)
