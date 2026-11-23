from __future__ import annotations

from django.apps import AppConfig


class TestAppConfig(AppConfig):
    name = "tests.testapp"
    label = "testapp"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from django_converter_studio import Rule, formats, register

        from .models import Clip

        register(Clip, Rule(field="video", sources=formats.VIDEO, to="mp4", run="task"))
