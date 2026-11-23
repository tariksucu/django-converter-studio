"""Keeps Wagtail's own file details right when a stored image or document is converted in place."""

from __future__ import annotations

import logging
from typing import Any

from django.apps import apps

from ..rules import Rule
from ..signals import file_converted

logger = logging.getLogger("django_converter_studio")


def _refresh_file_details(sender: Any, instance: Any, rule: Rule, **kwargs: Any) -> None:
    if not rule.replaces or rule.field != "file":
        return
    is_image = is_document = False
    if apps.is_installed("wagtail.images"):
        from wagtail.images.models import AbstractImage

        is_image = isinstance(instance, AbstractImage)
    if apps.is_installed("wagtail.documents"):
        from wagtail.documents.models import AbstractDocument

        is_document = isinstance(instance, AbstractDocument)
    if not (is_image or is_document):
        return
    # Wagtail works these out again (and saves them) when they are empty.
    instance.file_size = None
    instance.file_hash = ""
    instance.get_file_size()
    instance.get_file_hash()
    if is_image:
        # Renditions were made from the original; Wagtail makes new ones on demand.
        instance.renditions.all().delete()


def connect() -> None:
    file_converted.connect(
        _refresh_file_details, dispatch_uid="django_converter_studio.wagtail.file_details"
    )
