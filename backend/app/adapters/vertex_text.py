"""Prompt enhancer: Gemini text via Vertex generateContent. NOT TESTED LIVE."""
from __future__ import annotations

from typing import Any

from app.adapters.vertex_common import VertexClient, host
from app.errors import AdapterError


def build_enhance_payload(system_prompt: str, prompt: str) -> dict[str, Any]:
    return {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7},
    }


def parse_text(resp: dict[str, Any]) -> str:
    fb = resp.get("promptFeedback") or {}
    if fb.get("blockReason"):
        raise AdapterError("blocked", f"prompt blocked: {fb['blockReason']}")
    for cand in resp.get("candidates", []):
        text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if not p.get("thought"))
        if text.strip():
            return text.strip()
        if cand.get("finishReason") in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"):
            raise AdapterError("blocked", f"blocked: finishReason={cand['finishReason']}")
    raise AdapterError("invalid", "enhancer returned no text")


class VertexTextAdapter:
    def __init__(self, client: VertexClient, model: str, location: str = "global"):
        self.client = client
        self.model = model
        self.location = location

    async def enhance(self, system_prompt: str, prompt: str) -> str:
        loc = self.location
        url = (f"https://{host(loc)}/v1/projects/{self.client.cfg.project_id}/locations/{loc}"
               f"/publishers/google/models/{self.model}:generateContent")
        resp = await self.client.request("POST", url, build_enhance_payload(system_prompt, prompt))
        return parse_text(resp)
