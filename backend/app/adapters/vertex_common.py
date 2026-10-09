"""Shared Vertex plumbing: service-account auth (google-auth), httpx calls, error normalisation.

NOT TESTED LIVE (no key available). Error mapping is derived from public Vertex conventions.
Secrets: tokens and key material are never logged nor put in exception messages.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import socket
import ssl
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import requests

from app.adapters.base import run_output_thread
from app.errors import AdapterError, ApiError

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
JSON_THREAD_BYTES = 1024 * 1024  # parse bigger bodies off the event loop

# Invariant 13: shapes accepted for values that end up inside a URL carrying a Bearer token.
LOCATION_RE = re.compile(r"^[a-z]+-[a-z0-9]+[0-9]$")
PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]$")

# Invariant 17: `blocked` only from structured provider fields (exact enum values), never from free text.
BLOCK_REASONS = {
    "SAFETY", "IMAGE_SAFETY", "PROHIBITED_CONTENT", "IMAGE_PROHIBITED_CONTENT", "BLOCKLIST", "SPII",
    "RAI_FILTERED", "RAI_MEDIA_FILTERED", "BLOCKED_BY_SAFETY", "BLOCKED_REASON_SAFETY", "BLOCKED",
}


def valid_location(v: str) -> bool:
    return v == "global" or bool(LOCATION_RE.fullmatch(v))


def valid_project(v: str) -> bool:
    return bool(PROJECT_RE.fullmatch(v))


def valid_bucket(v: str) -> bool:
    return bool(BUCKET_RE.fullmatch(v)) and ".." not in v and not re.fullmatch(r"\d+(\.\d+){3}", v)


def validate_vertex_fields(project: str, location: str, bucket: str | None) -> None:
    """Raise ApiError(invalid) when a field has a shape that could redirect the request."""
    if not valid_project(project):
        raise ApiError("invalid", "projectId has an invalid format (lowercase letters, digits, hyphens; 6-30 chars)")
    if not valid_location(location):
        raise ApiError("invalid", "location must be 'global' or a region like us-central1")
    if bucket is not None and not valid_bucket(bucket):
        raise ApiError("invalid", "gcsBucket has an invalid bucket-name format")


def assert_google_url(url: str) -> None:
    """The Bearer token is only ever sent to https://*.googleapis.com (invariant 13)."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.username or parts.password or not (
            host == "googleapis.com" or host.endswith(".googleapis.com")):
        raise AdapterError("invalid", "refusing to send credentials to a non-googleapis.com host", before_send=True)


@dataclass
class VertexConfig:
    project_id: str
    location: str = "us-central1"
    gcs_bucket: str | None = None
    service_account_info: dict[str, Any] | None = None
    service_account_path: str | None = None
    auth_method: str = "service_account"  # "adc": google.auth.default (gcloud application-default login), no key file

    @classmethod
    def from_providers(cls, cfg: dict[str, Any] | None) -> VertexConfig | None:
        if not cfg or not cfg.get("projectId"):
            return None
        adc = cfg.get("authMethod") == "adc"
        if not adc and not (cfg.get("serviceAccountJson") or cfg.get("serviceAccountPath")):
            return None
        info = None if adc else cfg.get("serviceAccountJson")
        if isinstance(info, str):
            info = json.loads(info)
        location = cfg.get("location") or "us-central1"
        bucket = cfg.get("gcsBucket") or None
        validate_vertex_fields(str(cfg["projectId"]), str(location), bucket)  # providers.json may be hand-edited
        return cls(
            project_id=cfg["projectId"], location=location,
            gcs_bucket=bucket, service_account_info=info,
            service_account_path=None if adc else cfg.get("serviceAccountPath"),
            auth_method="adc" if adc else "service_account",
        )


def host(location: str) -> str:
    if not valid_location(location):
        raise AdapterError("invalid", "invalid Vertex location", before_send=True)
    return "aiplatform.googleapis.com" if location == "global" else f"{location}-aiplatform.googleapis.com"


def _detail_reasons(body: Any) -> set[str]:
    """Collect structured reason-like fields: error.details[].reason, error.errors[].reason, blockReason..."""
    found: set[str] = set()
    if not isinstance(body, dict):
        return found
    err = body.get("error", body)
    if not isinstance(err, dict):
        return found
    for key in ("details", "errors"):
        for d in err.get(key) or []:
            if isinstance(d, dict):
                for k in ("reason", "blockReason", "finishReason"):
                    if isinstance(d.get(k), str):
                        found.add(d[k].upper())
    for k in ("reason", "blockReason", "finishReason"):
        for src in (err, body):
            if isinstance(src.get(k), str):
                found.add(src[k].upper())
    fb = body.get("promptFeedback")
    if isinstance(fb, dict) and isinstance(fb.get("blockReason"), str):
        found.add(fb["blockReason"].upper())
    return found


def is_structured_block(body: Any) -> bool:
    return bool(_detail_reasons(body) & BLOCK_REASONS) or (
        isinstance(body, dict) and bool(body.get("raiMediaFilteredCount")))


def normalize_error(status: int, body: Any) -> AdapterError:
    msg = ""
    gstatus = ""
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict):
            msg = str(err.get("message", ""))[:500]
            gstatus = str(err.get("status", ""))
    msg = msg or f"HTTP {status}"
    if status == 429 or gstatus == "RESOURCE_EXHAUSTED":
        return AdapterError("quota", msg)
    if status in (401, 403) or gstatus in ("UNAUTHENTICATED", "PERMISSION_DENIED"):
        return AdapterError("auth", msg)
    if status == 400 or gstatus in ("INVALID_ARGUMENT", "FAILED_PRECONDITION"):
        # structured fields only: a parameter bug must never be presented as a content block
        return AdapterError("blocked" if is_structured_block(body) else "invalid", msg)
    if status in (408, 504) or gstatus == "DEADLINE_EXCEEDED":
        return AdapterError("timeout", msg)
    if status == 404:
        return AdapterError("invalid", f"not found: {msg}")
    return AdapterError("network", msg)


class VertexClient:
    def __init__(self, cfg: VertexConfig, http: httpx.AsyncClient | None = None, timeout: float = 120.0):
        self.cfg = cfg
        self._http = http
        self._timeout = timeout
        self._creds: Any = None
        self._auth_request: Any = None
        self._auth_timeout = min(timeout, 30.0)
        self._token_task: asyncio.Task[str] | None = None
        self._close_task: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def http(self) -> httpx.AsyncClient:
        if self._closed:
            raise AdapterError("network", "Vertex client is closed; current Vertex request was not sent", before_send=True)
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._timeout, follow_redirects=False)
        return self._http

    def _load_creds(self) -> Any:
        if self.cfg.auth_method == "adc":
            import google.auth

            creds, _ = google.auth.default(scopes=SCOPES)  # user creds from `gcloud auth application-default login`
            return creds
        from google.oauth2 import service_account

        if self.cfg.service_account_info:
            return service_account.Credentials.from_service_account_info(self.cfg.service_account_info, scopes=SCOPES)
        return service_account.Credentials.from_service_account_file(self.cfg.service_account_path, scopes=SCOPES)

    def _token_sync(self) -> str:
        from google.auth.transport.requests import Request

        if self._creds is None:
            self._creds = self._load_creds()
        if not self._creds.valid:
            if self._auth_request is None:
                self._auth_request = Request()
            self._creds.refresh(self._request_token)
        token = self._creds.token
        if not isinstance(token, str) or not token:
            raise ValueError("credentials returned no token")
        return token

    def _request_token(self, url: str, method: str = "GET", body: Any = None,
                       headers: Any = None, timeout: float | None = None, **kwargs: Any) -> Any:
        from google.auth.exceptions import TransportError

        bound = min(timeout, self._auth_timeout) if isinstance(timeout, (int, float)) and timeout > 0 else self._auth_timeout
        try:
            return self._auth_request(url, method=method, body=body, headers=headers, timeout=bound, **kwargs)
        except OSError as error:
            raise TransportError(error) from error

    @staticmethod
    def _transport_reason(error: Exception) -> str:
        pending: list[BaseException] = [error]
        seen: set[int] = set()
        causes: list[BaseException] = []
        while pending and len(seen) < 24:
            cause = pending.pop()
            if id(cause) in seen:
                continue
            seen.add(id(cause))
            causes.append(cause)
            pending.extend(arg for arg in cause.args if isinstance(arg, BaseException))
            pending.extend(nested for nested in (cause.__cause__, cause.__context__, getattr(cause, "reason", None))
                           if isinstance(nested, BaseException))
        if any(isinstance(cause, (requests.exceptions.SSLError, ssl.SSLError)) for cause in causes):
            return "TLS/certificate connection failed"
        if any(isinstance(cause, requests.exceptions.ProxyError) for cause in causes):
            return "proxy connection failed"
        if any(isinstance(cause, socket.gaierror) or type(cause).__name__ == "NameResolutionError" for cause in causes):
            return "DNS resolution failed"
        if any(isinstance(cause, (requests.exceptions.Timeout, TimeoutError)) for cause in causes):
            return "token service connection timed out"
        return "token service connection failed"

    async def _refresh_token(self) -> str:
        from google.auth.exceptions import RefreshError, TransportError

        try:
            return await asyncio.to_thread(self._token_sync)
        except TransportError as error:
            reason = self._transport_reason(error)
            raise AdapterError("network", f"cannot obtain access token: TransportError ({reason}); current Vertex request was not sent",
                               before_send=True) from None
        except RefreshError as error:
            if error.retryable:
                raise AdapterError("network", "cannot obtain access token: token service temporarily unavailable; current Vertex request was not sent",
                                   before_send=True) from None
            raise AdapterError("auth", "cannot obtain access token: credentials rejected (RefreshError)") from None
        except Exception as error:
            raise AdapterError("auth", f"cannot obtain access token: {type(error).__name__}") from None

    @staticmethod
    def _consume_token_result(task: asyncio.Task[str]) -> None:
        if not task.cancelled():
            task.exception()

    async def _auth_headers(self) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {await self.token()}"}
        if self.cfg.auth_method == "adc":  # user ADC has no quota project of its own; project id is regex-validated
            headers["x-goog-user-project"] = self.cfg.project_id
        return headers

    async def token(self) -> str:
        if self._closed:
            raise AdapterError("network", "Vertex client is closed; current Vertex request was not sent", before_send=True)
        if self._creds is not None and self._creds.valid and isinstance(self._creds.token, str) and self._creds.token:
            return self._creds.token
        if self._token_task is None or self._token_task.done():
            self._token_task = asyncio.create_task(self._refresh_token())
            self._token_task.add_done_callback(self._consume_token_result)
        return await asyncio.shield(self._token_task)

    def _map_transport(self, e: Exception) -> AdapterError:
        # connection never established -> request provably not sent -> safe to resubmit
        before = isinstance(e, httpx.ConnectError | httpx.ConnectTimeout | httpx.PoolTimeout)
        if isinstance(e, httpx.TimeoutException):
            if before:
                return AdapterError("network", "could not connect to Vertex (timeout)", before_send=True)
            return AdapterError("timeout", "request to Vertex timed out")
        return AdapterError("network", f"network error: {type(e).__name__}", before_send=before)

    async def request(self, method: str, url: str, json_body: Any = None, raw: bool = False) -> Any:
        assert_google_url(url)
        headers = await self._auth_headers()
        try:
            r = await self.http.request(method, url, json=json_body, headers=headers)
        except httpx.TransportError as e:
            raise self._map_transport(e) from None
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = {}
            raise normalize_error(r.status_code, body)
        if raw:
            return r
        try:
            if len(r.content) > JSON_THREAD_BYTES:
                return await asyncio.to_thread(r.json)
            return r.json()
        except ValueError:
            raise AdapterError("network", "provider returned a non-JSON response") from None

    async def stream_to_file(self, url: str, dest: Path) -> tuple[int, str]:
        """GET `url` straight to `dest` in chunks; sha256 computed while writing (invariant 19)."""
        assert_google_url(url)
        headers = await self._auth_headers()
        h = hashlib.sha256()
        size = 0
        try:
            async with self.http.stream("GET", url, headers=headers) as r:
                if r.status_code >= 400:
                    await r.aread()
                    try:
                        body = r.json()
                    except ValueError:
                        body = {}
                    raise normalize_error(r.status_code, body)
                with dest.open("wb") as f:
                    async for chunk in r.aiter_bytes(1024 * 1024):
                        await run_output_thread(f.write, chunk)
                        h.update(chunk)
                        size += len(chunk)
        except httpx.TransportError as e:
            dest.unlink(missing_ok=True)
            raise self._map_transport(e) from None
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
        return size, h.hexdigest()

    async def aclose(self) -> None:
        self._closed = True
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)

    async def _close(self) -> None:
        try:
            if self._token_task is not None:
                try:
                    await asyncio.shield(self._token_task)
                except AdapterError:
                    pass
            if self._http is not None:
                await self._http.aclose()
        finally:
            if self._auth_request is not None:
                session = self._auth_request.session
                self._auth_request.session = None
                if session is not None:
                    await asyncio.to_thread(session.close)

    async def test(self) -> None:
        """Auth check: just obtain a token."""
        await self.token()
