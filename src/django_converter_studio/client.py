"""The Converter Studio client, configured from the Django settings.

>>> from django_converter_studio import open_client
>>> with open_client() as client:
...     print(client.account().credits)
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import httpx
from converter_studio import ConverterStudio, MissingApiKeyError

from . import conf
from ._version import __version__

#: Sent on every request in X-Converter-Studio-Client and in front of the User-Agent (the Python
#: client's ``client_name``), for usage statistics only.
CLIENT_NAME = f"django/{__version__}"


def http_transport() -> httpx.BaseTransport | None:
    """The transport requests go through; ``None`` is HTTPX's own (tests put a fake API here)."""
    return None


def require_api_key() -> str:
    key = conf.api_key()
    if key is None:
        raise MissingApiKeyError(
            "No Converter Studio API key: set CONVERTER_STUDIO_API_KEY in the settings or the "
            "environment. Create a key at https://converter.studio/account#api-keys."
        )
    return key


@contextmanager
def open_client(
    *, api_key: str | None = None, base_url: str | None = None, max_retries: int = 2
) -> Iterator[ConverterStudio]:
    """A :class:`converter_studio.ConverterStudio` with the key and address from the settings;
    its connections are closed when the ``with`` block ends."""
    timeout = httpx.Timeout(conf.REQUEST_TIMEOUT)
    http = httpx.Client(transport=http_transport(), timeout=timeout, follow_redirects=False)
    try:
        client = ConverterStudio(
            api_key=api_key if api_key is not None else conf.api_key(),
            base_url=base_url or conf.base_url(),
            timeout=timeout,
            max_retries=max_retries,
            http_client=http,
            client_name=CLIENT_NAME,
        )
        yield client
    finally:
        http.close()
