"""System checks (``manage.py check``) for the settings and every model's rules."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit

from django.apps import AppConfig, apps
from django.conf import settings
from django.core import checks
from django.core.exceptions import FieldDoesNotExist
from django.db import models

from . import conf, tasks
from .formats import TEXT_TARGETS
from .rules import Rule, rules_for

TAG = "converter_studio"
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def check_settings(app_configs: Sequence[AppConfig] | None = None, **kwargs: Any) -> list[Any]:
    found: list[Any] = []
    key = conf.api_key()
    if key is None:
        found.append(
            checks.Warning(
                "No Converter Studio API key: files are not converted.",
                hint="Set CONVERTER_STUDIO_API_KEY in the settings or the environment; create a "
                "key at https://converter.studio/account#api-keys.",
                id="converter_studio.W001",
            )
        )
    elif not key.startswith("cvs_"):
        found.append(
            checks.Warning(
                "CONVERTER_STUDIO_API_KEY does not look like a Converter Studio API key.",
                hint="Keys start with cvs_live_; copy it again from your account page.",
                id="converter_studio.W002",
            )
        )
    url = urlsplit(conf.base_url())
    if url.scheme not in ("http", "https") or not url.netloc:
        found.append(
            checks.Error(
                "CONVERTER_STUDIO_BASE_URL is not an http:// or https:// address: "
                f"{conf.base_url()!r}",
                id="converter_studio.E001",
            )
        )
    elif url.scheme == "http" and (url.hostname or "") not in _LOCAL_HOSTS:
        found.append(
            checks.Warning(
                "CONVERTER_STUDIO_BASE_URL uses plain http://: the API key would travel "
                "unencrypted.",
                hint="Use https://converter.studio/api.",
                id="converter_studio.W003",
            )
        )
    credits = conf.max_credits()
    if isinstance(credits, bool) or not isinstance(credits, int) or credits < 0:
        found.append(
            checks.Error(
                "CONVERTER_STUDIO_MAX_CREDITS must be a whole number, 0 or more.",
                id="converter_studio.E002",
            )
        )
    for name in ("TIMEOUT", "UPLOAD_TIMEOUT"):
        value = getattr(settings, f"CONVERTER_STUDIO_{name}", 1)
        if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
            found.append(
                checks.Error(
                    f"CONVERTER_STUDIO_{name} must be a number of seconds above 0.",
                    id="converter_studio.E003",
                )
            )
    if conf.run_mode() not in conf.RUN_MODES:
        found.append(
            checks.Error(
                "CONVERTER_STUDIO_RUN must be 'auto', 'inline' or 'task'.",
                id="converter_studio.E004",
            )
        )
    elif conf.run_mode() == "task" and not tasks.available():
        found.append(
            checks.Warning(
                "CONVERTER_STUDIO_RUN is 'task' but there is no tasks framework to use: "
                "conversions run inline.",
                hint="Use Django 6.0 or later, or install django-tasks, and configure TASKS.",
                id="converter_studio.W004",
            )
        )
    if not apps.is_installed("django.contrib.contenttypes"):
        found.append(
            checks.Error(
                "django_converter_studio needs django.contrib.contenttypes in INSTALLED_APPS.",
                id="converter_studio.E005",
            )
        )
    return found


def _rule_errors(model: type[models.Model], rule: Rule) -> list[str]:
    errors = list(rule.problems())
    try:
        source = model._meta.get_field(rule.field)
    except FieldDoesNotExist:
        return [*errors, f"there is no field {rule.field!r}"]
    if not isinstance(source, models.FileField):
        errors.append(f"{rule.field!r} is not a FileField")
    if rule.target:
        try:
            target = model._meta.get_field(rule.target)
        except FieldDoesNotExist:
            return [*errors, f"there is no target field {rule.target!r}"]
        if isinstance(target, models.FileField):
            pass
        elif isinstance(target, models.TextField | models.CharField):
            if rule.to not in TEXT_TARGETS:
                errors.append(f"text field {rule.target!r} needs a text format, not {rule.to!r}")
        else:
            errors.append(f"target {rule.target!r} is neither a file nor a text field")
    return errors


def check_rules(app_configs: Sequence[AppConfig] | None = None, **kwargs: Any) -> list[Any]:
    found: list[Any] = []
    for model in apps.get_models():
        if (
            app_configs is not None
            and apps.get_app_config(model._meta.app_label) not in app_configs
        ):
            continue
        rules = rules_for(model)
        names = [rule.name for rule in rules]
        for rule in rules:
            if names.count(rule.name) > 1:
                found.append(
                    checks.Error(
                        f"Two Converter Studio rules are named {rule.name!r}.",
                        hint="Give each rule its own name=.",
                        obj=model,
                        id="converter_studio.E011",
                    )
                )
            found.extend(
                checks.Error(
                    f"Converter Studio rule {rule.name!r}: {error}.",
                    obj=model,
                    id="converter_studio.E010",
                )
                for error in _rule_errors(model, rule)
            )
            if rule.run == "task" and not tasks.available():
                found.append(
                    checks.Warning(
                        f"Converter Studio rule {rule.name!r} has run='task' but there is no "
                        "tasks framework to use: it runs inline.",
                        obj=model,
                        id="converter_studio.W010",
                    )
                )
    return found


def register() -> None:
    checks.register(check_settings, TAG)
    checks.register(check_rules, TAG)
