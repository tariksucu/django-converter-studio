from __future__ import annotations

import hashlib
import io
from typing import Any

import pytest

pytest.importorskip("wagtail")

from django.core.checks import run_checks
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse
from wagtail.documents import get_document_model
from wagtail.images import get_image_model
from wagtail.models import Collection

from django_converter_studio.models import ConversionJob
from django_converter_studio.wagtail.forms import ConvertingImageForm

from .fake_api import FakeAPI

pytestmark = pytest.mark.django_db
Image = get_image_model()
Document = get_document_model()
Status = ConversionJob.Status


def heic_bytes() -> bytes:
    pillow_heif = pytest.importorskip("pillow_heif")
    from PIL import Image as PILImage

    pillow_heif.register_heif_opener()
    out = io.BytesIO()
    PILImage.new("RGB", (8, 6), (10, 120, 200)).save(out, "HEIF")
    return out.getvalue()


def add_images(client: Client, name: str, data: bytes = b"raw photo") -> dict[str, Any]:
    response = client.post(
        reverse("wagtailimages:add_multiple"),
        {"files[]": SimpleUploadedFile(name, data), "title": name},
        headers={"x-requested-with": "XMLHttpRequest"},
    )
    assert response.status_code == 200
    answer: dict[str, Any] = response.json()
    return answer


def test_a_raw_photo_becomes_a_jpg_while_it_uploads(api: FakeAPI, admin_client: Client) -> None:
    answer = add_images(admin_client, "DSC_0042.NEF")
    assert answer["success"], answer
    image = Image.objects.get(pk=answer["image_id"])
    assert image.file.name == "original_images/DSC_0042.jpg"
    assert image.title == "DSC_0042.NEF"
    assert (image.width, image.height) == (8, 6)
    assert image.file_size == len(api.outputs["jpg"])
    assert image.file_hash == hashlib.sha1(api.outputs["jpg"]).hexdigest()  # noqa: S324
    assert [r.content for r in api.requests if r.method == "PUT"] == [b"raw photo"]
    assert not ConversionJob.objects.exists()  # converted before saving: nothing left to do


def test_the_single_add_form_and_heic(api: FakeAPI, admin_client: Client) -> None:
    response = admin_client.post(
        reverse("wagtailimages:add"),
        {
            "title": "Holiday",
            "file": SimpleUploadedFile("IMG_1.HEIC", b"heic"),
            "collection": Collection.get_first_root_node().pk,
        },
    )
    assert response.status_code == 302, response.content.decode()[:2000]
    assert Image.objects.get().file.name == "original_images/IMG_1.jpg"


@override_settings(CONVERTER_STUDIO_API_KEY="cvs_live_wrong")
def test_a_refused_upload_says_why(api: FakeAPI, admin_client: Client) -> None:
    answer = add_images(admin_client, "DSC_0042.dng")
    assert not answer["success"]
    assert answer["error_message"] == (
        "DSC_0042.dng could not be converted to JPG by Converter Studio: "
        "This API key does not work."
    )
    assert not Image.objects.exists()


def test_a_damaged_file_is_refused_with_the_reason(api: FakeAPI, admin_client: Client) -> None:
    answer = add_images(admin_client, "broken.heic")
    assert not answer["success"]
    assert "This file could not be converted" in answer["error_message"]


@override_settings(
    CONVERTER_STUDIO_API_KEY="cvs_live_wrong",
    WAGTAILIMAGES_EXTENSIONS=["jpg", "jpeg", "png", "heic", "heif"],
)
def test_an_original_wagtail_can_open_is_kept_when_conversion_fails(
    api: FakeAPI, admin_client: Client, django_capture_on_commit_callbacks: Any
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        answer = add_images(admin_client, "IMG_2.heic", heic_bytes())
    assert answer["success"], answer
    assert Image.objects.get().file.name == "original_images/IMG_2.heic"
    # The stored HEIC is tried again after the save (and recorded): the key still does not work.
    job = ConversionJob.objects.get()
    assert (job.status, job.error_code) == (Status.FAILED, "invalidApiKey")


def test_a_stored_heic_is_converted_in_place_with_wagtails_details(
    api: FakeAPI, admin_client: Client
) -> None:
    image = Image(title="old", collection=Collection.get_first_root_node())
    image.file.save("IMG_3.heic", ContentFile(b"heic"), save=False)
    image.width, image.height, image.file_size, image.file_hash = 8, 6, 4, "x"
    Image.objects.bulk_create([image])
    image = Image.objects.get()
    next_url = reverse("wagtailimages:index")
    response = admin_client.post(
        reverse(
            "wagtail_bulk_action",
            args=("wagtailimages", "image", "convert_with_converter_studio"),
        )
        + f"?id={image.pk}&next={next_url}",
        follow=True,
    )
    assert response.status_code == 200
    image.refresh_from_db()
    assert image.file.name == "original_images/IMG_3.jpg"
    assert image.file_size == len(api.outputs["jpg"])
    assert image.file_hash == hashlib.sha1(api.outputs["jpg"]).hexdigest()  # noqa: S324
    assert b"Converted 1 file (1 credits)." in response.content


def test_documents_become_pdf_after_they_upload(
    api: FakeAPI, admin_client: Client, django_capture_on_commit_callbacks: Any
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        response = admin_client.post(
            reverse("wagtaildocs:add_multiple"),
            {"files[]": SimpleUploadedFile("Annual report.docx", b"docx"), "title": "Annual"},
            headers={"x-requested-with": "XMLHttpRequest"},
        )
    assert response.json()["success"]
    document = Document.objects.get()
    assert document.file.name == "documents/Annual_report.pdf"
    assert document.title == "Annual"
    assert document.file_size == len(b"RESULT pdf")
    assert document.file_hash == hashlib.sha1(b"RESULT pdf").hexdigest()  # noqa: S324
    assert ConversionJob.objects.get().status == Status.DONE


def test_the_document_bulk_action(api: FakeAPI, admin_client: Client) -> None:
    root = Collection.get_first_root_node()
    for name in ("a.odt", "b.pdf"):
        document = Document(title=name, collection=root)
        document.file.save(name, ContentFile(b"doc"), save=False)
        Document.objects.bulk_create([document])
    ids = "&".join(f"id={pk}" for pk in Document.objects.values_list("pk", flat=True))
    url = (
        reverse(
            "wagtail_bulk_action",
            args=("wagtaildocs", "document", "convert_with_converter_studio"),
        )
        + f"?{ids}&next={reverse('wagtaildocs:index')}"
    )
    confirm = admin_client.get(url)
    assert confirm.status_code == 200
    assert b"DOCX, ODT" in confirm.content
    assert b"PDF" in confirm.content
    response = admin_client.post(url, follow=True)
    assert b"Converted 1 file (1 credits)." in response.content
    names = sorted(Document.objects.values_list("file", flat=True))
    assert names == ["documents/a.pdf", "documents/b.pdf"]


def test_the_listing_offers_the_bulk_action(api: FakeAPI, admin_client: Client) -> None:
    assert (
        b"Convert with Converter Studio" in admin_client.get(reverse("wagtaildocs:index")).content
    )


def test_the_form_is_the_configured_base() -> None:
    from wagtail.images.forms import get_image_form

    form_class = get_image_form(Image)
    assert issubclass(form_class, ConvertingImageForm)
    # The file dialog offers the files to convert, not only what it takes for images.
    accept = form_class(user=None).fields["file"].widget.attrs["accept"]
    assert accept.startswith("image/*")
    assert ".dng" in accept
    assert ".eps" in accept


def check_ids() -> set[str]:
    return {str(m.id) for m in run_checks(tags=["converter_studio"])}


def test_wagtail_checks() -> None:
    assert "converter_studio.W102" in check_ids()  # HEIC is left out of the test settings
    with override_settings(WAGTAILIMAGES_IMAGE_FORM_BASE=""):
        assert "converter_studio.W101" in check_ids()
    with override_settings(CONVERTER_STUDIO_WAGTAIL_IMAGES={"dng": "pdf", "heic": "tiff"}):
        assert "converter_studio.E102" in check_ids()
    with override_settings(WAGTAILIMAGES_EXTENSIONS=["png", "dng"]):
        assert "converter_studio.E103" in check_ids()  # jpg results would be refused
    with override_settings(WAGTAILDOCS_EXTENSIONS=["docx"]):
        assert "converter_studio.W103" in check_ids()
