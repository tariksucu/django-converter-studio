"""Converter Studio for Django and Wagtail (https://converter.studio).

Convert uploaded files by rule (HEIC and RAW photos to JPG, Office documents to PDF, scans to
text, videos to MP4), from the admin, a management command or your own code::

    from django_converter_studio import ConverterStudioMixin, Rule, formats

    class Photo(ConverterStudioMixin, models.Model):
        image = models.FileField(upload_to="photos/")
        converter_studio_rules = [Rule(field="image", sources=formats.HEIC, to="jpg")]

Documentation: https://converter.studio/developers
"""

from . import formats
from ._version import __version__
from .client import open_client
from .rules import ConverterStudioMixin, Rule, register, rules_for, unregister
from .services import ConvertedFile, account, convert, convert_to_storage, extract_text

__all__ = [
    "ConvertedFile",
    "ConverterStudioMixin",
    "Rule",
    "__version__",
    "account",
    "convert",
    "convert_to_storage",
    "extract_text",
    "formats",
    "open_client",
    "register",
    "rules_for",
    "unregister",
]
