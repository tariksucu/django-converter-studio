from __future__ import annotations

from typing import ClassVar

from django.db import models

from django_converter_studio import ConverterStudioMixin, Rule, formats


class Photo(ConverterStudioMixin, models.Model):
    """HEIC and RAW photos become JPG, in place."""

    title = models.CharField(max_length=100, blank=True)
    image = models.FileField(upload_to="photos/")

    converter_studio_rules: ClassVar[list[Rule]] = [
        Rule(field="image", sources=formats.HEIC + formats.RAW, to="jpg")
    ]

    def __str__(self) -> str:
        return self.title


class Report(ConverterStudioMixin, models.Model):
    """Office documents get a PDF next to them; PDFs and scans get their text read."""

    file = models.FileField(upload_to="reports/")
    pdf = models.FileField(upload_to="reports/pdf/", blank=True)
    text = models.TextField(blank=True)
    summary = models.CharField(max_length=10, blank=True)

    converter_studio_rules: ClassVar[list[Rule]] = [
        Rule(field="file", sources=formats.OFFICE, to="pdf", target="pdf"),
        Rule(
            field="file",
            sources=(*formats.OCR_IMAGES, "pdf"),
            to="txt",
            target="text",
            options={"ocr": True},
        ),
    ]

    def __str__(self) -> str:
        return self.file.name or ""


class Clip(models.Model):
    """Rules registered from outside the model (see apps.py): videos become MP4 as a task."""

    video = models.FileField(upload_to="clips/")

    def __str__(self) -> str:
        return self.video.name or ""


class Avatar(models.Model):
    """An ImageField whose size fields follow the converted file."""

    picture = models.ImageField(upload_to="avatars/", width_field="width", height_field="height")
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)

    converter_studio_rules: ClassVar[list[Rule]] = [
        Rule(field="picture", sources=formats.HEIC, to="jpg", delete_original=True)
    ]

    def __str__(self) -> str:
        return self.picture.name or ""
