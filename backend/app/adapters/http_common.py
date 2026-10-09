"""Hardened httpx plumbing shared by the OpenAI and BytePlus adapters (same rules as the Vertex client).

- credentials only ever go to hosts accepted by `assert_url` (checked on EVERY request);
- redirects are never followed (a redirect would carry the Authorization header elsewhere);
- downloads stream straight to disk, sha256 computed while writing (invariant 19);
- transport errors are mapped to the standard kinds; `before_send=True` only when the request provably never left;
- secrets are never logged and never put in exception messages (the key lives only in `_headers`).
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.adapters.base import run_output_thread
from app.errors import AdapterError

JSON_THREAD_BYTES = 1024 * 1024  # parse bigger bodies off the event loop
MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024  # a video above 1 GiB is not something this tool expects

Normalize = Callable[[int, Any], AdapterError]
UrlCheck = Callable[[str], None]


def https_host(url: str) -> str:
    """Lower-cased hostname of an https URL without userinfo and with the default port, else ''."""
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        return ""
    if parts.scheme != "https" or parts.username or parts.password or port not in (None, 443):
        return ""
    return (parts.hostname or "").lower()


def is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def map_transport(e: Exception, name: str) -> AdapterError:
    """Connection never established -> the request provably did not reach the provider -> safe to resubmit."""
    before = isinstance(e, httpx.ConnectError | httpx.ConnectTimeout | httpx.PoolTimeout)
    if isinstance(e, httpx.TimeoutException):
        if before:
            return AdapterError("network", f"could not connect to {name} (timeout)", before_send=True)
        return AdapterError("timeout", f"request to {name} timed out")
    return AdapterError("network", f"network error: {type(e).__name__}", before_send=before)


def error_body(r: httpx.Response) -> Any:
    try:
        return r.json()
    except ValueError:
        return {}


class HardenedClient:
    """One provider endpoint. Subclasses (or callers) supply the host check and the error normaliser."""

    def __init__(self, name: str, headers: dict[str, str], assert_url: UrlCheck, normalize: Normalize,
                 http: httpx.AsyncClient | None = None, timeout: httpx.Timeout | None = None):
        self.name = name
        self._headers = headers  # holds the credential: never exposed, never logged
        self._assert_url = assert_url
        self._normalize = normalize
        self._http = http
        self._timeout = timeout or httpx.Timeout(120.0, connect=15.0)

    def __repr__(self) -> str:  # a stray log of the client must not show headers
        return f"<{type(self).__name__} {self.name}>"

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout, follow_redirects=False)
        return self._http

    def _raise_for_status(self, r: httpx.Response) -> None:
        if 300 <= r.status_code < 400:
            raise AdapterError("invalid", f"{self.name} answered with a redirect; redirects are not followed")
        if r.status_code >= 400:
            raise self._normalize(r.status_code, error_body(r))

    async def request(self, method: str, url: str, json_body: Any = None, data: dict[str, str] | None = None,
                      files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
                      params: dict[str, Any] | None = None) -> Any:
        self._assert_url(url)
        try:
            r = await self.http.request(method, url, json=json_body, data=data, files=files, params=params,
                                        headers=self._headers, follow_redirects=False)
        except httpx.TransportError as e:
            raise map_transport(e, self.name) from None
        self._raise_for_status(r)
        if not r.content:
            return {}
        try:
            if len(r.content) > JSON_THREAD_BYTES:
                return await asyncio.to_thread(r.json)
            return r.json()
        except ValueError:
            raise AdapterError("network", f"{self.name} returned a non-JSON response") from None

    async def stream_to_file(self, url: str, dest: Path, assert_url: UrlCheck | None = None,
                             auth: bool = False) -> tuple[int, str]:
        """GET `url` straight to `dest`. Pre-signed result URLs are fetched WITHOUT credentials (auth=False)."""
        (assert_url or self._assert_url)(url)
        h = hashlib.sha256()
        size = 0
        try:
            async with self.http.stream("GET", url, headers=self._headers if auth else {},
                                        follow_redirects=False) as r:
                if r.status_code >= 300:
                    await r.aread()
                    self._raise_for_status(r)
                    raise AdapterError("invalid", f"unexpected HTTP {r.status_code} while downloading")
                with dest.open("wb") as f:
                    async for chunk in r.aiter_bytes(1024 * 1024):
                        size += len(chunk)
                        if size > MAX_DOWNLOAD_BYTES:
                            raise AdapterError("invalid", "download is larger than the allowed maximum")
                        await run_output_thread(f.write, chunk)
                        h.update(chunk)
        except httpx.TransportError as e:
            dest.unlink(missing_ok=True)
            raise map_transport(e, self.name) from None
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
        return size, h.hexdigest()

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
