"""Gemini image ("Nano Banana") via Vertex generateContent.

NOT TESTED LIVE. Fields marked [?] are unverified against the live API (see manifests, verified: false). Built from plans/reports/research-image-params.md 2a. Uses the classic
`generationConfig.imageConfig{aspectRatio,imageSize}` camelCase shape (the Interactions snake_case
shape also exists upstream; this adapter targets generateContent on Vertex).
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

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
from app.adapters.vertex_common import VertexClient, host
from app.errors import AdapterError
from app.schemas import Job, ModelManifest

SAFETY_CATEGORIES = [
    "HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH",
    "HARM_CATEGORY_SEXUALLY_EXPLICIT", "HARM_CATEGORY_DANGEROUS_CONTENT",
]
BLOCK_FINISH = {"SAFETY", "IMAGE_SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "IMAGE_PROHIBITED_CONTENT",
                "IMAGE_OTHER", "RECITATION"}


def parse_generate_content(resp: dict[str, Any]) -> list[OutputRef]:
    """Pure: Vertex generateContent response -> image outputs, or a normalised AdapterError."""
    fb = resp.get("promptFeedback") or {}
    if fb.get("blockReason"):
        raise AdapterError("blocked", f"prompt blocked: {fb['blockReason']} {fb.get('blockReasonMessage', '')}".strip())
    outs: list[OutputRef] = []
    texts: list[str] = []
    finish = None
    for cand in resp.get("candidates", []):
        finish = finish or cand.get("finishReason")
        for part in (cand.get("content") or {}).get("parts", []):
            if part.get("thought"):
                continue  # invariant 18: thought (draft) images/text are never outputs
            blob = part.get("inlineData") or part.get("inline_data")
            if blob and blob.get("data"):
                outs.append(OutputRef(mime=blob.get("mimeType") or blob.get("mime_type") or "image/png",
                                      data=base64.b64decode(blob["data"])))
            elif part.get("text"):
                texts.append(part["text"])
    if outs:
        return outs
    if finish in BLOCK_FINISH:
        raise AdapterError("blocked", f"generation blocked: finishReason={finish}")
    raise AdapterError("invalid", "model returned no image" + (f": {' '.join(texts)[:300]}" if texts else ""))


class VertexImageAdapter:
    poll_interval_s = 0.0

    def __init__(self, manifest: ModelManifest, client: VertexClient | None = None):
        self.m = manifest
        self.client = client

    def build_payload(self, job: Job) -> dict[str, Any]:
        parts: list[dict[str, Any]] = [{"text": job.prompt}]
        for img in input_images(job, "reference_images"):
            if img.data is not None:
                parts.append({"inlineData": {"mimeType": img.mime, "data": b64(img.data)}})
            elif img.gcs_uri:
                parts.append({"fileData": {"mimeType": img.mime, "fileUri": img.gcs_uri}})
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"]},  # [?] IMAGE-only not confirmed for every model
        }
        apply_params(self.m, job, payload, skip={"google_search", "safety_threshold"})
        eff = job.effective_params
        if eff.get("google_search"):
            payload["tools"] = [{"googleSearch": {}}]
        if eff.get("safety_threshold"):
            payload["safetySettings"] = [{"category": c, "threshold": eff["safety_threshold"]}
                                         for c in SAFETY_CATEGORIES]
        return payload

    def _url(self) -> str:
        assert self.client is not None
        loc = self.m.api_location or self.client.cfg.location
        return (f"https://{host(loc)}/v1/projects/{self.client.cfg.project_id}/locations/{loc}"
                f"/publishers/google/models/{self.m.api_model}:generateContent")

    async def submit(self, job: Job) -> SubmitHandle:
        assert self.client is not None, "Vertex is not configured"
        resp = await self.client.request("POST", self._url(), self.build_payload(job))
        outs = parse_generate_content(resp)
        return SubmitHandle(id=job.id, data={"outputs": outs})

    async def poll(self, handle: SubmitHandle) -> PollResult:
        return PollResult(state="done", outputs=handle.data["outputs"])

    async def download(self, outputs: list[OutputRef], dest: Path) -> list[Downloaded]:
        return await write_outputs(outputs, dest)
