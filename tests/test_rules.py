from __future__ import annotations

import pytest

from django_converter_studio import Rule, formats, register, rules_for, unregister

from .testapp.models import Clip, Photo


def test_rules_normalize_their_formats() -> None:
    rule = Rule(field="file", sources=[".HEIC", "Heif", ""], to=".JPG")
    assert rule.to == "jpg"
    assert rule.sources == frozenset({"heic", "heif"})
    assert rule.name == "file:jpg"
    assert rule.replaces
    assert Rule(field="file", sources=["doc"], to="pdf", target="pdf").name == "file>pdf:pdf"
    with pytest.raises(TypeError, match="list of extensions"):
        Rule(field="file", sources="heic", to="jpg")


@pytest.mark.parametrize(
    ("name", "matches"),
    [
        ("photos/IMG_1.HEIC", True),
        ("IMG_1.heif", True),
        ("IMG_1.jpg", False),
        ("heic", False),
        (".heic", False),
        ("photos.heic/IMG", False),
        ("a.tar.gz", False),
    ],
)
def test_matching_by_extension(name: str, matches: bool) -> None:
    assert Rule(field="f", sources=formats.HEIC, to="jpg").matches(name) is matches


def test_a_file_already_in_the_target_format_is_not_converted() -> None:
    assert not Rule(field="f", sources=formats.VIDEO, to="mp4").matches("clip.mp4")
    assert Rule(field="f", sources=formats.VIDEO, to="mp4").matches("clip.mov")


def test_extensions() -> None:
    assert formats.extension("a/b/c.Tar.GZ") == "tgz"
    assert formats.extension("C:\\photos\\IMG.HEIC") == "heic"
    assert formats.extension("README") == ""
    assert set(formats.OFFICE) >= {"docx", "xlsx", "pptx", "odt"}


def test_where_rules_come_from() -> None:
    assert [rule.name for rule in rules_for(Photo)] == ["image:jpg"]
    assert [rule.name for rule in rules_for(Clip)] == ["video:mp4"]  # registered in apps.py
    register(Photo, Rule(field="image", sources=["png"], to="webp", name="extra"))
    assert [rule.name for rule in rules_for(Photo)] == ["image:jpg", "extra"]
    unregister(Photo)
    assert [rule.name for rule in rules_for(Photo)] == ["image:jpg"]
