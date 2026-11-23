"""``manage.py converter_studio_convert``: convert files already stored, by the models' rules."""

from __future__ import annotations

import posixpath
from typing import Any

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import models
from django.db.models import Q

from django_converter_studio.jobs import convert_instance, matching_rules
from django_converter_studio.models import ConversionJob
from django_converter_studio.rules import models_with_rules, rules_for

Status = ConversionJob.Status


class Command(BaseCommand):
    help = (
        "Converts the files already stored by the Converter Studio rules of the given models "
        "(app_label.ModelName), or of every model that has rules. Files converted already "
        "(a replaced file, a filled target) are skipped."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("models", nargs="*", metavar="app_label.ModelName")
        parser.add_argument("--field", action="append", help="only this file field (repeatable)")
        parser.add_argument("--limit", type=int, default=0, help="convert at most this many files")
        parser.add_argument(
            "--force", action="store_true", help="convert again into filled targets"
        )
        parser.add_argument("--queue", action="store_true", help="queue them as tasks instead")
        parser.add_argument("--dry-run", action="store_true", help="list what would be converted")

    def _models(self, labels: list[str]) -> list[type[models.Model]]:
        if not labels:
            return models_with_rules()
        chosen = []
        for label in labels:
            try:
                model = apps.get_model(label)
            except (LookupError, ValueError) as error:
                raise CommandError(f"No model {label!r} (use app_label.ModelName)") from error
            if not rules_for(model):
                raise CommandError(f"{label} has no Converter Studio rules")
            chosen.append(model)
        return chosen

    def handle(self, *args: Any, **options: Any) -> None:
        fields = set(options["field"]) if options["field"] else None
        limit = max(0, options["limit"])
        run = "task" if options["queue"] else "inline"
        count = failed = credits = 0
        for model in self._models(options["models"]):
            candidates = Q()
            for rule in rules_for(model):
                if fields is None or rule.field in fields:
                    for ext in rule.sources:
                        candidates |= Q(**{f"{rule.field}__iendswith": f".{ext}"})
            if not candidates:
                continue
            for obj in model._default_manager.filter(candidates).order_by("pk").iterator():
                rules = matching_rules(obj, fields=fields, force=options["force"])
                if not rules:
                    continue
                if limit and count >= limit:
                    break
                label = f"{model._meta.label} {obj.pk}"
                if options["dry_run"]:
                    for rule in rules:
                        source = getattr(obj, rule.field).name
                        where = rule.target or rule.field
                        self.stdout.write(f"{label}: {source} -> {rule.to} ({where})")
                    count += 1
                    continue
                for job in convert_instance(obj, fields=fields, force=options["force"], run=run):
                    name = posixpath.basename(job.source_name)
                    if job.status == Status.DONE:
                        credits += job.credits or 0
                        self.stdout.write(
                            f"{label}: {name} -> {job.result_name} ({job.credits or 0} credits)"
                        )
                    elif job.status == Status.FAILED:
                        failed += 1
                        self.stderr.write(f"{label}: {name} not converted: {job.error_message}")
                    elif job.status == Status.SKIPPED:
                        self.stderr.write(f"{label}: {name} skipped: {job.error_message}")
                    else:
                        self.stdout.write(f"{label}: {name} queued")
                count += 1
        verb = "would be converted" if options["dry_run"] else "handled"
        self.stdout.write(f"{count} objects {verb}; {credits} credits used.")
        if failed:
            raise CommandError(f"{failed} conversions failed (see Admin > Converter Studio)")
