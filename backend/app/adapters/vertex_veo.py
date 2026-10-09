"""Veo 3.1 / Fast / Lite via Vertex predictLongRunning + fetchPredictOperation.

NOT TESTED LIVE. Built from plans/reports/research-video-params.md 2.1 and 3.
`generateAudio`, `compressionQuality`, `resizeMode` come from secondary sources and are marked [?]
in the manifests (verified: false until a live call); durationSeconds is sent as an integer [?].
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

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
from app.adapters.vertex_common import VertexClient, host, normalize_error, valid_bucket
from app.errors import AdapterError
from app.schemas import InputAsset, Job, ModelManifest


def _image_obj(img: InputAsset) -> dict[str, Any]:
    if img.gcs_uri:
        return {"gcsUri": img.gcs_uri, "mimeType": img.mime}
    assert img.data is not None
    return {"bytesBase64Encoded": b64(img.data), "mimeType": img.mime}


# google.rpc.Code values we recognise on a *finished* operation's `error.code`. Anything else is NOT treated as a
# transient network failure (it would be resubmitted and billed again): it surfaces as `invalid`.
_OP_CODE_TO_HTTP = {8: 429, 3: 400, 7: 403, 16: 401, 4: 504}


def parse_operation(op: dict[str, Any]) -> PollResult:
    """Pure: fetchPredictOperation response -> PollResult."""
    if not op.get("done"):
        return PollResult(state="running")
    if op.get("error"):
        e = op["error"]
        status = _OP_CODE_TO_HTTP.get(e.get("code")) if isinstance(e, dict) else None
        if status is None:
            code = e.get("code") if isinstance(e, dict) else None
            msg = str(e.get("message", "") if isinstance(e, dict) else e)[:300]
            return PollResult(state="failed", error=AdapterError("invalid", f"operation failed (code {code}): {msg}"))
        return PollResult(state="failed", error=normalize_error(status, {"error": e}))
    resp = op.get("response") or {}
    outs: list[OutputRef] = []
    for v in resp.get("videos", []):
        mime = v.get("mimeType") or "video/mp4"
        if v.get("bytesBase64Encoded"):
            outs.append(inline_output(mime, v["bytesBase64Encoded"]))
        elif v.get("gcsUri"):
            outs.append(OutputRef(mime=mime, uri=v["gcsUri"]))
    reasons = resp.get("raiMediaFilteredReasons") or []
    filtered = resp.get("raiMediaFilteredCount")
    if not outs:
        if filtered or reasons:
            return PollResult(state="failed", error=AdapterError(
                "blocked", "video blocked by safety filters" + (f": {'; '.join(map(str, reasons))[:300]}" if reasons else "")))
        return PollResult(state="failed", error=AdapterError("invalid", "operation finished without videos"))
    warnings: list[str] = []
    if filtered or reasons:  # partial group: some of the requested videos were filtered out
        warnings.append(f"raiMediaFilteredCount={filtered or len(reasons)}"
                        + (f": {'; '.join(map(str, reasons))[:300]}" if reasons else ""))
    return PollResult(state="done", outputs=outs, warnings=warnings)


class VertexVeoAdapter:
    poll_interval_s = None  # settings.pollIntervalSeconds (Vertex doc samples poll every 15 s)

    def __init__(self, manifest: ModelManifest, client: VertexClient | None = None):
        self.m = manifest
        self.client = client

    def build_payload(self, job: Job) -> dict[str, Any]:
        instance: dict[str, Any] = {"prompt": job.prompt}
        first = input_images(job, "first_frame")
        last = input_images(job, "last_frame")
        if first:
            instance["image"] = _image_obj(first[0])
        if last:
            instance["lastFrame"] = _image_obj(last[0])  # requires `image` (enforced by manifest `required`)
        payload: dict[str, Any] = {"instances": [instance], "parameters": {"sampleCount": job.variant_count}}
        apply_params(self.m, job, payload)
        bucket = self.client.cfg.gcs_bucket if self.client else None
        if bucket:
            payload["parameters"]["storageUri"] = f"gs://{bucket}/aigen/{job.id}/"
        return payload

    def _base(self) -> str:
        assert self.client is not None, "Vertex is not configured"
        loc = self.m.api_location or self.client.cfg.location
        return (f"https://{host(loc)}/v1/projects/{self.client.cfg.project_id}/locations/{loc}"
                f"/publishers/google/models/{self.m.api_model}")

    async def submit(self, job: Job) -> SubmitHandle:
        assert self.client is not None, "Vertex is not configured"
        resp = await self.client.request("POST", f"{self._base()}:predictLongRunning", self.build_payload(job))
        name = resp.get("name")
        if not name:
            raise AdapterError("invalid", "predictLongRunning returned no operation name")
        return SubmitHandle(id=name)

    async def poll(self, handle: SubmitHandle) -> PollResult:
        assert self.client is not None
        op = await self.client.request("POST", f"{self._base()}:fetchPredictOperation", {"operationName": handle.id})
        return parse_operation(op)

    async def download(self, outputs: list[OutputRef], dest: Path) -> list[Downloaded]:
        assert self.client is not None
        client = self.client

        async def fetch(uri: str, path: Path) -> tuple[int, str]:
            return await download_gcs(client, uri, path)

        return await write_outputs(outputs, dest, fetch)


async def download_gcs(client: VertexClient, gs_uri: str, dest: Path) -> tuple[int, str]:
    """Stream gs://bucket/object to `dest`; returns (size, sha256)."""
    bucket, _, obj = gs_uri.removeprefix("gs://").partition("/")
    if not valid_bucket(bucket) or not obj:
        raise AdapterError("invalid", "provider returned a malformed gcsUri")
    url = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o/{quote(obj, safe='')}?alt=media"
    return await client.stream_to_file(url, dest)
