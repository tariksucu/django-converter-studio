"""Conversions in the background, through Django's tasks framework.

Django 6.0 and later have it built in (``django.tasks``); Django 5.2 can use its backport,
``django-tasks`` (``django_tasks``, which Wagtail installs). The framework is chosen by the
``TASKS`` backend that ``CONVERTER_STUDIO_TASK_BACKEND`` names (``"default"``), so a Wagtail site
whose ``TASKS`` uses a ``django_tasks`` backend keeps using it. Without either framework,
conversions run inline: right after the save is committed, in the same process.

Django ships only an immediate and a dummy backend; for real background work, configure a
backend that has a worker (for example ``django-tasks-db``) and run that worker.
"""

from __future__ import annotations

import importlib.util
import logging
from typing import Any

from django.conf import settings
from django.core.signals import setting_changed
from django.dispatch import receiver
from django.utils.module_loading import import_string

from . import conf

logger = logging.getLogger("django_converter_studio")

CORE = "django.tasks"
BACKPORT = "django_tasks"


def _importable(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def backend_path() -> str:
    """The ``BACKEND`` of the ``TASKS`` alias conversions are enqueued on ("" if not set)."""
    configured = getattr(settings, "TASKS", None) or {}
    backend = configured.get(conf.task_backend(), {}) if isinstance(configured, dict) else {}
    return str(backend.get("BACKEND", "")) if isinstance(backend, dict) else ""


def framework() -> str | None:
    """``"django.tasks"``, ``"django_tasks"`` or ``None``: which tasks framework is used."""
    core, backport = _importable(CORE), _importable(BACKPORT)
    path = backend_path()
    if path.startswith(f"{BACKPORT}.") and backport:
        return BACKPORT
    if path.startswith(f"{CORE}.") and core:
        return CORE
    if path:
        # A third-party backend: the framework its class is built on.
        try:
            backend = import_string(path)
        except ImportError:
            return None
        for name, present in ((CORE, core), (BACKPORT, backport)):
            if present and issubclass(
                backend, import_string(f"{name}.backends.base.BaseTaskBackend")
            ):
                return name
        return None
    if core:
        return CORE
    return BACKPORT if backport else None


def convert_jobs(job_ids: list[str]) -> list[str]:
    """Runs conversions of the log (by id) and returns their statuses."""
    from .jobs import run_jobs

    return run_jobs(job_ids)


def _as_task(function: Any) -> Any:
    name = framework()
    if name is None:
        return None
    try:
        decorator = import_string(f"{name}.task")
        return decorator(backend=conf.task_backend(), queue_name=conf.task_queue())(function)
    except Exception as error:  # a misconfigured backend: conversions run inline instead
        logger.warning("Converter Studio: the tasks framework cannot take conversions: %s", error)
        return None


_function = convert_jobs
_task: Any = None
_stale = True


def build() -> None:
    """(Re)makes the Task from the settings: on import, and after ``TASKS`` changes."""
    global _task, _stale, convert_jobs
    _task = _as_task(_function)
    _stale = False
    # A worker imports a task by its function's path, so the Task takes the function's name.
    convert_jobs = _task if _task is not None else _function


def get_task() -> Any:
    """The ``convert_jobs`` Task, or ``None`` when there is no tasks framework to use."""
    if _stale:
        build()
    return _task


def available() -> bool:
    return get_task() is not None


@receiver(setting_changed)
def _settings_changed(*, setting: str, **kwargs: Any) -> None:
    # Rebuilt on next use, once the frameworks have reset their own backends too.
    global _stale
    if setting in ("TASKS", "CONVERTER_STUDIO_TASK_BACKEND", "CONVERTER_STUDIO_TASK_QUEUE"):
        _stale = True


build()
