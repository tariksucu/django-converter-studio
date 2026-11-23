"""Converting files from your own code: read through any storage, the result as a Django ``File``.

>>> from django_converter_studio import convert, convert_to_storage, extract_text
>>> with convert(photo.image, "jpg") as result:        # a FieldFile, an UploadedFile, a File...
...     photo.preview.save(result.name, result.file)
>>> name = convert_to_storage(report.file, "pdf")        # saved through report.file's storage
>>> text = extract_text(scan.file)                       # OCR for pictures and scanned PDFs
"""

from __future__ import annotations

import mimetypes
import os
import posixpath
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import IO, Any, TypeAlias, cast

from converter_studio import Account, Conversion, ConverterStudio
from django.core.files import File
from django.core.files.storage import Storage, default_storage
from django.db.models.fields.files import FieldFile

from . import conf
from .client import open_client, require_api_key
from .formats import extension, normalize

#: Results are kept in memory up to this size, then in a temporary file.
SPOOL_BYTES = 10 * 1024 * 1024

Source: TypeAlias = "File[Any] | str | os.PathLike[str] | bytes | IO[bytes]"
"""What can be converted: a ``FieldFile`` (read through its storage), any Django ``File``
(an upload), a path, bytes (with ``file_name``) or a binary file object."""


@dataclass
class ConvertedFile:
    """A finished conversion's result. ``file`` is a Django ``File`` (kept in memory up to 10 MB,
    then in a temporary file); save it with ``storage.save(name, result.file)`` or
    ``field_file.save(result.name, result.file)``. Close it, or use it in a ``with`` block."""

    name: str
    file: File[Any]
    size: int
    conversion: Conversion = field(repr=False)

    @property
    def credits(self) -> int | None:
        """What the conversion cost, in credits."""
        return self.conversion.credits

    @property
    def content_type(self) -> str:
        return mimetypes.guess_type(self.name)[0] or "application/octet-stream"

    def read_text(self, encoding: str = "utf-8") -> str:
        """The result as text (for ``txt``, ``md``, ``csv``...), without a byte-order mark."""
        self.file.seek(0)
        data = self.file.read()
        self.file.seek(0)
        return cast(bytes, data).decode(encoding, errors="replace").removeprefix("﻿")

    def close(self) -> None:
        self.file.close()

    def __enter__(self) -> ConvertedFile:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def source_name(source: Source, file_name: str | None = None) -> str:
    """The name a source is sent under (its last part): the API reads the format from it."""
    if file_name:
        return posixpath.basename(file_name.replace("\\", "/"))
    if isinstance(source, str | os.PathLike):
        return Path(source).name
    name = getattr(source, "name", None)
    if isinstance(name, str) and name:
        return posixpath.basename(name.replace("\\", "/"))
    raise ValueError("file_name is needed for this source (for example 'photo.heic')")


@contextmanager
def _readable(source: Source) -> Iterator[Any]:
    """What the client uploads: a path, bytes, or a binary file object at its start."""
    if isinstance(source, str | os.PathLike | bytes | bytearray | memoryview):
        yield source
        return
    if isinstance(source, File):
        # A FieldFile opens through its field's storage, whatever it is; a file that was closed
        # is closed again afterwards, one that was open (an upload) is left open.
        opened_here = source.closed
        if opened_here:
            source.open("rb")
        try:
            yield _rewound(source.file if source.file is not None else source)
        finally:
            if opened_here:
                source.close()
        return
    yield _rewound(source)


def _rewound(stream: Any) -> Any:
    try:
        if stream.seekable():
            stream.seek(0)
    except (AttributeError, ValueError, OSError):
        pass
    return stream


def result_name(conversion: Conversion, source: str, to: str) -> str:
    """The result's file name: the source's name with the result's extension."""
    produced = posixpath.basename((conversion.output_name or "").replace("\\", "/"))
    ext = extension(produced) or normalize(conversion.to_format or to)
    stem = source.rsplit(".", 1)[0] if "." in source.strip(".") else source
    return f"{stem or 'file'}.{ext}"


def download(client: ConverterStudio, conversion: Conversion, name: str) -> ConvertedFile:
    """The finished conversion's result as a :class:`ConvertedFile`."""
    spool = tempfile.SpooledTemporaryFile(max_size=SPOOL_BYTES)  # noqa: SIM115 (ConvertedFile)
    try:
        for chunk in client.iter_download(conversion):
            spool.write(chunk)
        size = spool.tell()
        spool.seek(0)
    except BaseException:
        spool.close()
        raise
    return ConvertedFile(name=name, file=File(spool, name=name), size=size, conversion=conversion)


def convert(
    source: Source,
    to: str,
    *,
    file_name: str | None = None,
    options: Mapping[str, object] | None = None,
    max_credits: int | None = None,
    timeout: float | None = None,
    client: ConverterStudio | None = None,
) -> ConvertedFile:
    """Converts ``source`` to ``to`` (``"jpg"``, ``"pdf"``, ``"txt"``, ``"mp4"``...), waits for
    it and returns the result.

    ``options``: the API's conversion settings (``{"quality": "high"}``; see
    https://converter.studio/developers). ``max_credits``: the most it may cost to start on its
    own (``CONVERTER_STUDIO_MAX_CREDITS``, 20); a dearer one raises
    ``converter_studio.ConfirmationRequiredError`` and costs nothing. ``timeout``: seconds to
    wait (``CONVERTER_STUDIO_TIMEOUT``). Errors are ``converter_studio`` exceptions whose
    message is the API's own sentence, meant for people.
    """
    name = source_name(source, file_name)
    target = normalize(to)
    with ExitStack() as stack:
        if client is None:
            require_api_key()
            client = stack.enter_context(open_client())
        with _readable(source) as readable:
            conversion = client.convert(
                readable,
                target,
                file_name=name,
                options=options,
                max_credits=conf.max_credits() if max_credits is None else max_credits,
                timeout=conf.timeout() if timeout is None else timeout,
            )
        return download(client, conversion, result_name(conversion, name, target))


def convert_to_storage(
    source: Source,
    to: str,
    *,
    name: str | None = None,
    storage: Storage | None = None,
    **kwargs: Any,
) -> str:
    """Converts ``source`` and saves the result through ``storage`` (the source's own storage
    for a ``FieldFile``, else ``default_storage``), next to the source unless ``name`` is
    given. Returns the name the storage saved it under. ``kwargs`` are those of
    :func:`convert`."""
    if storage is None:
        storage = source.storage if isinstance(source, FieldFile) else default_storage
    with convert(source, to, **kwargs) as result:
        if name is None:
            folder = posixpath.dirname(source.name or "") if isinstance(source, FieldFile) else ""
            name = posixpath.join(folder, result.name) if folder else result.name
        return storage.save(name, result.file)


def extract_text(
    source: Source, *, options: Mapping[str, object] | None = None, **kwargs: Any
) -> str:
    """The text of a picture (OCR), a PDF (scanned pages read by OCR) or a document."""
    settings = dict(options or {})
    name = source_name(source, kwargs.get("file_name"))
    if extension(name) == "pdf":
        settings.setdefault("ocr", True)
    with convert(source, "txt", options=settings, **kwargs) as result:
        return result.read_text().strip()


def account() -> Account:
    """The API key's account: plan, credits left, limits."""
    require_api_key()
    with open_client() as client:
        return client.account()
