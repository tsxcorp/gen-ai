"""Provider adapter interface. build_payload is a pure function (also feeds the raw-request tab)."""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, TypeVar

from app.core.storage import EXT
from app.errors import AdapterError
from app.schemas import InputAsset, Job, ModelManifest

INLINE_DECODE_LIMIT = 256 * 1024  # base64 chars; larger payloads are decoded straight to disk, never held as bytes
ThreadResult = TypeVar("ThreadResult")


@dataclass
class SubmitHandle:
    id: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutputRef:
    mime: str
    data: bytes | None = None
    uri: str | None = None
    b64: str | None = None  # large inline base64: decoded in chunks while writing to disk


def inline_output(mime: str, b64_text: str) -> OutputRef:
    """Small payloads are decoded now; big ones stay base64 and are decoded incrementally by write_outputs."""
    if len(b64_text) <= INLINE_DECODE_LIMIT:
        return OutputRef(mime=mime, data=base64.b64decode(b64_text))
    return OutputRef(mime=mime, b64=b64_text)


@dataclass
class PollResult:
    state: Literal["running", "done", "failed"]
    outputs: list[OutputRef] = field(default_factory=list)
    error: AdapterError | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class Downloaded:
    path: Path
    mime: str
    sha256: str | None = None  # computed while writing (invariant 19)
    size_bytes: int | None = None


class ProviderAdapter(Protocol):
    poll_interval_s: float | None  # None -> settings.pollIntervalSeconds

    def build_payload(self, job: Job) -> dict[str, Any]: ...
    async def submit(self, job: Job) -> SubmitHandle: ...
    async def poll(self, handle: SubmitHandle) -> PollResult: ...
    async def download(self, outputs: list[OutputRef], dest: Path) -> list[Downloaded]: ...


FetchToFile = Callable[[str, Path], Awaitable[tuple[int, str]]]  # (uri, dest) -> (size, sha256)


def _write_bytes(path: Path, data: bytes) -> tuple[int, str]:
    path.write_bytes(data)
    return len(data), hashlib.sha256(data).hexdigest()


def _write_b64(path: Path, text: str) -> tuple[int, str]:
    h = hashlib.sha256()
    size = 0
    step = 4 * 64 * 1024  # multiple of 4 so every chunk decodes on its own
    try:
        with path.open("wb") as f:
            for i in range(0, len(text), step):
                chunk = base64.b64decode(text[i:i + step])
                f.write(chunk)
                h.update(chunk)
                size += len(chunk)
    except (binascii.Error, ValueError):
        path.unlink(missing_ok=True)
        raise AdapterError("invalid", "provider returned malformed base64") from None
    return size, h.hexdigest()


async def write_outputs(outputs: list[OutputRef], dest: Path, fetch: FetchToFile | None = None) -> list[Downloaded]:
    """Write every output straight to disk (no re-encode); sha256 is computed while writing and the heavy
    work runs off the event loop. URIs are streamed by `fetch` (adapter-provided)."""
    dest.mkdir(parents=True, exist_ok=True)
    files: list[Downloaded] = []
    try:
        await _write_all(outputs, dest, fetch, files)
    except BaseException:
        for f in files:  # all-or-nothing: a retry of the download must not leave orphans behind
            f.path.unlink(missing_ok=True)
        raise
    return files


async def _write_all(outputs: list[OutputRef], dest: Path, fetch: FetchToFile | None, files: list[Downloaded]) -> None:
    for output in outputs:
        path = dest / f"{uuid.uuid4().hex}.{EXT.get(output.mime, 'bin')}"
        try:
            if output.data is not None:
                size, sha = await run_output_thread(_write_bytes, path, output.data)
            elif output.b64 is not None:
                size, sha = await run_output_thread(_write_b64, path, output.b64)
            elif output.uri and fetch is not None:
                size, sha = await fetch(output.uri, path)
            else:
                raise AdapterError("invalid", "output has neither bytes nor a downloadable uri")
            files.append(Downloaded(path=path, mime=output.mime, sha256=sha, size_bytes=size))
        except BaseException:
            path.unlink(missing_ok=True)
            raise

async def run_output_thread(writer: Callable[..., ThreadResult], *args: Any) -> ThreadResult:
    task = asyncio.create_task(asyncio.to_thread(writer, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        drain = asyncio.gather(task, return_exceptions=True)
        while not drain.done():
            try:
                await asyncio.shield(drain)
            except asyncio.CancelledError:
                continue
        drain.result()
        raise


# ---------- shared pure helpers ----------
def set_path(d: dict[str, Any], path: str, value: Any) -> None:
    """Set d['a']['b'][0]['c'] from 'a.b.0.c'; creates dicts, requires lists to exist."""
    parts = path.split(".")
    cur: Any = d
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        key: Any = int(part) if isinstance(cur, list) else part
        if last:
            cur[key] = value
            return
        nxt = cur[key] if (isinstance(cur, list) or key in cur) else None
        if nxt is None:
            nxt = {}
            cur[key] = nxt
        cur = nxt


def apply_params(m: ModelManifest, job: Job, payload: dict[str, Any], skip: set[str] = frozenset()) -> None:
    """Write every supported effective param to its manifest providerPath. Unsupported never emitted."""
    for key, val in job.effective_params.items():
        p = m.param(key)
        if p is None or not p.supported or key in skip or key == "prompt" or val is None:
            continue
        if p.type in ("image", "imageList") or not p.provider_path:
            continue
        out = p.provider_format.format(val) if p.provider_format else val
        set_path(payload, p.provider_path, out)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def input_images(job: Job, slot: str) -> list[InputAsset]:
    return job.inputs.get(slot, [])


_B64_RE = re.compile(r"[A-Za-z0-9+/=_\-\r\n]+")


def looks_like_base64(s: str) -> bool:
    return len(s) > 256 and _B64_RE.fullmatch(s) is not None


def redact_payload(obj: Any) -> Any:
    """For the raw-request tab: replace long base64 blobs with a placeholder; structure unchanged.
    Only strings made entirely of base64 characters qualify (a long prompt, e.g. CJK, is shown verbatim)."""
    if isinstance(obj, dict):
        return {k: redact_payload(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_payload(v) for v in obj]
    if isinstance(obj, str) and looks_like_base64(obj):
        return f"<base64 {len(obj)} chars>"
    return obj
