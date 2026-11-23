from __future__ import annotations

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class ConverterStudioConfig(AppConfig):
    name = "django_converter_studio"
    label = "converter_studio"
    verbose_name = _("Converter Studio")
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from . import checks, signals

        checks.register()
        signals.connect()
