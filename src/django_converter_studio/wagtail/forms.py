"""The image form that converts an upload before Wagtail checks it.

``WAGTAILIMAGES_IMAGE_FORM_BASE = "django_converter_studio.wagtail.forms.ConvertingImageForm"``,
or, with a base form of your own: ``class MyImageForm(ConvertingImageFormMixin, BaseImageForm)``.

Every upload path of the admin uses it: "Add an image", "Add images" (several at once), the image
chooser's upload tab and replacing an image's file.
"""

from __future__ import annotations

import logging
from typing import Any

from converter_studio import ConverterStudioError
from django.core.files.uploadedfile import InMemoryUploadedFile, UploadedFile
from django.utils.translation import gettext as _
from wagtail.images.forms import BaseImageForm

from .. import conf, services
from .rules import image_target

logger = logging.getLogger("django_converter_studio")


def convert_upload(upload: UploadedFile[Any], to: str) -> InMemoryUploadedFile:
    """The upload converted to ``to``, as an upload of its own (same field, the new name)."""
    result = services.convert(
        upload,
        to,
        file_name=upload.name,
        options=conf.wagtail_options().get(to, {}),
        timeout=conf.upload_timeout(),
    )
    data: Any = result.file.file
    return InMemoryUploadedFile(
        file=data,
        field_name=getattr(upload, "field_name", None),
        name=result.name,
        content_type=result.content_type,
        size=result.size,
        charset=None,
    )


class ConvertingImageFormMixin:
    """Converts an uploaded image that ``CONVERTER_STUDIO_WAGTAIL_IMAGES`` names (HEIC, RAW, EPS...)
    before the form's fields are checked, so Wagtail stores the converted image.

    When the conversion fails and Wagtail cannot take the original either, the upload is refused
    with Converter Studio's reason (no credits, a wrong API key...); when Wagtail can take the
    original (a HEIC with ``"heic"`` in ``WAGTAILIMAGES_EXTENSIONS``), it is kept.
    """

    converter_studio_error: str | None = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        form: Any = self
        field = form.fields.get("file")
        accept = field.widget.attrs.get("accept") if field is not None else None
        if accept:
            # File dialogs filter on "image/*", which hides RAW, EPS and AI files on many systems.
            extensions = ", ".join(f".{ext}" for ext in sorted(conf.wagtail_images()))
            field.widget.attrs["accept"] = f"{accept}, {extensions}"

    def full_clean(self) -> None:
        form: Any = self
        self.converter_studio_error = None
        key = form.add_prefix("file")
        upload = form.files.get(key) if form.is_bound and "file" in form.fields else None
        to = image_target(upload.name) if isinstance(upload, UploadedFile) and upload.name else None
        if upload is not None and to:
            try:
                converted = convert_upload(upload, to)
            except ConverterStudioError as error:
                self.converter_studio_error = _(
                    "%(file)s could not be converted to %(format)s by Converter Studio: %(reason)s"
                ) % {"file": upload.name, "format": to.upper(), "reason": error}
                logger.warning("Converter Studio: %s", self.converter_studio_error)
            else:
                files = form.files.copy()
                files[key] = converted
                form.files = files
        super().full_clean()  # type: ignore[misc]
        if self.converter_studio_error and form.has_error("file"):
            # Wagtail refused the original too: say why it was not converted instead.
            form.errors["file"] = form.error_class([self.converter_studio_error])


class ConvertingImageForm(ConvertingImageFormMixin, BaseImageForm):  # type: ignore[misc]
    """Wagtail's image form, converting uploads first."""
