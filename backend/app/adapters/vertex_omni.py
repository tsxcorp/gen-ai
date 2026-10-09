"""Gemini Omni 1.1 Flash via the Interactions API on Vertex.

NOT TESTED LIVE and the least certain adapter: the Vertex Interactions endpoint path, the exact
response shape and where `task` lives are [?] (see requirements Open #1/#2). Everything marked [?]
below must be confirmed with one real call before being treated as fact.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

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
from app.adapters.vertex_common import BLOCK_REASONS, VertexClient, host
from app.adapters.vertex_veo import download_gcs
from app.errors import AdapterError
from app.schemas import InputAsset, Job, ModelManifest

TASK_BY_MODE = {"t2v": "text_to_video", "i2v": "image_to_video", "first_last": "image_to_video"}  # [?]


def _image_part(img: InputAsset) -> dict[str, Any]:
    if img.gcs_uri:
        return {"type": "image", "uri": img.gcs_uri, "mime_type": img.mime}  # [?]
    assert img.data is not None
    return {"type": "image", "data": b64(img.data), "mime_type": img.mime}


def parse_interaction(it: dict[str, Any]) -> PollResult:
    """Pure: interaction resource -> PollResult. [?] shape: outputs[] with video data/uri."""
    status = it.get("status")
    if status in ("in_progress", "queued", "running", "requires_action"):
        return PollResult(state="running")
    if status in ("failed", "cancelled", "incomplete"):
        err = it.get("error") if isinstance(it.get("error"), dict) else {}
        msg = str(err.get("message") or f"interaction {status}")
        # structured fields only (invariant 17): exact enum values in error.code/reason/status or finish/block reason
        fields = [err.get(k) for k in ("code", "reason", "status")] + [it.get(k) for k in ("finish_reason", "block_reason")]
        kind = "blocked" if any(isinstance(f, str) and f.upper() in BLOCK_REASONS for f in fields) else "invalid"
        return PollResult(state="failed", error=AdapterError(kind, msg[:500]))
    outs: list[OutputRef] = []
    for o in it.get("outputs", []):
        if o.get("type") != "video":
            continue
        mime = o.get("mime_type") or "video/mp4"
        if o.get("data"):
            outs.append(inline_output(mime, o["data"]))
        elif o.get("gcs_uri") or o.get("uri"):
            outs.append(OutputRef(mime=mime, uri=o.get("gcs_uri") or o.get("uri")))
    if not outs:
        return PollResult(state="failed", error=AdapterError("invalid", "interaction completed without video output"))
    return PollResult(state="done", outputs=outs)


class VertexOmniAdapter:
    poll_interval_s = None  # settings.pollIntervalSeconds

    def __init__(self, manifest: ModelManifest, client: VertexClient | None = None):
        self.m = manifest
        self.client = client

    def build_payload(self, job: Job) -> dict[str, Any]:
        inp: list[dict[str, Any]] = [{"type": "text", "text": job.prompt}]
        for slot in ("first_frame", "last_frame"):
            for img in input_images(job, slot):
                inp.append(_image_part(img))
        payload: dict[str, Any] = {
            "model": self.m.api_model,
            "input": inp,
            "response_format": {"type": "video"},
            "background": True,  # async + poll; sync (`false`) is also valid upstream
        }
        task = TASK_BY_MODE.get(job.mode)
        if task:
            payload["task"] = task  # [?] placement; Google recommends prompting over the hint
        apply_params(self.m, job, payload)  # model_variant -> model, aspect_ratio/resolution/duration -> response_format.*
        bucket = self.client.cfg.gcs_bucket if self.client else None
        if bucket:  # Vertex: delivery uri + gcs_uri (avoids ~4 MB inline cap) [?]
            payload["response_format"]["delivery"] = "uri"
            payload["response_format"]["gcs_uri"] = f"gs://{bucket}/aigen/{job.id}.mp4"
        return payload

    def _base(self) -> str:
        assert self.client is not None, "Vertex is not configured"
        loc = self.m.api_location or "global"
        return (f"https://{host(loc)}/v1beta1/projects/{self.client.cfg.project_id}/locations/{loc}"
                f"/interactions")  # [?] endpoint path on Vertex

    async def submit(self, job: Job) -> SubmitHandle:
        assert self.client is not None, "Vertex is not configured"
        resp = await self.client.request("POST", self._base(), self.build_payload(job))
        if not resp.get("id"):
            raise AdapterError("invalid", "interaction created without id")
        return SubmitHandle(id=resp["id"], data={"first": resp})

    async def poll(self, handle: SubmitHandle) -> PollResult:
        assert self.client is not None
        first = handle.data.pop("first", None)
        if first is not None and first.get("status") not in (None, "in_progress", "queued", "running"):
            return parse_interaction(first)
        it = await self.client.request("GET", f"{self._base()}/{handle.id}")
        return parse_interaction(it)

    async def download(self, outputs: list[OutputRef], dest: Path) -> list[Downloaded]:
        assert self.client is not None
        client = self.client

        async def fetch(uri: str, path: Path) -> tuple[int, str]:
            return await download_gcs(client, uri, path)

        return await write_outputs(outputs, dest, fetch)
