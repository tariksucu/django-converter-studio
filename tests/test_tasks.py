from __future__ import annotations

import importlib.util
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

import django
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from django_converter_studio import tasks
from django_converter_studio.jobs import mode
from django_converter_studio.models import ConversionJob
from django_converter_studio.rules import Rule

from .fake_api import FakeAPI
from .testapp.models import Clip, Photo

pytestmark = pytest.mark.django_db

Commit = Callable[..., AbstractContextManager[list[Callable[[], Any]]]]
Status = ConversionJob.Status
CORE = django.VERSION >= (6, 0)
BACKPORT = importlib.util.find_spec("django_tasks") is not None
FRAMEWORK = "django.tasks" if CORE else "django_tasks"
needs_tasks = pytest.mark.skipif(not (CORE or BACKPORT), reason="no tasks framework installed")


def dummy(framework: str = FRAMEWORK) -> dict[str, Any]:
    return {"default": {"BACKEND": f"{framework}.backends.dummy.DummyBackend"}}


def results(framework: str = FRAMEWORK) -> list[Any]:
    backends = __import__(framework, fromlist=["task_backends"]).task_backends
    return list(backends["default"].results)


def test_the_framework_follows_the_backend() -> None:
    with override_settings(TASKS=None):
        expected = "django.tasks" if CORE else ("django_tasks" if BACKPORT else None)
        assert tasks.framework() == expected
    if BACKPORT:
        with override_settings(TASKS=dummy("django_tasks")):
            assert tasks.framework() == "django_tasks"
    if CORE:
        with override_settings(TASKS=dummy("django.tasks")):
            assert tasks.framework() == "django.tasks"
    with override_settings(TASKS={"default": {"BACKEND": "no.such.Backend"}}):
        assert tasks.framework() is None
        assert not tasks.available()


@needs_tasks
@override_settings(TASKS=dummy())
def test_a_task_rule_is_queued_after_the_commit(
    api: FakeAPI, django_capture_on_commit_callbacks: Commit
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        clip = Clip.objects.create(video=SimpleUploadedFile("talk.mov", b"movie"))
    job = ConversionJob.objects.get()
    assert job.status == Status.QUEUED
    assert api.requests == []
    (result,) = results()
    assert result.task.module_path == "django_converter_studio.tasks.convert_jobs"
    assert result.args == [[str(job.pk)]]
    # What a worker does with it:
    assert result.task.call(*result.args, **result.kwargs) == [Status.DONE]
    clip.refresh_from_db()
    assert clip.video.name == "clips/talk.mp4"


@needs_tasks
@override_settings(TASKS=dummy(), CONVERTER_STUDIO_RUN="auto")
def test_auto_uses_the_tasks_framework(api: FakeAPI) -> None:
    assert mode(Rule(field="f", sources=["heic"], to="jpg")) == "task"
    assert mode(Rule(field="f", sources=["heic"], to="jpg", run="inline")) == "inline"


@override_settings(TASKS={"default": {"BACKEND": "no.such.Backend"}}, CONVERTER_STUDIO_RUN="task")
def test_without_a_framework_tasks_run_inline(
    api: FakeAPI, django_capture_on_commit_callbacks: Commit
) -> None:
    with django_capture_on_commit_callbacks(execute=True):
        clip = Clip.objects.create(video=SimpleUploadedFile("talk.mov", b"movie"))
    clip.refresh_from_db()
    assert clip.video.name == "clips/talk.mp4"


@needs_tasks
@override_settings(
    TASKS={
        "default": {
            "BACKEND": f"{FRAMEWORK}.backends.immediate.ImmediateBackend",
            "QUEUES": ["files"],
        }
    },
    CONVERTER_STUDIO_TASK_QUEUE="files",
)
def test_the_immediate_backend_and_a_queue_of_its_own(
    api: FakeAPI, django_capture_on_commit_callbacks: Commit
) -> None:
    assert tasks.get_task().queue_name == "files"
    with django_capture_on_commit_callbacks(execute=True):
        photo = Photo.objects.create(image=SimpleUploadedFile("IMG.heic", b"heic"))
    photo.refresh_from_db()
    assert photo.image.name == "photos/IMG.jpg"


@needs_tasks
@override_settings(TASKS=dummy())
def test_a_queue_that_refuses_the_job_marks_it_failed(
    api: FakeAPI, monkeypatch: pytest.MonkeyPatch, django_capture_on_commit_callbacks: Commit
) -> None:
    task = tasks.get_task()

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("the queue is down")

    monkeypatch.setattr(tasks, "get_task", lambda: type("T", (), {"enqueue": refuse})())
    with django_capture_on_commit_callbacks(execute=True):
        Clip.objects.create(video=SimpleUploadedFile("talk.mov", b"movie"))
    job = ConversionJob.objects.get()
    assert (job.status, job.error_code) == (Status.FAILED, "taskError")
    assert "the queue is down" in job.error_message
    assert task is not None
