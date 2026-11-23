from __future__ import annotations

from typing import Any

import pytest
from django.core.checks import run_checks
from django.test import override_settings

from django_converter_studio import Rule, register, tasks, unregister

from .testapp.models import Report


def ids(**kwargs: Any) -> set[str]:
    return {str(message.id) for message in run_checks(tags=["converter_studio"], **kwargs)}


def test_a_good_setup_passes() -> None:
    expected = {"converter_studio.W102"}  # HEIC is left out of the test's Wagtail settings
    if not tasks.available():
        expected.add("converter_studio.W010")  # Clip's rule asks for a task: it runs inline
    assert ids() <= expected


@override_settings(CONVERTER_STUDIO_API_KEY=None)
def test_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "converter_studio.W001" in ids()
    monkeypatch.setenv("CONVERTER_STUDIO_API_KEY", "cvs_live_from_env")
    assert "converter_studio.W001" not in ids()


@override_settings(CONVERTER_STUDIO_API_KEY="sk-something")
def test_a_key_of_another_service() -> None:
    assert "converter_studio.W002" in ids()


@pytest.mark.parametrize(
    ("url", "found"),
    [
        ("ftp://converter.studio/api", "converter_studio.E001"),
        ("http://converter.studio/api", "converter_studio.W003"),
        ("http://localhost:8080/api", None),
    ],
)
def test_the_base_url(url: str, found: str | None) -> None:
    with override_settings(CONVERTER_STUDIO_BASE_URL=url):
        result = ids()
    assert not ({"converter_studio.E001", "converter_studio.W003"} - {found} & result)
    if found:
        assert found in result


@override_settings(
    CONVERTER_STUDIO_MAX_CREDITS=-1, CONVERTER_STUDIO_TIMEOUT=0, CONVERTER_STUDIO_RUN="later"
)
def test_wrong_values() -> None:
    assert {"converter_studio.E002", "converter_studio.E003", "converter_studio.E004"} <= ids()


@override_settings(CONVERTER_STUDIO_RUN="task", TASKS={"default": {"BACKEND": "no.Backend"}})
def test_task_without_a_framework() -> None:
    assert "converter_studio.W004" in ids()


def test_wrong_rules() -> None:
    register(
        Report,
        Rule(field="nothing", sources=["heic"], to="jpg", name="a"),
        Rule(field="summary", sources=["heic"], to="jpg", name="b"),
        Rule(field="file", sources=["png"], to="jpg", target="text", name="c"),
        Rule(field="file", sources=[], to="j p g", target="file", run="soon", name="d"),
        Rule(field="file", sources=["png"], to="txt", target="id", name="e"),
        Rule(field="file", sources=["png"], to="txt", target="missing", name="f"),
    )
    try:
        messages = [m.msg for m in run_checks(tags=["converter_studio"]) if m.obj is Report]
    finally:
        unregister(Report)
    text = "\n".join(messages)
    assert "rule 'a': there is no field 'nothing'" in text
    assert "rule 'b': 'summary' is not a FileField" in text
    assert "rule 'c': text field 'text' needs a text format, not 'jpg'" in text
    assert "'sources' is empty" in text
    assert "'run' must be 'inline' or 'task'" in text
    assert "'target' is the source field itself" in text
    assert "'to' must be a format" in text
    assert "rule 'e': target 'id' is neither a file nor a text field" in text
    assert "rule 'f': there is no target field 'missing'" in text


def test_duplicate_rule_names() -> None:
    with pytest.raises(ValueError, match="already has a rule named"):
        register(Report, Rule(field="file", sources=["doc"], to="pdf", target="pdf"))
