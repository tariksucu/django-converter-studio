"""System checks for the Wagtail settings that uploads to be converted depend on."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.apps import AppConfig, apps
from django.conf import settings
from django.core import checks
from django.utils.module_loading import import_string

from .. import conf
from ..checks import TAG
from .rules import IMAGE_TARGETS

FORM = "django_converter_studio.wagtail.forms.ConvertingImageForm"
_DEFAULT_IMAGE_EXTENSIONS = ["avif", "gif", "jpg", "jpeg", "png", "webp"]


def check_wagtail(app_configs: Sequence[AppConfig] | None = None, **kwargs: Any) -> list[Any]:
    found: list[Any] = []
    if not apps.is_installed("django_converter_studio"):
        found.append(
            checks.Error(
                "django_converter_studio.wagtail needs django_converter_studio in INSTALLED_APPS.",
                id="converter_studio.E101",
            )
        )
    images = conf.wagtail_images()
    if images and apps.is_installed("wagtail.images"):
        from .forms import ConvertingImageFormMixin

        base = getattr(settings, "WAGTAILIMAGES_IMAGE_FORM_BASE", "")
        try:
            form = import_string(base) if base else None
        except ImportError:
            form = None
        if not (isinstance(form, type) and issubclass(form, ConvertingImageFormMixin)):
            found.append(
                checks.Warning(
                    "Wagtail checks uploaded images before Converter Studio sees them, so HEIC, "
                    "RAW and the other images in CONVERTER_STUDIO_WAGTAIL_IMAGES are refused.",
                    hint=f'Set WAGTAILIMAGES_IMAGE_FORM_BASE = "{FORM}" (or a form with '
                    "ConvertingImageFormMixin).",
                    id="converter_studio.W101",
                )
            )
        allowed = {
            ext.lower()
            for ext in getattr(settings, "WAGTAILIMAGES_EXTENSIONS", _DEFAULT_IMAGE_EXTENSIONS)
        }
        missing = sorted(source for source in images if source not in allowed)
        if missing:
            found.append(
                checks.Warning(
                    "The image uploader refuses these extensions before they can be converted: "
                    + ", ".join(missing)
                    + ".",
                    hint="Add them to WAGTAILIMAGES_EXTENSIONS, or remove them from "
                    "CONVERTER_STUDIO_WAGTAIL_IMAGES.",
                    id="converter_studio.W102",
                )
            )
        wrong = sorted({target for target in images.values() if target not in IMAGE_TARGETS})
        unaccepted = sorted({t for t in images.values() if t in IMAGE_TARGETS and t not in allowed})
        if wrong:
            found.append(
                checks.Error(
                    "CONVERTER_STUDIO_WAGTAIL_IMAGES converts images to formats Wagtail does not "
                    "render: " + ", ".join(wrong) + ".",
                    hint="Use jpg, png, webp, avif or gif.",
                    id="converter_studio.E102",
                )
            )
        if unaccepted:
            found.append(
                checks.Error(
                    "Images are converted to formats WAGTAILIMAGES_EXTENSIONS does not accept: "
                    + ", ".join(unaccepted)
                    + ".",
                    id="converter_studio.E103",
                )
            )
    documents = conf.wagtail_documents()
    allowed_documents = getattr(settings, "WAGTAILDOCS_EXTENSIONS", None)
    if documents and allowed_documents is not None:
        allowed_set = {ext.lower() for ext in allowed_documents}
        unaccepted = sorted({t for t in documents.values() if t not in allowed_set})
        if unaccepted:
            found.append(
                checks.Warning(
                    "Documents are converted to formats WAGTAILDOCS_EXTENSIONS does not accept: "
                    + ", ".join(unaccepted)
                    + ".",
                    id="converter_studio.W103",
                )
            )
    return found


def register() -> None:
    checks.register(check_wagtail, TAG)
