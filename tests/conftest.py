from __future__ import annotations

import io
import time
from collections.abc import Iterator
from typing import Any

import pytest
from django.core.files.storage import default_storage

from django_converter_studio import client as client_module

from .fake_api import FakeAPI


def jpeg_bytes(size: tuple[int, int] = (8, 6)) -> bytes:
    """A real JPEG (Wagtail and ImageField read its size), or plain bytes without Pillow."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover (Pillow comes with Wagtail)
        return b"\xff\xd8\xff\xe0 not a real jpeg"
    out = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(out, "JPEG")
    return out.getvalue()


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    # The client pauses between status requests that come back early; tests need no pause.
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    monkeypatch.delenv("CONVERTER_STUDIO_API_KEY", raising=False)
    monkeypatch.delenv("CONVERTER_STUDIO_BASE_URL", raising=False)


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> FakeAPI:
    fake = FakeAPI(outputs={"jpg": jpeg_bytes(), "png": b"\x89PNG fake", "txt": b"Hello 2026\n"})
    monkeypatch.setattr(client_module, "http_transport", fake.transport)
    return fake


@pytest.fixture(autouse=True)
def _empty_storage() -> Iterator[None]:
    yield
    from django.core.files.storage.memory import (  # type: ignore[attr-defined]
        InMemoryDirNode,
        InMemoryStorage,
    )

    storage: Any = default_storage
    target = getattr(storage, "_wrapped", storage)
    if isinstance(target, InMemoryStorage):
        # Forget the files of the test.
        target._root = InMemoryDirNode()  # type: ignore[attr-defined]
