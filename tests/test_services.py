from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from converter_studio import (
    AuthenticationError,
    ConfirmationRequiredError,
    ConversionFailedError,
    MissingApiKeyError,
)
from converter_studio import __version__ as python_client_version
from django.core.files import File
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

import django_converter_studio
from django_converter_studio import (
    account,
    convert,
    convert_to_storage,
    extract_text,
    open_client,
)

from .fake_api import KEY, FakeAPI
from .testapp.models import Report


def test_every_request_names_the_django_client(api: FakeAPI) -> None:
    with convert(b"photo bytes", "jpg", file_name="IMG_1.HEIC") as result:
        assert result.name == "IMG_1.jpg"
    name = f"django/{django_converter_studio.__version__}"
    assert {r.headers["x-converter-studio-client"] for r in api.requests} == {name}
    agent = f"{name} converter-studio-python/{python_client_version} Python/"
    assert all(r.headers["user-agent"].startswith(agent) for r in api.requests)
    # The key goes to the API only, never to the upload and download links.
    for request in api.requests:
        has_key = "authorization" in request.headers
        assert has_key == (not request.url.path.startswith(("/api/v1/uploads/", "/api/jobs/")))


def test_convert_bytes_returns_a_django_file(api: FakeAPI) -> None:
    with convert(b"heic", "JPG", file_name="photos/IMG_1.heic") as result:
        assert result.file.read() == api.outputs["jpg"]
        assert result.size == len(api.outputs["jpg"])
        assert result.credits == 1
        assert result.content_type == "image/jpeg"
    assert api.created()[0]["to"] == "jpg"
    assert api.created()[0]["maxCredits"] == 20
    upload = json.loads(api.of("POST", "/api/v1/uploads")[0].content)
    assert upload["fileName"] == "IMG_1.heic"


def test_convert_reads_a_field_file_through_its_storage(api: FakeAPI) -> None:
    report = Report()
    report.file.save("scan.pdf", ContentFile(b"%PDF-1.7 scan"), save=False)
    assert report.file.closed
    with convert(report.file, "txt") as result:
        assert result.read_text() == "Hello 2026\n"
    assert [r.content for r in api.requests if r.method == "PUT"] == [b"%PDF-1.7 scan"]
    assert json.loads(api.of("POST", "/api/v1/uploads")[0].content)["fileName"] == "scan.pdf"


def test_a_closed_file_is_opened_and_closed_again(api: FakeAPI, tmp_path: Path) -> None:
    path = tmp_path / "a.heic"
    path.write_bytes(b"heic")
    source = File(path.open("rb"), name=str(path))
    source.close()
    with convert(source, "jpg") as result:
        assert result.name == "a.jpg"
    assert source.closed
    assert [r.content for r in api.requests if r.method == "PUT"] == [b"heic"]


def test_convert_an_upload_and_leave_it_open(api: FakeAPI) -> None:
    upload = SimpleUploadedFile("talk.mov", b"movie", content_type="video/quicktime")
    upload.read(2)  # wherever it stands, the whole file is sent
    with convert(upload, "mp4", options={"height": "720"}) as result:
        assert result.name == "talk.mp4"
    assert [r.content for r in api.requests if r.method == "PUT"] == [b"movie"]
    assert api.created()[0]["options"] == {"height": "720"}
    assert not upload.closed


def test_convert_a_file_object_needs_a_name(api: FakeAPI) -> None:
    with pytest.raises(ValueError, match="file_name"):
        convert(io.BytesIO(b"x"), "pdf")


def test_convert_to_storage_saves_next_to_the_source(api: FakeAPI) -> None:
    report = Report()
    report.file.save("q3.docx", ContentFile(b"docx"), save=False)
    name = convert_to_storage(report.file, "pdf")
    assert name == "reports/q3.pdf"
    with default_storage.open(name) as saved:
        assert saved.read() == b"RESULT pdf"
    assert convert_to_storage(b"x", "pdf", file_name="a.docx", name="out/a.pdf") == "out/a.pdf"


def test_extract_text_reads_scanned_pdfs_with_ocr(api: FakeAPI) -> None:
    assert extract_text(b"%PDF", file_name="scan.pdf") == "Hello 2026"
    assert api.created()[0]["options"] == {"ocr": True}
    assert extract_text(b"png", file_name="sign.png") == "Hello 2026"
    assert "options" not in api.created()[1]


def test_errors_carry_the_api_message(api: FakeAPI) -> None:
    with pytest.raises(ConversionFailedError) as failed:
        convert(b"x", "jpg", file_name="broken.heic")
    assert failed.value.code == "conversionFailed"
    assert "credits were given back" in str(failed.value)
    api.credits = 30
    with pytest.raises(ConfirmationRequiredError):
        convert(b"x", "mp4", file_name="long.mov")
    with pytest.raises(ConfirmationRequiredError):
        convert(b"x", "mp4", file_name="long.mov", max_credits=29)
    with convert(b"x", "mp4", file_name="long.mov", max_credits=30) as result:
        assert result.credits == 30


@override_settings(CONVERTER_STUDIO_API_KEY="cvs_live_wrong")
def test_a_wrong_key(api: FakeAPI) -> None:
    with pytest.raises(AuthenticationError, match="does not work"):
        convert(b"x", "jpg", file_name="a.heic")


@override_settings(CONVERTER_STUDIO_API_KEY=None)
def test_no_key_at_all(api: FakeAPI) -> None:
    with pytest.raises(MissingApiKeyError, match="CONVERTER_STUDIO_API_KEY"):
        convert(b"x", "jpg", file_name="a.heic")
    assert api.requests == []


@override_settings(CONVERTER_STUDIO_API_KEY=None)
def test_the_key_may_come_from_the_environment(
    api: FakeAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CONVERTER_STUDIO_API_KEY", KEY)
    assert account().credits == 1099


def test_open_client_uses_the_settings(api: FakeAPI) -> None:
    with open_client() as client:
        assert client.base_url == "https://api.test/api"
        assert client.account().plan == "pro"
