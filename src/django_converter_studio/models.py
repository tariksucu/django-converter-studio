"""The conversions log: one row per file converted by a rule (Admin > Converter Studio)."""

from __future__ import annotations

import uuid
from typing import Any

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import gettext_lazy as _


class ConversionJob(models.Model):
    """A file of an object converted by one of its model's rules."""

    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        RUNNING = "running", _("Running")
        DONE = "done", _("Done")
        FAILED = "failed", _("Failed")
        SKIPPED = "skipped", _("Skipped")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, verbose_name=_("content type")
    )
    object_id = models.CharField(_("object id"), max_length=255)
    content_object = GenericForeignKey("content_type", "object_id")
    field = models.CharField(_("field"), max_length=100)
    rule = models.CharField(_("rule"), max_length=200)
    source_name = models.CharField(_("file"), max_length=1024)
    to_format = models.CharField(_("to"), max_length=16)
    target = models.CharField(_("target field"), max_length=100, blank=True)
    status = models.CharField(
        _("status"), max_length=16, choices=Status.choices, default=Status.QUEUED, db_index=True
    )
    #: The API's conversion id (also its upload's id), kept so a retry never pays twice.
    conversion_id = models.CharField(_("conversion id"), max_length=64, blank=True)
    credits = models.PositiveIntegerField(_("credits"), null=True, blank=True)
    result_name = models.CharField(_("result"), max_length=1024, blank=True)
    #: The API's error code (``notEnoughCredits``, ``conversionFailed``...) or this package's
    #: (``missingApiKey``, ``connectionError``, ``timeout``, ``confirmationRequired``,
    #: ``sourceUnreadable``, ``storageError``, ``objectDeleted``, ``fileChanged``, ``noFile``,
    #: ``ruleRemoved``).
    error_code = models.CharField(_("error code"), max_length=64, blank=True)
    error_message = models.TextField(_("error"), blank=True)
    attempts = models.PositiveSmallIntegerField(_("attempts"), default=0)
    created_at = models.DateTimeField(_("created"), auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(_("started"), null=True, blank=True)
    finished_at = models.DateTimeField(_("finished"), null=True, blank=True)

    class Meta:
        verbose_name = _("conversion")
        verbose_name_plural = _("conversions")
        ordering = ("-created_at",)
        indexes = (models.Index(fields=["content_type", "object_id"]),)

    def __str__(self) -> str:
        return f"{self.source_name} -> {self.to_format} ({self.get_status_display()})"

    @property
    def is_open(self) -> bool:
        """Queued or running: not to be started a second time."""
        return self.status in (self.Status.QUEUED, self.Status.RUNNING)

    def get_object(self) -> Any:
        """The converted object, or ``None`` when it was deleted."""
        model = self.content_type.model_class()
        if model is None:
            return None
        return model._base_manager.filter(pk=self.object_id).first()
