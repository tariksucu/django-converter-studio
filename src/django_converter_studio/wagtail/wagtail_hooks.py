"""A "Convert with Converter Studio" bulk action on the image and document listings."""

from __future__ import annotations

from functools import cache
from typing import Any

from django.apps import apps
from django.template import engines
from django.template.backends.django import DjangoTemplates
from django.template.response import TemplateResponse
from django.utils.translation import gettext_lazy as _
from wagtail import hooks

from ..jobs import convert_instance
from ..reports import report
from ..rules import rules_for

# The confirmation page, on Wagtail's own confirmation layout. Kept here rather than in a .html
# file: Django template tags must stay on one line, which HTML formatters do not respect.
CONFIRMATION = """\
{% extends "wagtailadmin/bulk_actions/confirmation/base.html" %}
{% load i18n wagtailadmin_tags %}

{% block titletag %}{% blocktrans trimmed count counter=items|length %}
  Convert 1 file with Converter Studio
{% plural %}
  Convert {{ counter }} files with Converter Studio
{% endblocktrans %}{% endblock %}

{% block header %}
  {% trans "Convert with Converter Studio" as title_str %}
  {% include "wagtailadmin/shared/header.html" with title=title_str icon="cog" %}
{% endblock header %}

{% block items_with_access %}
  {% if items %}
    <p>{% blocktrans trimmed %}
      Converter Studio converts each selected file whose format has a rule, in place: the file
      keeps its title, collection and tags. Each conversion uses credits of the Converter Studio
      account; files in other formats are left as they are.
    {% endblocktrans %}</p>
    <ul>
      {% for rule in converter_studio_rules %}
        <li>{{ rule.sources }} &rarr; {{ rule.to }}</li>
      {% endfor %}
    </ul>
    <p>{% trans "Selected files:" %}</p>
    <ul>
      {% for entry in items %}
        <li>{{ entry.item.title }} ({{ entry.item.file.name }})</li>
      {% endfor %}
    </ul>
  {% endif %}
{% endblock items_with_access %}

{% block items_with_no_access %}
  {% blocktrans trimmed asvar no_access_msg count counter=items_with_no_access|length %}
    You don't have permission to change this file
  {% plural %}
    You don't have permission to change these files
  {% endblocktrans %}
  {% with items=items_with_no_access %}
    {% include "wagtailadmin/bulk_actions/confirmation/list_items_with_no_access.html" %}
  {% endwith %}
{% endblock items_with_no_access %}

{% block form_section %}
  {% if items %}
    {% trans "Yes, convert" as action_button_text %}
    {% trans "No, don't convert" as no_action_button_text %}
    {% include "wagtailadmin/bulk_actions/confirmation/form.html" %}
  {% else %}
    {% include "wagtailadmin/bulk_actions/confirmation/go_back.html" %}
  {% endif %}
{% endblock form_section %}
"""


@cache
def confirmation_template() -> Any:
    engine = next(e for e in engines.all() if isinstance(e, DjangoTemplates))
    return engine.from_string(CONFIRMATION)


class ConvertBulkActionMixin:
    """Converts the selected files by their model's rules (inline, or queued as tasks)."""

    display_name = _("Convert with Converter Studio")
    action_type = "convert_with_converter_studio"
    aria_label = _("Convert the selected files with Converter Studio")
    template_name = "wagtailadmin/bulk_actions/confirmation/base.html"  # see render_to_response
    action_priority = 60

    def render_to_response(self, context: dict[str, Any], **kwargs: Any) -> TemplateResponse:
        request: Any = getattr(self, "request")  # noqa: B009
        return TemplateResponse(request, confirmation_template(), context, **kwargs)

    def check_perm(self, obj: Any) -> bool:
        policy: Any = getattr(self, "permission_policy")  # noqa: B009 (set by Wagtail's base)
        request: Any = getattr(self, "request")  # noqa: B009
        return bool(policy.user_has_permission_for_instance(request.user, "change", obj))

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context: dict[str, Any] = super().get_context_data(**kwargs)  # type: ignore[misc]
        model: Any = getattr(self, "model")  # noqa: B009
        context["converter_studio_rules"] = [
            {"sources": ", ".join(sorted(rule.sources)).upper(), "to": rule.to.upper()}
            for rule in rules_for(model)
        ]
        return context

    def prepare_action(self, objects: Any, objects_without_access: Any) -> None:
        # Before Wagtail's transaction: the conversions talk to the API and save files.
        request: Any = getattr(self, "request")  # noqa: B009
        jobs = [job for obj in objects for job in convert_instance(obj)]
        report(
            request,
            jobs,
            nothing=str(
                _(
                    "Nothing to convert: none of the selected files is in a format that "
                    "Converter Studio converts here, or it has been converted already."
                )
            ),
        )

    @classmethod
    def execute_action(cls, objects: Any, **kwargs: Any) -> tuple[int, int]:
        return len(objects), 0

    def get_success_message(self, num_parent_objects: int, num_child_objects: int) -> None:
        return None


if apps.is_installed("wagtail.documents"):
    from wagtail.documents import get_document_model
    from wagtail.documents.views.bulk_actions.document_bulk_action import DocumentBulkAction

    if rules_for(get_document_model()):

        @hooks.register("register_bulk_action")
        class ConvertDocumentsBulkAction(ConvertBulkActionMixin, DocumentBulkAction):  # type: ignore[misc]
            pass


if apps.is_installed("wagtail.images"):
    from wagtail.images import get_image_model
    from wagtail.images.views.bulk_actions.image_bulk_action import ImageBulkAction

    if rules_for(get_image_model()):

        @hooks.register("register_bulk_action")
        class ConvertImagesBulkAction(ConvertBulkActionMixin, ImageBulkAction):  # type: ignore[misc]
            pass
