from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

import httpx
import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from django_converter_studio import Rule, open_client, register, unregister
from django_converter_studio.jobs import STUCK_AFTER, convert_instance, retry, run_jobs
from django_converter_studio.models import ConversionJob
from django_converter_studio.signals import file_converted

from .conftest import jpeg_bytes
from .fake_api import FakeAPI
from .testapp.models import Avatar, Clip, Photo, Report

pytestmark = pytest.mark.django_db

Commit = Callable[..., AbstractContextManager[list[Callable[[], Any]]]]
Status = ConversionJob.Status


def upload(name: str, data: bytes = b"data") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, data)


def test_a_heic_upload_becomes_a_jpg_in_place(
    api: FakeAPI, django_capture_on_commit_callbacks: Commit
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        photo = Photo.objects.create(title="Beach", image=upload("IMG_0001.HEIC", b"heic"))
    assert photo.image.name == "photos/IMG_0001.jpg"  # the instance in hand follows
    photo.refresh_from_db()
    assert photo.image.name == "photos/IMG_0001.jpg"
    with default_storage.open(photo.image.name) as stored:
        assert stored.read() == api.outputs["jpg"]
    assert default_storage.exists("photos/IMG_0001.HEIC")  # originals are kept by default
    job = ConversionJob.objects.get()
    assert (job.status, job.credits, job.to_format) == (Status.DONE, 1, "jpg")
    assert job.source_name == "photos/IMG_0001.HEIC"
    assert job.result_name == "photos/IMG_0001.jpg"
    assert job.content_object == photo
    assert job.conversion_id == api.created()[0]["uploadId"]
    sent = [r.content for r in api.requests if r.method == "PUT"]
    assert sent == [b"heic"]


def test_nothing_happens_before_the_commit_and_for_other_files(
    api: FakeAPI, django_capture_on_commit_callbacks: Commit
) -> None:
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        Photo.objects.create(image=upload("IMG_0002.heic"))
    assert len(callbacks) == 1
    assert api.requests == []
    assert ConversionJob.objects.get().status == Status.QUEUED
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        photo = Photo.objects.create(image=upload("already.jpg"))
        photo.title = "renamed"
        photo.save()  # the file did not change
        photo.save(update_fields=["title"])
    assert callbacks == []
    assert ConversionJob.objects.count() == 1


def test_a_file_assigned_in_code_is_converted_too(
    api: FakeAPI, django_capture_on_commit_callbacks: Commit
) -> None:
    photo = Photo.objects.create(image=upload("a.jpg"))
    with django_capture_on_commit_callbacks(execute=True):
        photo.image = ContentFile(b"raw", name="DSC_1.NEF")
        photo.save()
    assert photo.image.name == "photos/DSC_1.jpg"


def test_documents_get_a_pdf_and_scans_their_text(
    api: FakeAPI, django_capture_on_commit_callbacks: Commit
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        report = Report.objects.create(file=upload("Q3 plan.docx"))
        scan = Report.objects.create(file=upload("scan.pdf"))
    report.refresh_from_db()
    scan.refresh_from_db()
    assert report.file.name == "reports/Q3_plan.docx"  # the storage cleans names
    assert report.pdf.name == "reports/pdf/Q3_plan.pdf"
    assert report.text == ""
    assert scan.text == "Hello 2026"
    assert scan.pdf.name == ""
    ocr = next(body for body in api.created() if body["to"] == "txt")
    assert ocr["options"] == {"ocr": True}


def test_a_failed_conversion_keeps_the_original_and_says_why(
    api: FakeAPI, django_capture_on_commit_callbacks: Commit
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        photo = Photo.objects.create(image=upload("broken.heic"))
    photo.refresh_from_db()
    assert photo.image.name == "photos/broken.heic"
    job = ConversionJob.objects.get()
    assert job.status == Status.FAILED
    assert job.error_code == "conversionFailed"
    assert "credits were given back" in job.error_message


@override_settings(CONVERTER_STUDIO_API_KEY="cvs_live_wrong")
def test_a_wrong_key_is_recorded(api: FakeAPI, django_capture_on_commit_callbacks: Commit) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        Photo.objects.create(image=upload("IMG.heic"))
    job = ConversionJob.objects.get()
    assert (job.status, job.error_code) == (Status.FAILED, "invalidApiKey")
    assert job.error_message == "This API key does not work."


@override_settings(CONVERTER_STUDIO_API_KEY="")
def test_no_key_is_recorded(api: FakeAPI, django_capture_on_commit_callbacks: Commit) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        Photo.objects.create(image=upload("IMG.heic"))
    job = ConversionJob.objects.get()
    assert (job.status, job.error_code) == (Status.FAILED, "missingApiKey")
    assert api.requests == []


def test_a_conversion_over_the_credit_limit_waits_for_approval(
    api: FakeAPI, django_capture_on_commit_callbacks: Commit
) -> None:
    api.credits = 25
    with django_capture_on_commit_callbacks(execute=True):
        photo = Photo.objects.create(image=upload("big.heic"))
    job = ConversionJob.objects.get()
    assert (job.status, job.error_code) == (Status.FAILED, "confirmationRequired")
    assert "25 credits" in job.error_message
    uploads = len(api.of("POST", "/api/v1/uploads"))
    assert retry([job]) == [Status.FAILED]  # without approval it stays as it is
    assert retry([job], approve=True) == [Status.DONE]
    assert len(api.of("POST", "/api/v1/uploads")) == uploads  # picked up, not sent again
    photo.refresh_from_db()
    assert photo.image.name == "photos/big.jpg"


def test_a_retry_picks_the_conversion_up_without_paying_twice(
    api: FakeAPI, django_capture_on_commit_callbacks: Commit
) -> None:
    down = [httpx.ConnectError("down")] * 3  # the first try and the client's two retries
    api.push("/api/v1/conversions/up00000001", *down)
    with django_capture_on_commit_callbacks(execute=True):
        photo = Photo.objects.create(image=upload("IMG.heic"))
    job = ConversionJob.objects.get()
    assert (job.status, job.error_code) == (Status.FAILED, "connectionError")
    assert job.conversion_id == "up00000001"
    assert retry([job]) == [Status.DONE]
    assert len(api.created()) == 1
    assert len(api.of("POST", "/api/v1/uploads")) == 1
    photo.refresh_from_db()
    assert photo.image.name == "photos/IMG.jpg"


def test_a_run_that_died_is_taken_over_later(
    api: FakeAPI, django_capture_on_commit_callbacks: Commit
) -> None:
    with django_capture_on_commit_callbacks(execute=False):
        Photo.objects.create(image=upload("IMG.heic"))
    job = ConversionJob.objects.get()
    ConversionJob.objects.filter(pk=job.pk).update(status=Status.RUNNING, started_at=timezone.now())
    assert run_jobs([str(job.pk)]) == [Status.RUNNING]  # another process has it
    ConversionJob.objects.filter(pk=job.pk).update(started_at=timezone.now() - STUCK_AFTER * 2)
    assert run_jobs([str(job.pk)]) == [Status.DONE]


def test_a_lost_create_answer_is_made_again_with_the_same_key(api: FakeAPI) -> None:
    default_storage.save("photos/IMG.heic", ContentFile(b"heic"))
    Photo.objects.bulk_create([Photo(image="photos/IMG.heic")])
    photo = Photo.objects.get()
    job = ConversionJob.objects.create(
        content_type=ContentType.objects.get_for_model(Photo),
        object_id=str(photo.pk),
        field="image",
        rule="image:jpg",
        source_name="photos/IMG.heic",
        to_format="jpg",
    )
    # An earlier run sent the file (and kept its id) but its POST /v1/conversions was lost.
    with open_client() as client:
        slot = client.upload(b"heic", file_name="IMG.heic")
    ConversionJob.objects.filter(pk=job.pk).update(conversion_id=slot.id)
    assert run_jobs([str(job.pk)]) == [Status.DONE]
    assert len(api.created()) == 1
    assert len(api.of("POST", "/api/v1/uploads")) == 1
    key = api.of("POST", "/api/v1/conversions")[0].headers["idempotency-key"]
    assert key == f"django-{job.pk}-{slot.id}"


def test_a_file_replaced_before_its_turn_is_skipped(
    api: FakeAPI, django_capture_on_commit_callbacks: Commit
) -> None:
    with django_capture_on_commit_callbacks(execute=False):
        photo = Photo.objects.create(image=upload("first.heic"))
    Photo.objects.filter(pk=photo.pk).update(image="photos/second.jpg")
    job = ConversionJob.objects.get()
    assert run_jobs([str(job.pk)]) == [Status.SKIPPED]
    job.refresh_from_db()
    assert job.error_code == "fileChanged"
    Photo.objects.all().delete()
    job.status = Status.QUEUED
    job.save()
    assert run_jobs([str(job.pk)]) == [Status.SKIPPED]
    job.refresh_from_db()
    assert job.error_code == "objectDeleted"
    assert api.requests == []


def test_a_job_runs_once(api: FakeAPI, django_capture_on_commit_callbacks: Commit) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        Photo.objects.create(image=upload("IMG.heic"))
    job = ConversionJob.objects.get()
    assert run_jobs([str(job.pk)]) == [Status.DONE]
    assert len(api.created()) == 1


def test_delete_original_and_image_sizes(
    api: FakeAPI, django_capture_on_commit_callbacks: Commit
) -> None:
    pytest.importorskip("PIL")
    api.outputs["jpg"] = jpeg_bytes((12, 7))
    with django_capture_on_commit_callbacks(execute=True):
        avatar = Avatar.objects.create(picture=upload("me.heic", b"heic"))
    avatar.refresh_from_db()
    assert avatar.picture.name == "avatars/me.jpg"
    assert (avatar.width, avatar.height) == (12, 7)
    assert not default_storage.exists("avatars/me.heic")


@override_settings(CONVERTER_STUDIO_DELETE_ORIGINALS=True)
def test_delete_originals_setting(api: FakeAPI, django_capture_on_commit_callbacks: Commit) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        Photo.objects.create(image=upload("IMG.heic"))
    assert not default_storage.exists("photos/IMG.heic")
    assert default_storage.exists("photos/IMG.jpg")


def test_file_converted_signal(api: FakeAPI, django_capture_on_commit_callbacks: Commit) -> None:
    seen: list[dict[str, Any]] = []

    def receiver(sender: Any, **kwargs: Any) -> None:
        seen.append({"sender": sender, **kwargs})

    def broken(sender: Any, **kwargs: Any) -> None:
        raise RuntimeError("a receiver that fails does not fail the conversion")

    file_converted.connect(receiver)
    file_converted.connect(broken)
    try:
        with django_capture_on_commit_callbacks(execute=True):
            Photo.objects.create(image=upload("IMG.heic"))
    finally:
        file_converted.disconnect(receiver)
        file_converted.disconnect(broken)
    assert seen[0]["sender"] is Photo
    assert seen[0]["original_name"] == "photos/IMG.heic"
    assert seen[0]["name"] == "photos/IMG.jpg"
    assert ConversionJob.objects.get().status == Status.DONE


def test_convert_instance_skips_what_is_done(api: FakeAPI) -> None:
    Report.objects.bulk_create([Report(file="reports/a.docx", pdf="reports/pdf/a.pdf")])
    default_storage.save("reports/a.docx", ContentFile(b"docx"))
    report = Report.objects.get()
    assert convert_instance(report) == []
    jobs = report.convert_files(force=True)
    assert [job.status for job in jobs] == [Status.DONE]
    report.refresh_from_db()
    assert (report.pdf.name or "").startswith("reports/pdf/a")


def test_rules_registered_from_outside_and_storage_names(
    api: FakeAPI, django_capture_on_commit_callbacks: Commit
) -> None:
    register(Photo, Rule(field="image", sources=["png"], to="webp", name="png-webp"))
    try:
        with django_capture_on_commit_callbacks(execute=True):
            first = Photo.objects.create(image=upload("logo.png"))
            second = Photo.objects.create(image=upload("logo.png"))
    finally:
        unregister(Photo)
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.image.name == "photos/logo.webp"
    assert second.image.name != first.image.name  # the storage picks a free name
    assert Clip._meta.label == "testapp.Clip"


def test_one_replacing_rule_per_file() -> None:
    register(Photo, Rule(field="image", sources=["heic"], to="png", name="second"))
    try:
        from django_converter_studio.jobs import matching_rules

        photo = Photo(image="photos/a.heic")
        assert [rule.name for rule in matching_rules(photo)] == ["image:jpg"]
    finally:
        unregister(Photo)
