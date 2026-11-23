"""Rules: which uploaded files a model converts, to what, and where the result goes.

>>> from django_converter_studio import Rule, formats
>>> class Photo(ConverterStudioMixin, models.Model):
...     image = models.FileField(upload_to="photos/")
...     converter_studio_rules = [Rule(field="image", sources=formats.HEIC + formats.RAW, to="jpg")]

or, for a model you do not own, in your ``AppConfig.ready()``::

    register(Document, Rule(field="file", sources=formats.OFFICE, to="pdf", target="pdf"))
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING, Any, ClassVar

from .conf import RUN_MODES
from .formats import extension, normalize

if TYPE_CHECKING:
    from django.db import models

    from .models import ConversionJob

_FORMAT = re.compile(r"[a-z0-9]{1,16}")


@dataclass(frozen=True, kw_only=True)
class Rule:
    """Convert the files of ``field`` whose extension is in ``sources`` to ``to``.

    ``target``: ``None`` replaces the file in place (same field, new name, same storage); the
    name of another ``FileField`` stores the result there; the name of a ``TextField`` or
    ``CharField`` stores the result's text there (``to`` must be a text format such as
    ``"txt"``). ``options``: the API's conversion settings. ``max_credits``: the most one file may
    cost to start on its own (``CONVERTER_STUDIO_MAX_CREDITS``). ``run``: ``"inline"`` (after the
    save is committed, in the same process) or ``"task"`` (Django's tasks framework);
    ``CONVERTER_STUDIO_RUN`` when not given. ``delete_original``: for a replacing rule, delete
    the original from storage once the result is saved (``CONVERTER_STUDIO_DELETE_ORIGINALS``).
    ``name``: how the rule is known in the conversions log (made up when not given).
    """

    field: str
    to: str
    sources: Collection[str]
    target: str | None = None
    options: Mapping[str, object] = dataclass_field(default_factory=dict)
    max_credits: int | None = None
    run: str | None = None
    delete_original: bool | None = None
    name: str = ""

    def __post_init__(self) -> None:
        to = normalize(self.to)
        object.__setattr__(self, "to", to)
        if isinstance(self.sources, str):
            raise TypeError("sources is a list of extensions, such as ['heic', 'heif']")
        object.__setattr__(self, "sources", frozenset(normalize(s) for s in self.sources if s))
        object.__setattr__(self, "options", dict(self.options))
        if not self.name:
            where = f">{self.target}" if self.target else ""
            object.__setattr__(self, "name", f"{self.field}{where}:{to}")

    @property
    def replaces(self) -> bool:
        """Whether the result takes the original's place in the same field."""
        return self.target is None

    def matches(self, file_name: str) -> bool:
        """Whether a file of this name is converted by the rule."""
        ext = extension(file_name)
        return bool(ext) and ext in self.sources and ext != self.to

    def problems(self) -> list[str]:
        """What is wrong with the rule itself (the model's fields are checked elsewhere)."""
        found = []
        if not _FORMAT.fullmatch(self.to):
            found.append(f"'to' must be a format such as 'jpg' or 'pdf', not {self.to!r}")
        if not self.sources:
            found.append("'sources' is empty")
        if self.run is not None and self.run not in RUN_MODES - {"auto"}:
            found.append(f"'run' must be 'inline' or 'task', not {self.run!r}")
        if self.max_credits is not None and (
            isinstance(self.max_credits, bool) or self.max_credits < 0
        ):
            found.append("'max_credits' must be a whole number, 0 or more")
        if self.target == self.field:
            found.append("'target' is the source field itself: leave it out to replace the file")
        return found


class ConverterStudioMixin:
    """Gives a model rules (``converter_studio_rules``) and :meth:`convert_files`.

    ``class Photo(ConverterStudioMixin, models.Model)``; the mixin adds no database field.
    """

    converter_studio_rules: ClassVar[Iterable[Rule]] = ()

    def convert_files(
        self, *, fields: Iterable[str] | None = None, force: bool = False, run: str | None = None
    ) -> list[ConversionJob]:
        """Converts this object's files by its rules now (or queues them, ``run="task"``) and
        returns the conversions. ``force`` converts again into targets that are filled."""
        from .jobs import convert_instance

        return convert_instance(self, fields=fields, force=force, run=run)  # type: ignore[arg-type]


_registry: dict[type[models.Model], tuple[Rule, ...]] = {}


def register(model: type[models.Model], *rules: Rule) -> None:
    """Adds ``rules`` to ``model`` (call it from an ``AppConfig.ready()``)."""
    names = {rule.name for rule in rules_for(model)}
    for rule in rules:
        if rule.name in names:
            raise ValueError(f"{model.__name__} already has a rule named {rule.name!r}")
        names.add(rule.name)
    _registry[model] = (*_registry.get(model, ()), *rules)


def unregister(model: type[models.Model]) -> None:
    """Removes the rules :func:`register` gave ``model`` (not its ``converter_studio_rules``)."""
    _registry.pop(model, None)


def rules_for(model: type[models.Model] | Any) -> tuple[Rule, ...]:
    """The model's rules: its ``converter_studio_rules`` and those registered for it (or for the
    model a proxy stands for)."""
    found: list[Rule] = list(getattr(model, "converter_studio_rules", ()) or ())
    found.extend(_registry.get(model, ()))
    meta = getattr(model, "_meta", None)
    concrete = getattr(meta, "concrete_model", None)
    if concrete is not None and concrete is not model:
        found.extend(_registry.get(concrete, ()))
    return tuple(found)


def get_rule(model: type[models.Model], name: str) -> Rule | None:
    return next((rule for rule in rules_for(model) if rule.name == name), None)


def models_with_rules() -> list[type[models.Model]]:
    """Every installed model that has rules."""
    from django.apps import apps

    return [model for model in apps.get_models() if rules_for(model)]
