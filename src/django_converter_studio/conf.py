"""The package's settings, read from ``django.conf.settings`` each time.

- ``CONVERTER_STUDIO_API_KEY``: the account's API key (else the environment variable of that
  name).
- ``CONVERTER_STUDIO_BASE_URL``: the API's address (``https://converter.studio/api``).
- ``CONVERTER_STUDIO_MAX_CREDITS``: the most one file may cost to start on its own (20).
- ``CONVERTER_STUDIO_TIMEOUT``: seconds a conversion may take in a job or a command (600).
- ``CONVERTER_STUDIO_UPLOAD_TIMEOUT``: seconds an upload form waits for its conversion (60).
- ``CONVERTER_STUDIO_RUN``: ``"auto"`` (a task when a tasks framework is there, else inline),
  ``"inline"`` or ``"task"``.
- ``CONVERTER_STUDIO_TASK_BACKEND``, ``CONVERTER_STUDIO_TASK_QUEUE``: the ``TASKS`` alias and
  the queue conversions are enqueued on (``"default"``).
- ``CONVERTER_STUDIO_DELETE_ORIGINALS``: delete a replaced original from storage (``False``).

The Wagtail settings are described in :mod:`django_converter_studio.wagtail`.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Literal, cast

from converter_studio import API_KEY_ENV, BASE_URL_ENV, DEFAULT_BASE_URL
from django.conf import settings

from .formats import HEIC, RAW, VECTOR, normalize

RunMode = Literal["inline", "task"]
RUN_MODES: frozenset[str] = frozenset({"auto", "inline", "task"})

DEFAULT_MAX_CREDITS = 20
DEFAULT_TIMEOUT = 600.0
DEFAULT_UPLOAD_TIMEOUT = 60.0
#: Seconds for one HTTP request to connect, send or receive a chunk.
REQUEST_TIMEOUT = 60.0

#: Wagtail images: what each extension Wagtail cannot use as it is becomes.
DEFAULT_WAGTAIL_IMAGES: dict[str, str] = {
    **dict.fromkeys(HEIC, "jpg"),
    **dict.fromkeys(RAW, "jpg"),
    **dict.fromkeys(VECTOR, "png"),
}


def _get(name: str, default: Any = None) -> Any:
    return getattr(settings, f"CONVERTER_STUDIO_{name}", default)


def api_key() -> str | None:
    """The API key: the setting, else the ``CONVERTER_STUDIO_API_KEY`` environment variable."""
    value = _get("API_KEY")
    if value is None:
        value = os.environ.get(API_KEY_ENV)
    text = str(value or "").strip()
    return text or None


def base_url() -> str:
    value = _get("BASE_URL") or os.environ.get(BASE_URL_ENV) or DEFAULT_BASE_URL
    return str(value).strip().rstrip("/")


def max_credits() -> int:
    return cast(int, _get("MAX_CREDITS", DEFAULT_MAX_CREDITS))


def timeout() -> float:
    return float(_get("TIMEOUT", DEFAULT_TIMEOUT))


def upload_timeout() -> float:
    return float(_get("UPLOAD_TIMEOUT", DEFAULT_UPLOAD_TIMEOUT))


def run_mode() -> str:
    return str(_get("RUN", "auto"))


def task_backend() -> str:
    return str(_get("TASK_BACKEND", "default"))


def task_queue() -> str:
    return str(_get("TASK_QUEUE", "default"))


def delete_originals() -> bool:
    return bool(_get("DELETE_ORIGINALS", False))


def _mapping(name: str, default: Mapping[str, str]) -> dict[str, str]:
    value = _get(name, default)
    if not isinstance(value, Mapping):
        return {}
    return {normalize(str(key)): normalize(str(item)) for key, item in value.items() if item}


def wagtail_images() -> dict[str, str]:
    """``CONVERTER_STUDIO_WAGTAIL_IMAGES``: extension -> format for Wagtail image uploads."""
    return _mapping("WAGTAIL_IMAGES", DEFAULT_WAGTAIL_IMAGES)


def wagtail_documents() -> dict[str, str]:
    """``CONVERTER_STUDIO_WAGTAIL_DOCUMENTS``: extension -> format for Wagtail documents (none)."""
    return _mapping("WAGTAIL_DOCUMENTS", {})


def wagtail_options() -> dict[str, dict[str, object]]:
    """``CONVERTER_STUDIO_WAGTAIL_OPTIONS``: target format -> conversion settings."""
    value = _get("WAGTAIL_OPTIONS", {})
    if not isinstance(value, Mapping):
        return {}
    return {
        normalize(str(key)): dict(item) for key, item in value.items() if isinstance(item, Mapping)
    }
