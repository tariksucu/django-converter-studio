from __future__ import annotations

from typing import Any

import django
import pytest
from django.contrib.messages import get_messages
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from django_converter_studio.models import ConversionJob

from .fake_api import FakeAPI
from .testapp.models import Photo, Report

pytestmark = pytest.mark.django_db
Status = ConversionJob.Status


def stored(name: str, data: bytes = b"data") -> str:
    return default_storage.save(name, ContentFile(data))


def test_an_upload_through_the_admin_is_converted(
    api: FakeAPI, admin_client: Client, django_capture_on_commit_callbacks: Any
) -> None:
    # The admin saves in a transaction; the conversion runs once it is committed.
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            reverse("admin:testapp_photo_add"),
            {"title": "Beach", "image": SimpleUploadedFile("IMG_0001.HEIC", b"heic")},
        )
    assert response.status_code == 302
    photo = Photo.objects.get()
    assert photo.image.name == "photos/IMG_0001.jpg"
    assert ConversionJob.objects.get().status == Status.DONE


def test_the_action_converts_existing_files(api: FakeAPI, admin_client: Client) -> None:
    Photo.objects.bulk_create(
        [Photo(title="a", image=stored("photos/a.heic")), Photo(title="b", image="photos/b.jpg")]
    )
    Photo.objects.bulk_create([Photo(title="c", image=stored("photos/broken.heic"))])
    response = admin_client.post(
        reverse("admin:testapp_photo_changelist"),
        {
            "action": "convert_with_converter_studio",
            "_selected_action": [str(pk) for pk in Photo.objects.values_list("pk", flat=True)],
        },
        follow=True,
    )
    texts = [str(m) for m in get_messages(response.wsgi_request)]
    assert "Converted 1 file (1 credits)." in texts
    assert any(t.startswith("broken.heic was not converted: This file could not") for t in texts)
    assert Photo.objects.get(title="a").image.name == "photos/a.jpg"


def test_the_action_on_a_plain_actions_list(api: FakeAPI, admin_client: Client) -> None:
    Report.objects.bulk_create([Report(file="reports/a.zip")])
    response = admin_client.post(
        reverse("admin:testapp_report_changelist"),
        {"action": "convert_with_converter_studio", "_selected_action": [Report.objects.get().pk]},
        follow=True,
    )
    texts = [str(m) for m in get_messages(response.wsgi_request)]
    assert len(texts) == 1
    assert texts[0].startswith("Nothing to convert")


def test_the_conversions_log(api: FakeAPI, admin_client: Client) -> None:
    api.credits = 40
    Photo.objects.bulk_create([Photo(title="a", image=stored("photos/big.heic"))])
    Photo.objects.get().convert_files()
    job = ConversionJob.objects.get()
    assert job.error_code == "confirmationRequired"
    page = admin_client.get(reverse("admin:converter_studio_conversionjob_changelist"))
    assert page.status_code == 200
    assert b"big.heic" in page.content
    assert b"costs 40 credits" in page.content
    detail = admin_client.get(reverse("admin:converter_studio_conversionjob_change", args=[job.pk]))
    assert detail.status_code == 200
    assert reverse("admin:testapp_photo_change", args=[job.object_id]).encode() in detail.content
    url = reverse("admin:converter_studio_conversionjob_changelist")
    admin_client.post(url, {"action": "convert_again", "_selected_action": [str(job.pk)]})
    job.refresh_from_db()
    assert job.status == Status.FAILED
    response = admin_client.post(
        url, {"action": "approve_and_convert", "_selected_action": [str(job.pk)]}, follow=True
    )
    job.refresh_from_db()
    assert job.status == Status.DONE
    assert "Converted 1 file (40 credits)." in [str(m) for m in get_messages(response.wsgi_request)]
    assert admin_client.get(reverse("admin:converter_studio_conversionjob_add")).status_code == 403


@pytest.mark.skipif(django.VERSION < (6, 1), reason="change form actions came in Django 6.1")
def test_the_action_on_an_objects_own_page(api: FakeAPI, admin_client: Client) -> None:
    Photo.objects.bulk_create([Photo(title="a", image=stored("photos/a.heic"))])
    photo = Photo.objects.get()
    page = admin_client.get(reverse("admin:testapp_photo_change", args=[photo.pk]))
    assert b"Convert with Converter Studio" in page.content
