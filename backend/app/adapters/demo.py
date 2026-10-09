"""DemoAdapter (AIGEN_DEMO=1): no network, no credentials. Deterministic keyword behaviour.

Prompt keywords: [blocked] -> blocked, [quota] -> quota on the first attempt of a job then ok,
[fail] -> invalid. Images are real PNGs, videos are a real tiny MP4 (H.264, 64x64, 1 s).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import struct
import zlib
from pathlib import Path
from typing import Any

from app.adapters.base import Downloaded, OutputRef, PollResult, SubmitHandle, write_outputs
from app.adapters.byteplus_seedance import SeedanceAdapter
from app.adapters.openai_image import OpenAIImageAdapter
from app.adapters.vertex_image import VertexImageAdapter
from app.adapters.vertex_omni import VertexOmniAdapter
from app.adapters.vertex_veo import VertexVeoAdapter
from app.errors import AdapterError
from app.schemas import Job, ModelManifest

_REAL = {
    "vertex_image": VertexImageAdapter, "vertex_omni": VertexOmniAdapter, "vertex_veo": VertexVeoAdapter,
    "openai_image": OpenAIImageAdapter, "byteplus_seedance": SeedanceAdapter,
}

_MP4 = base64.b64decode(
    "AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAANDbW9vdgAAAGxtdmhkAAAAAAAAAAAAAAAAAAAD6AAAA+gAAQAAAQAA"
    "AAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAA"
    "Am50cmFrAAAAXHRraGQAAAADAAAAAAAAAAAAAAABAAAAAAAAA+gAAAAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAA"
    "AAAAAAAAAAAAAABAAAAAAEAAAABAAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAAAPoAAAAAAABAAAAAAHmbWRpYQAAACBtZGhk"
    "AAAAAAAAAAAAAAAAAABAAAAAQABVxAAAAAAALWhkbHIAAAAAAAAAAHZpZGUAAAAAAAAAAAAAAABWaWRlb0hhbmRsZXIAAAABkW1p"
    "bmYAAAAUdm1oZAAAAAEAAAAAAAAAAAAAACRkaW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAAAQAAAVFzdGJsAAAAuXN0c2QA"
    "AAAAAAAAAQAAAKlhdmMxAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAEAAQABIAAAASAAAAAAAAAABFUxhdmM2MS4xOS4xMDEgbGli"
    "eDI2NAAAAAAAAAAAAAAAGP//AAAAL2F2Y0MBQsAK/+EAF2dCwArZBCbARAAAAwAEAAADAEA8SJkgAQAFaMuDyyAAAAAQcGFzcAAA"
    "AAEAAAABAAAAFGJ0cnQAAAAAAAAW+AAAAAAAAAAYc3R0cwAAAAAAAAABAAAACAAACAAAAAAUc3RzcwAAAAAAAAABAAAAAQAAABxz"
    "dHNjAAAAAAAAAAEAAAABAAAACAAAAAEAAAA0c3RzegAAAAAAAAAAAAAACAAAApgAAAAKAAAACwAAAAoAAAAKAAAACgAAAAoAAAAK"
    "AAAAFHN0Y28AAAAAAAAAAQAAA3MAAABhdWR0YQAAAFltZXRhAAAAAAAAACFoZGxyAAAAAAAAAABtZGlyYXBwbAAAAAAAAAAAAAAA"
    "ACxpbHN0AAAAJKl0b28AAAAcZGF0YQAAAAEAAAAATGF2ZjYxLjcuMTAwAAAACGZyZWUAAALnbWRhdAAAAnAGBf//bNxF6b3m2Ui3"
    "lizYINkj7u94MjY0IC0gY29yZSAxNjQgcjMxMDggMzFlMTlmOSAtIEguMjY0L01QRUctNCBBVkMgY29kZWMgLSBDb3B5bGVmdCAy"
    "MDAzLTIwMjMgLSBodHRwOi8vd3d3LnZpZGVvbGFuLm9yZy94MjY0Lmh0bWwgLSBvcHRpb25zOiBjYWJhYz0wIHJlZj0zIGRlYmxv"
    "Y2s9MTowOjAgYW5hbHlzZT0weDE6MHgxMTEgbWU9aGV4IHN1Ym1lPTcgcHN5PTEgcHN5X3JkPTEuMDA6MC4wMCBtaXhlZF9yZWY9"
    "MSBtZV9yYW5nZT0xNiBjaHJvbWFfbWU9MSB0cmVsbGlzPTEgOHg4ZGN0PTAgY3FtPTAgZGVhZHpvbmU9MjEsMTEgZmFzdF9wc2tp"
    "cD0xIGNocm9tYV9xcF9vZmZzZXQ9LTIgdGhyZWFkcz0yIGxvb2thaGVhZF90aHJlYWRzPTEgc2xpY2VkX3RocmVhZHM9MCBucj0w"
    "IGRlY2ltYXRlPTEgaW50ZXJsYWNlZD0wIGJsdXJheV9jb21wYXQ9MCBjb25zdHJhaW5lZF9pbnRyYT0wIGJmcmFtZXM9MCB3ZWln"
    "aHRwPTAga2V5aW50PTI1MCBrZXlpbnRfbWluPTggc2NlbmVjdXQ9NDAgaW50cmFfcmVmcmVzaD0wIHJjX2xvb2thaGVhZD00MCBy"
    "Yz1jcmYgbWJ0cmVlPTEgY3JmPTIzLjAgcWNvbXA9MC42MCBxcG1pbj0wIHFwbWF4PTY5IHFwc3RlcD00IGlwX3JhdGlvPTEuNDAg"
    "YXE9MToxLjAwAIAAAAAgZYiEBDxGKAAJNccAASvI4AAjBycnJ1111111111114AAAAAGQZo4CHhGAAAAB0GaVAIeEYAAAAAGQZpg"
    "EPCMAAAABkGagBDwjAAAAAZBmqA/wjAAAAAGQZrAP8IwAAAABkGa4DvCMA=="
)


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def make_png(w: int, h: int, seed: str) -> bytes:
    d = hashlib.sha256(seed.encode()).digest()
    c1, c2 = d[0:3], d[3:6]
    cx, cy, r2 = (d[6] / 255) * w, (d[7] / 255) * h, (min(w, h) * (0.2 + d[8] / 700)) ** 2
    rows = bytearray()
    for y in range(h):
        rows.append(0)
        for x in range(w):
            t = (x / max(1, w - 1) + y / max(1, h - 1)) / 2
            px = [int(c1[i] * (1 - t) + c2[i] * t) for i in range(3)]
            if (x - cx) ** 2 + (y - cy) ** 2 < r2:
                px = [255 - v for v in px]
            rows += bytes(px)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(rows), 6)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def make_mp4(seed: str) -> bytes:
    """Valid MP4 + a trailing 'free' box carrying the seed so variants differ in bytes."""
    payload = hashlib.sha256(seed.encode()).digest()
    return _MP4 + struct.pack(">I", 8 + len(payload)) + b"free" + payload


def _dims(ratio: str, long_side: int = 320) -> tuple[int, int]:
    try:
        a, b = (int(x) for x in ratio.replace("x", ":").split(":"))  # "16:9" or an OpenAI size "1536x1024"
    except ValueError:
        a, b = 1, 1
    if a >= b:
        return long_side, max(16, round(long_side * b / a))
    return max(16, round(long_side * a / b)), long_side


class DemoAdapter:
    poll_interval_s = 0.05

    def __init__(self, manifest: ModelManifest):
        self.m = manifest
        self._real = _REAL[manifest.adapter](manifest, None)
        self._quota_seen: set[str] = set()
        self.delay = float(os.environ.get("AIGEN_DEMO_DELAY_MS", "300")) / 1000.0

    def build_payload(self, job: Job) -> dict[str, Any]:
        return self._real.build_payload(job)

    async def submit(self, job: Job) -> SubmitHandle:
        await asyncio.sleep(self.delay)
        p = job.prompt.lower()
        if "[blocked]" in p:
            raise AdapterError("blocked", "demo: blocked by safety filters")
        if "[fail]" in p:
            raise AdapterError("invalid", "demo: invalid parameters")
        if "[quota]" in p and job.id not in self._quota_seen:
            self._quota_seen.add(job.id)
            raise AdapterError("quota", "demo: 429 quota exceeded")
        outs: list[OutputRef] = []
        for i in range(job.variant_count):
            seed = f"{job.prompt}|{job.id}|{i}|{sorted(job.effective_params.items())}"
            if self.m.kind == "image":
                w, h = _dims(str(job.effective_params.get("aspect_ratio") or job.effective_params.get("size") or "1:1"))
                outs.append(OutputRef(mime="image/png", data=make_png(w, h, seed)))
            else:
                outs.append(OutputRef(mime="video/mp4", data=make_mp4(seed)))
        return SubmitHandle(id=job.id, data={"outputs": outs})

    async def poll(self, handle: SubmitHandle) -> PollResult:
        return PollResult(state="done", outputs=handle.data["outputs"])

    async def download(self, outputs: list[OutputRef], dest: Path) -> list[Downloaded]:
        return await write_outputs(outputs, dest)


def demo_enhance(manifest: ModelManifest | None, prompt: str) -> str:
    """Deterministic rewrite used by /api/enhance in demo mode."""
    p = prompt.strip().rstrip(".")
    if manifest is not None and manifest.kind == "video":
        return f"{p}. Single continuous shot, smooth slow camera movement, cinematic lighting, natural ambient sound."
    return f"{p}. Highly detailed, balanced composition, soft cinematic lighting, sharp focus."
