"""The rules made from the ``CONVERTER_STUDIO_WAGTAIL_*`` settings."""

from __future__ import annotations

from collections.abc import Mapping

from .. import conf
from ..formats import extension
from ..rules import Rule

#: Formats Wagtail renders, which image results may be.
IMAGE_TARGETS = frozenset({"jpg", "jpeg", "png", "webp", "avif", "gif"})


def _rules(mapping: Mapping[str, str], prefix: str) -> list[Rule]:
    by_target: dict[str, list[str]] = {}
    for source, target in mapping.items():
        by_target.setdefault(target, []).append(source)
    options = conf.wagtail_options()
    return [
        Rule(
            field="file",
            sources=sources,
            to=target,
            options=options.get(target, {}),
            name=f"{prefix}:{target}",
        )
        for target, sources in by_target.items()
    ]


def image_rules() -> list[Rule]:
    return _rules(conf.wagtail_images(), "wagtail-images")


def document_rules() -> list[Rule]:
    return _rules(conf.wagtail_documents(), "wagtail-documents")


def image_target(file_name: str) -> str | None:
    """The format an uploaded image of this name becomes, or ``None`` to keep it."""
    return conf.wagtail_images().get(extension(file_name))
