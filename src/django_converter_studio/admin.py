"""The admin: the conversions log, and the "Convert with Converter Studio" action for your models.

from django_converter_studio.admin import ConverterStudioAdminMixin, convert_with_converter_studio

@admin.register(Photo)
class PhotoAdmin(ConverterStudioAdminMixin, admin.ModelAdmin):  # adds the action
    ...

# or: actions = [convert_with_converter_studio]
"""

from __future__ import annotations

import posixpath
from typing import TYPE_CHECKING, Any

from django.contrib import admin
from django.db.models import Model, QuerySet
from django.http import HttpRequest
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html
from django.utils.text import Truncator
from django.utils.translation import gettext_lazy as _

from .jobs import convert_instance, retry
from .models import ConversionJob
from .reports import report

__all__ = [
    "ConversionJobAdmin",
    "ConverterStudioAdminMixin",
    "convert_with_converter_studio",
    "report",
]

if TYPE_CHECKING:
    _JobAdmin = admin.ModelAdmin[ConversionJob]
else:
    _JobAdmin = admin.ModelAdmin


@admin.action(description=_("Convert with Converter Studio"), permissions=["change"])
def convert_with_converter_studio(
    modeladmin: admin.ModelAdmin[Any], request: HttpRequest, queryset: QuerySet[Model]
) -> None:
    """Converts the selected objects' files by their model's rules (inline, or queued)."""
    jobs = [job for obj in queryset for job in convert_instance(obj)]
    report(
        request,
        jobs,
        nothing=str(
            _(
                "Nothing to convert: no file of the selected objects matches a Converter Studio "
                "rule, or it has been converted already."
            )
        ),
    )


if hasattr(admin, "ActionLocation"):
    # Django 6.1 can offer an action on an object's own page too (what @admin.action(location=)
    # sets; older versions have no such argument).
    convert_with_converter_studio.locations = [  # type: ignore[attr-defined]
        admin.ActionLocation.CHANGE_LIST,
        admin.ActionLocation.CHANGE_FORM,
    ]


class ConverterStudioAdminMixin:
    """Adds the "Convert with Converter Studio" action to a ``ModelAdmin``."""

    def get_actions(self, request: HttpRequest, action_location: Any = None) -> dict[str, Any]:
        parent: Any = super()
        model_admin: Any = self
        if action_location is None:  # Django 5.2 and 6.0
            actions: dict[str, Any] = parent.get_actions(request)
            action = model_admin.get_action(convert_with_converter_studio)
        else:  # Django 6.1: the change list or an object's own page
            actions = parent.get_actions(request, action_location=action_location)
            action = model_admin.get_action(convert_with_converter_studio, action_location)
        name = "convert_with_converter_studio"
        if (
            name not in actions
            and action is not None
            and model_admin.has_change_permission(request)
        ):
            actions[name] = action
        return actions


@admin.register(ConversionJob)
class ConversionJobAdmin(_JobAdmin):
    list_display = (
        "created_at",
        "file",
        "converted_object",
        "to_format",
        "status",
        "credits",
        "reason",
    )
    list_filter = ("status", "to_format", "error_code", "content_type")
    search_fields = ("object_id", "source_name", "result_name", "error_code", "error_message")
    date_hierarchy = "created_at"
    actions = ("convert_again", "approve_and_convert")
    readonly_fields = (
        "id",
        "content_type",
        "object_id",
        "converted_object",
        "field",
        "rule",
        "source_name",
        "to_format",
        "target",
        "status",
        "conversion_id",
        "credits",
        "result_name",
        "error_code",
        "error_message",
        "attempts",
        "created_at",
        "started_at",
        "finished_at",
    )
    fields = readonly_fields

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    @admin.display(description=_("file"), ordering="source_name")
    def file(self, job: ConversionJob) -> str:
        return posixpath.basename(job.source_name)

    @admin.display(description=_("object"))
    def converted_object(self, job: ConversionJob) -> Any:
        label = f"{job.content_type.name} {job.object_id}"
        try:
            url = reverse(
                f"admin:{job.content_type.app_label}_{job.content_type.model}_change",
                args=[job.object_id],
            )
        except NoReverseMatch:
            return label
        return format_html('<a href="{}">{}</a>', url, label)

    @admin.display(description=_("reason"))
    def reason(self, job: ConversionJob) -> str:
        return Truncator(job.error_message).chars(120)

    @admin.action(description=_("Convert again"), permissions=["change"])
    def convert_again(self, request: HttpRequest, queryset: QuerySet[ConversionJob]) -> None:
        jobs = list(queryset)
        retry(jobs)
        report(
            request,
            ConversionJob.objects.filter(pk__in=[job.pk for job in jobs]),
            nothing=str(_("Nothing selected.")),
        )

    @admin.action(
        description=_("Approve the price and convert (over the credit limit)"),
        permissions=["change"],
    )
    def approve_and_convert(self, request: HttpRequest, queryset: QuerySet[ConversionJob]) -> None:
        jobs = list(queryset.filter(error_code="confirmationRequired"))
        retry(jobs, approve=True)
        report(
            request,
            ConversionJob.objects.filter(pk__in=[job.pk for job in jobs]),
            nothing=str(_("None of the selected conversions waits for a price approval.")),
        )
