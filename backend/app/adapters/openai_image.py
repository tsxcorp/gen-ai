"""OpenAI gpt-image-2.5 (sunburst / flare) via the Images API: /v1/images/generations and /v1/images/edits.

NOT TESTED LIVE (no key available). Built from plans/reports/research-image-params.md 2b; fields marked [?] in
the manifests are unverified. The API is synchronous and returns base64 only: `submit` does the whole request and
keeps the images for `poll`, so a successful submit is never repeated (invariant 14).
Secrets: the key is only in the Authorization header of requests to api.openai.com; never logged or echoed.
"""
from __future__ import annotations

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
    inline_output,
    input_images,
    write_outputs,
)
from app.adapters.http_common import HardenedClient, https_host
from app.core.storage import EXT
from app.errors import AdapterError, ApiError
from app.providers import IDENT_RE, SECRET_RE
from app.schemas import Job, ModelManifest

OPENAI_HOST = "api.openai.com"
BASE_URL = f"https://{OPENAI_HOST}/v1"
# Invariant 17: `blocked` only from the structured `error.code` (exact values), never from free text.
BLOCK_CODES = {"moderation_blocked", "content_policy_violation"}
MIME_BY_FORMAT = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
FORM_FIELDS = ("model", "prompt", "n", "size", "quality", "output_format", "output_compression", "background",
               "moderation")


def assert_openai_url(url: str) -> None:
    """The API key is only ever sent to https://api.openai.com."""
    if https_host(url) != OPENAI_HOST:
        raise AdapterError("invalid", "refusing to send credentials to a host other than api.openai.com",
                           before_send=True)


@dataclass
class OpenAIConfig:
    api_key: str = field(repr=False)
    organization: str | None = None
    project: str | None = None

    @classmethod
    def from_providers(cls, cfg: dict[str, Any] | None) -> OpenAIConfig | None:
        if not isinstance(cfg, dict) or not isinstance(cfg.get("apiKey"), str) or not cfg["apiKey"]:
            return None
        org, proj = cfg.get("organization") or None, cfg.get("project") or None
        # providers.json may be hand-edited: header values must keep a strict shape
        if not SECRET_RE.fullmatch(cfg["apiKey"]) or any(v is not None and not (
                isinstance(v, str) and IDENT_RE.fullmatch(v)) for v in (org, proj)):
            raise ApiError("invalid", "openai provider configuration has an invalid format")
        return cls(api_key=cfg["apiKey"], organization=org, project=proj)


def normalize_error(status: int, body: Any) -> AdapterError:
    msg, code = "", ""
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict):
            msg = str(err.get("message", ""))[:500]
            code = str(err.get("code") or "")
    msg = msg or f"HTTP {status}"
    if status == 429:
        return AdapterError("quota", msg)
    if status in (401, 403):
        return AdapterError("auth", msg)
    if status == 400 and code in BLOCK_CODES:
        return AdapterError("blocked", msg)
    if status in (408, 504):
        return AdapterError("timeout", msg)
    if status >= 500:
        return AdapterError("network", msg)
    return AdapterError("invalid", msg)  # 400/404/409/422 and anything unrecognised: never "blocked" by guesswork


def parse_images_response(resp: Any, fallback_format: str = "png") -> list[OutputRef]:
    """Pure: Images API response -> outputs (base64 only), or a normalised AdapterError."""
    data = resp.get("data") if isinstance(resp, dict) else None
    mime = MIME_BY_FORMAT.get(str(resp.get("output_format") or fallback_format), "image/png") if isinstance(
        resp, dict) else "image/png"
    outs: list[OutputRef] = []
    for item in data or []:
        if isinstance(item, dict) and isinstance(item.get("b64_json"), str) and item["b64_json"]:
            outs.append(inline_output(mime, item["b64_json"]))
    if not outs:
        raise AdapterError("invalid", "OpenAI returned no image data")
    return outs


class OpenAIClient(HardenedClient):
    def __init__(self, cfg: OpenAIConfig, http: httpx.AsyncClient | None = None):
        headers = {"Authorization": f"Bearer {cfg.api_key}"}
        if cfg.organization:
            headers["OpenAI-Organization"] = cfg.organization
        if cfg.project:
            headers["OpenAI-Project"] = cfg.project
        # generation can take up to ~2 minutes: long read timeout, short connect timeout
        super().__init__("OpenAI", headers, assert_openai_url, normalize_error, http,
                         httpx.Timeout(300.0, connect=15.0, pool=30.0))

    async def test(self) -> None:
        """Free auth check: list models."""
        await self.request("GET", f"{BASE_URL}/models")


class OpenAIImageAdapter:
    poll_interval_s = 0.0

    def __init__(self, manifest: ModelManifest, client: OpenAIClient | None = None):
        self.m = manifest
        self.client = client

    def _edit(self, job: Job) -> bool:
        return job.mode == "edit"

    def build_payload(self, job: Job) -> dict[str, Any]:
        """Form/JSON fields of the request. Reference images (edit mode) are shown inline for the raw-request tab;
        `submit` sends them as multipart files. The API key is never part of the payload."""
        payload: dict[str, Any] = {"model": self.m.api_model, "prompt": job.prompt}
        apply_params(self.m, job, payload)
        payload["n"] = job.variant_count
        if payload.get("output_format", "png") == "png":
            payload.pop("output_compression", None)  # only meaningful for jpeg/webp
        if self._edit(job):
            imgs = input_images(job, "reference_images")
            if not imgs:
                raise AdapterError("invalid", "edit mode needs at least one reference image")
            if any(i.data is None for i in imgs):
                raise AdapterError("invalid", "reference image bytes are not available")
            payload["image"] = [{"mimeType": i.mime, "data": b64(i.data or b"")} for i in imgs]
        return payload

    async def submit(self, job: Job) -> SubmitHandle:
        assert self.client is not None, "OpenAI is not configured"
        payload = self.build_payload(job)
        if self._edit(job):
            data = {k: str(v) for k, v in payload.items() if k in FORM_FIELDS and v is not None}
            files = [("image[]", (f"image{i}.{EXT.get(img.mime, 'png')}", img.data or b"", img.mime))
                     for i, img in enumerate(input_images(job, "reference_images"))]
            resp = await self.client.request("POST", f"{BASE_URL}/images/edits", data=data, files=files)
        else:
            resp = await self.client.request("POST", f"{BASE_URL}/images/generations", json_body=payload)
        outs = parse_images_response(resp, str(payload.get("output_format", "png")))
        return SubmitHandle(id=job.id, data={"outputs": outs})

    async def poll(self, handle: SubmitHandle) -> PollResult:
        return PollResult(state="done", outputs=handle.data["outputs"])

    async def download(self, outputs: list[OutputRef], dest: Path) -> list[Downloaded]:
        return await write_outputs(outputs, dest)
