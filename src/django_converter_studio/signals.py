"""The save hooks that convert new uploads by rule, and the ``file_converted`` signal.

``pre_save`` notes which file fields of a model with rules received a new file (one that is not in
storage yet); ``post_save`` creates their conversions and runs them once the save is committed:
inline (in the same process) or as a task.
"""

from __future__ import annotations

from typing import Any

from django.db.models.signals import post_save, pre_save
from django.dispatch import Signal

from .rules import rules_for

#: Sent after a converted file (or text) is saved: ``sender`` is the model, with ``instance``,
#: ``job`` (the :class:`~django_converter_studio.models.ConversionJob`), ``rule``,
#: ``original_name`` (the source file's storage name) and ``name`` (the result's storage name,
#: ``""`` for text). The row has already been updated.
file_converted = Signal()

_NEW_FILES = "_converter_studio_new_files"


def _new_files(sender: Any, instance: Any, update_fields: Any) -> set[str]:
    found = set()
    for field in {rule.field for rule in rules_for(sender)}:
        if update_fields is not None and field not in update_fields:
            continue
        value = getattr(instance, field, None)
        # A FieldFile that is not committed holds a file that is not in storage yet: an upload
        # or a File assigned in code. Django's FileField.pre_save stores it next.
        if value and value.name and not getattr(value, "_committed", True):
            found.add(field)
    return found


def _before_save(
    sender: Any, instance: Any, raw: bool = False, update_fields: Any = None, **kwargs: Any
) -> None:
    if raw or not rules_for(sender):
        return
    new = _new_files(sender, instance, update_fields)
    if new:
        instance.__dict__[_NEW_FILES] = new
    else:
        instance.__dict__.pop(_NEW_FILES, None)


def _after_save(
    sender: Any, instance: Any, raw: bool = False, using: str | None = None, **kwargs: Any
) -> None:
    new = instance.__dict__.pop(_NEW_FILES, None)
    if raw or not new:
        return
    from .jobs import schedule

    schedule(instance, fields=new, force=True, using=using)


def connect() -> None:
    pre_save.connect(_before_save, dispatch_uid="django_converter_studio.pre_save")
    post_save.connect(_after_save, dispatch_uid="django_converter_studio.post_save")
