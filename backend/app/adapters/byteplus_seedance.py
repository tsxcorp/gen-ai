"""BytePlus ModelArk Seedance (2.5, 2.0, 2.0 Fast, 2.0 Mini): async task API.

NOT TESTED LIVE (no key available). Built from plans/reports/research-video-params.md 2.2 and 3; error codes marked
[?] come from vendor docs not verified against a real account.
  submit  POST /api/v3/contents/generations/tasks            -> {id}
  poll    GET  /api/v3/contents/generations/tasks/{id}       -> status queued|running|succeeded|failed|expired|cancelled
  cancel  DELETE .../{id} only while status == queued (never deletes a running task)
Result URLs live 24 hours: the video is streamed to disk right after `succeeded` (no credentials are sent to the
pre-signed URL). A successful submit is never repeated (invariant 14).
Secrets: the key is only in the Authorization header of requests to ark.<region>.bytepluses.com.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.adapters.base import (
    Downloaded,
    OutputRef,
    PollResult,
    SubmitHandle,
    apply_params,
    b64,
    input_images,
    write_outputs,
)
from app.adapters.http_common import HardenedClient, https_host, is_ip_literal
from app.errors import AdapterError, ApiError
from app.providers import DEFAULT_BYTEPLUS_REGION, REGION_RE, SECRET_RE
from app.schemas import InputAsset, Job, ModelManifest

HOST_SUFFIX = ".bytepluses.com"
TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
# Invariant 17: `blocked` only from structured error codes. [?] code family taken from ModelArk error-code docs.
SENSITIVE_RE = re.compile(r"^(Input|Output)(Text|Image|Video|Audio)SensitiveContentDetected(\.[A-Za-z]+)?$")
QUOTA_CODES = {"QuotaExceeded", "RateLimitExceeded", "TooManyRequests", "RequestBurstTooFast", "ServerOverloaded",
               "SetLimitExceeded"}  # [?]
AUTH_CODES = {"AuthenticationError", "AccessDenied", "AccountOverdue", "InvalidAccountStatus"}  # [?]


def ark_host(region: str) -> str:
    """ark.<region>.bytepluses.com; the region is validated because it becomes part of the host name."""
    if len(region) > 32 or not REGION_RE.fullmatch(region):
        raise AdapterError("invalid", "invalid BytePlus region", before_send=True)
    host = f"ark.{region}{HOST_SUFFIX}"
    assert host.endswith(HOST_SUFFIX)
    return host


def assert_ark_url(url: str, region: str) -> None:
    if https_host(url) != ark_host(region):
        raise AdapterError("invalid", "refusing to send credentials to a host other than ark.<region>.bytepluses.com",
                           before_send=True)


def assert_download_url(url: str) -> None:
    """Pre-signed result URL: https, a *.bytepluses.com name (not an IP literal), never sent credentials."""
    host = https_host(url)
    if not host or is_ip_literal(host) or not host.endswith(HOST_SUFFIX) or host == HOST_SUFFIX.lstrip("."):
        raise AdapterError("invalid", "provider returned a download URL outside bytepluses.com")


@dataclass
class ByteplusConfig:
    api_key: str = field(repr=False)
    region: str = DEFAULT_BYTEPLUS_REGION

    @classmethod
    def from_providers(cls, cfg: dict[str, Any] | None) -> ByteplusConfig | None:
        if not isinstance(cfg, dict) or not isinstance(cfg.get("apiKey"), str) or not cfg["apiKey"]:
            return None
        region = cfg.get("region") or DEFAULT_BYTEPLUS_REGION
        if not SECRET_RE.fullmatch(cfg["apiKey"]) or not isinstance(region, str) or not (
                len(region) <= 32 and REGION_RE.fullmatch(region)):
            raise ApiError("invalid", "byteplus provider configuration has an invalid format")
        return cls(api_key=cfg["apiKey"], region=region)


def normalize_error(status: int, body: Any) -> AdapterError:
    msg, code = "", ""
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict):
            msg = str(err.get("message", ""))[:500]
            code = str(err.get("code") or "")
    msg = msg or f"HTTP {status}"
    if status == 429 or code in QUOTA_CODES:
        return AdapterError("quota", msg)
    if status in (401, 403) or code in AUTH_CODES:
        return AdapterError("auth", msg)
    if status == 400 and SENSITIVE_RE.fullmatch(code):
        return AdapterError("blocked", msg)
    if status in (408, 504):
        return AdapterError("timeout", msg)
    if status >= 500:
        return AdapterError("network", msg)
    return AdapterError("invalid", msg)


def parse_task(task: Any) -> PollResult:
    """Pure: GET task response -> PollResult."""
    if not isinstance(task, dict):
        return PollResult(state="failed", error=AdapterError("invalid", "unexpected task response"))
    status = str(task.get("status") or "")
    if status in ("queued", "running", ""):
        return PollResult(state="running")
    if status == "succeeded":
        url = (task.get("content") or {}).get("video_url")
        if not isinstance(url, str) or not url:
            return PollResult(state="failed", error=AdapterError("invalid", "task succeeded without a video_url"))
        return PollResult(state="done", outputs=[OutputRef(mime="video/mp4", uri=url)])
    if status == "expired":
        return PollResult(state="failed", error=AdapterError("timeout", "task expired before it finished"))
    if status in ("cancelled", "canceled"):
        return PollResult(state="failed", error=AdapterError("invalid", "task was cancelled"))
    if status == "failed":
        err = task.get("error") if isinstance(task.get("error"), dict) else {}
        code, msg = str(err.get("code") or ""), str(err.get("message") or "task failed")[:300]
        if SENSITIVE_RE.fullmatch(code):
            kind = "blocked"
        elif code in QUOTA_CODES:
            kind = "quota"
        elif code in AUTH_CODES:
            kind = "auth"
        else:
            kind = "invalid"  # unknown codes are never treated as transient (that would pay again)
        return PollResult(state="failed", error=AdapterError(kind, f"{msg} ({code})" if code else msg))
    return PollResult(state="running")  # unknown status: keep polling, the job timeout bounds it


class ArkClient(HardenedClient):
    def __init__(self, cfg: ByteplusConfig, http: httpx.AsyncClient | None = None):
        self.region = cfg.region
        self.base = f"https://{ark_host(cfg.region)}/api/v3"
        super().__init__("BytePlus", {"Authorization": f"Bearer {cfg.api_key}"},
                         lambda url: assert_ark_url(url, cfg.region), normalize_error, http,
                         httpx.Timeout(60.0, connect=15.0))

    async def test(self) -> None:
        """Free auth check: list the account's tasks (page of 1)."""
        await self.request("GET", f"{self.base}/contents/generations/tasks", params={"page_num": 1, "page_size": 1})


def _image_item(img: InputAsset, role: str) -> dict[str, Any]:
    if img.data is None:
        raise AdapterError("invalid", "reference image bytes are not available")
    return {"type": "image_url", "image_url": {"url": f"data:{img.mime};base64,{b64(img.data)}"}, "role": role}


class SeedanceAdapter:
    poll_interval_s = None  # settings.pollIntervalSeconds

    def __init__(self, manifest: ModelManifest, client: ArkClient | None = None):
        self.m = manifest
        self.client = client

    def build_payload(self, job: Job) -> dict[str, Any]:
        content: list[dict[str, Any]] = [{"type": "text", "text": job.prompt}]
        first = input_images(job, "first_frame")
        last = input_images(job, "last_frame")
        if first:
            content.append(_image_item(first[0], "first_frame"))
        if last:
            content.append(_image_item(last[0], "last_frame"))  # requires first_frame (manifest `required`)
        payload: dict[str, Any] = {"model": self.m.api_model, "content": content}
        apply_params(self.m, job, payload)  # resolution, ratio, duration, generate_audio, watermark (top-level)
        return payload

    def _task_url(self, task_id: str) -> str:
        assert self.client is not None, "BytePlus is not configured"
        if not TASK_ID_RE.fullmatch(task_id):
            raise AdapterError("invalid", "provider returned a malformed task id")
        return f"{self.client.base}/contents/generations/tasks/{task_id}"

    async def submit(self, job: Job) -> SubmitHandle:
        assert self.client is not None, "BytePlus is not configured"
        resp = await self.client.request("POST", f"{self.client.base}/contents/generations/tasks",
                                         json_body=self.build_payload(job))
        task_id = resp.get("id") if isinstance(resp, dict) else None
        if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
            raise AdapterError("invalid", "task creation returned no valid task id")
        return SubmitHandle(id=task_id)

    async def poll(self, handle: SubmitHandle) -> PollResult:
        assert self.client is not None
        return parse_task(await self.client.request("GET", self._task_url(handle.id)))

    async def cancel(self, handle: SubmitHandle) -> bool:
        """Best effort: only a task that is still `queued` can be cancelled; a running task is left alone."""
        assert self.client is not None
        task = await self.client.request("GET", self._task_url(handle.id))
        if not isinstance(task, dict) or task.get("status") != "queued":
            return False
        await self.client.request("DELETE", self._task_url(handle.id))
        return True

    async def download(self, outputs: list[OutputRef], dest: Path) -> list[Downloaded]:
        assert self.client is not None
        client = self.client

        async def fetch(uri: str, path: Path) -> tuple[int, str]:
            return await client.stream_to_file(uri, path, assert_url=assert_download_url, auth=False)

        return await write_outputs(outputs, dest, fetch)
