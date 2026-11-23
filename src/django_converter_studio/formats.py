"""Groups of file extensions for :class:`~django_converter_studio.Rule` ``sources``.

They follow what Converter Studio converts (https://converter.studio/developers); ask the API for
the full, current list with ``open_client().formats()``. Plain constants, safe to import from a
settings module.
"""

from __future__ import annotations

#: iPhone and Android photos.
HEIC: tuple[str, ...] = ("heic", "heif")
#: Camera RAW photos (Canon, Nikon, Sony, Adobe DNG).
RAW: tuple[str, ...] = ("cr2", "nef", "arw", "dng")
#: Vector artwork (to PNG, JPG or SVG).
VECTOR: tuple[str, ...] = ("eps", "ai")
#: Pictures whose text can be read (OCR) to ``txt`` or ``docx``.
OCR_IMAGES: tuple[str, ...] = ("jpg", "jpeg", "png", "webp", "heic", "heif", "tiff", "tif", "bmp")
#: Word processing documents.
DOCUMENTS: tuple[str, ...] = ("doc", "docx", "odt", "rtf")
#: Spreadsheets.
SPREADSHEETS: tuple[str, ...] = ("xls", "xlsx", "ods")
#: Presentations.
PRESENTATIONS: tuple[str, ...] = ("ppt", "pptx", "odp")
#: Everything an office suite opens, for conversions to PDF.
OFFICE: tuple[str, ...] = DOCUMENTS + SPREADSHEETS + PRESENTATIONS
#: Videos (to MP4, WebM or MOV; or their sound to MP3).
VIDEO: tuple[str, ...] = ("mov", "mkv", "avi", "wmv", "flv", "3gp", "webm", "mp4")
#: Audio (to MP3, M4A, OGG, WAV...).
AUDIO: tuple[str, ...] = ("wav", "aiff", "flac", "wma", "m4a", "ogg", "opus", "aac", "mp3")

#: Extensions whose result is text a text field can hold.
TEXT_TARGETS: frozenset[str] = frozenset(
    {"txt", "md", "html", "csv", "json", "xml", "yaml", "srt", "vtt", "ass", "svg"}
)


def extension(name: str) -> str:
    """The lower-case extension of a file name, without the dot (``""`` when it has none)."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    if base.lower().endswith(".tar.gz"):
        return "tgz"
    if "." not in base.strip("."):
        return ""
    return base.rsplit(".", 1)[-1].lower()


def normalize(value: str) -> str:
    """``".JPG"`` -> ``"jpg"``: how extensions and formats are compared."""
    return value.strip().lower().lstrip(".")
