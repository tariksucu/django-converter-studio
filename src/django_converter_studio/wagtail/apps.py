from __future__ import annotations

from django.apps import AppConfig, apps
from django.utils.translation import gettext_lazy as _


class ConverterStudioWagtailConfig(AppConfig):
    name = "django_converter_studio.wagtail"
    label = "converter_studio_wagtail"
    verbose_name = _("Converter Studio for Wagtail")

    def ready(self) -> None:
        from ..rules import register
        from . import checks, receivers
        from .rules import document_rules, image_rules

        checks.register()
        receivers.connect()
        if apps.is_installed("wagtail.images"):
            from wagtail.images import get_image_model

            register(get_image_model(), *image_rules())
        if apps.is_installed("wagtail.documents"):
            from wagtail.documents import get_document_model

            register(get_document_model(), *document_rules())
