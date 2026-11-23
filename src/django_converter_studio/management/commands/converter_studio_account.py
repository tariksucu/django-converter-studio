"""``manage.py converter_studio_account``: check the API key, show the plan and the credits left."""

from __future__ import annotations

from typing import Any

from converter_studio import ConverterStudioError
from django.core.management.base import BaseCommand, CommandError

from django_converter_studio import conf
from django_converter_studio.services import account


class Command(BaseCommand):
    help = "Checks the Converter Studio API key and shows the account's plan and credits."

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            info = account()
        except ConverterStudioError as error:
            raise CommandError(str(error)) from error
        renews = info.renews_at.date().isoformat() if info.renews_at else "-"
        self.stdout.write(f"API: {conf.base_url()}")
        self.stdout.write(f"Plan: {info.plan}, {info.credits} credits left (renews {renews})")
