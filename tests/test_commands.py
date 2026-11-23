from __future__ import annotations

from io import StringIO

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management import CommandError, call_command
from django.test import override_settings

from django_converter_studio.models import ConversionJob

from .fake_api import FakeAPI
from .testapp.models import Photo, Report

pytestmark = pytest.mark.django_db


def stored(name: str) -> str:
    return default_storage.save(name, ContentFile(b"data"))


def run(*args: str) -> tuple[str, str]:
    out, err = StringIO(), StringIO()
    call_command("converter_studio_convert", *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def test_dry_run_lists_without_converting(api: FakeAPI) -> None:
    Photo.objects.bulk_create([Photo(image=stored("photos/a.heic")), Photo(image="photos/b.jpg")])
    Report.objects.bulk_create([Report(file=stored("reports/r.docx"))])
    out, _ = run("--dry-run")
    assert "photos/a.heic -> jpg (image)" in out
    assert "reports/r.docx -> pdf (pdf)" in out
    assert "b.jpg" not in out
    assert "2 objects would be converted" in out
    assert api.requests == []


def test_converting_existing_files(api: FakeAPI) -> None:
    Photo.objects.bulk_create([Photo(image=stored(f"photos/{n}.heic")) for n in "abc"])
    out, _ = run("testapp.Photo", "--limit", "2")
    assert out.count("-> photos/") == 2
    assert "2 objects handled; 2 credits used." in out
    out, _ = run("testapp.Photo")
    assert out.count("-> photos/") == 1
    out, _ = run("testapp.Photo")
    assert "0 objects handled" in out
    assert ConversionJob.objects.filter(status="done").count() == 3


def test_failures_end_in_an_error(api: FakeAPI) -> None:
    Photo.objects.bulk_create([Photo(image=stored("photos/broken.heic"))])
    with pytest.raises(CommandError, match="1 conversions failed"):
        run()


def test_queue_hands_them_to_the_tasks_framework(api: FakeAPI) -> None:
    Report.objects.bulk_create([Report(file=stored("reports/r.docx"))])
    out, _ = run("testapp.Report", "--field", "file")
    assert "-> reports/pdf/r.pdf" in out
    out, _ = run("testapp.Report", "--force", "--dry-run")
    assert "1 objects would be converted" in out


def test_unknown_models_are_refused() -> None:
    with pytest.raises(CommandError, match="No model"):
        run("testapp.Nothing")
    with pytest.raises(CommandError, match="has no Converter Studio rules"):
        run("auth.User")


def test_account(api: FakeAPI) -> None:
    out = StringIO()
    call_command("converter_studio_account", stdout=out)
    assert "Plan: pro, 1099 credits left (renews 2026-12-22)" in out.getvalue()
    assert "dev@example.com" not in out.getvalue()
    with (
        override_settings(CONVERTER_STUDIO_API_KEY="cvs_live_wrong"),
        pytest.raises(CommandError, match="This API key does not work"),
    ):
        call_command("converter_studio_account", stdout=StringIO())
