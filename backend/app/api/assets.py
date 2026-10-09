from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.api.deps import get_ctx
from app.context import AppContext
from app.core.storage import MAX_UPLOAD
from app.errors import ApiError
from app.schemas import CamelModel

router = APIRouter(tags=["assets"])


def sniff_image(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"hevx"):
            return "image/heic"
        if brand in (b"mif1", b"msf1", b"heim", b"heis"):
            return "image/heif"
    return None


def _flag(v: str | bool | None) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "on")


@router.post("/uploads")
async def upload(
    file: UploadFile = File(...),
    hasPerson: str | None = Form(None),  # noqa: N803 - contract field names
    consent: str = Form("false"),
    ctx: AppContext = Depends(get_ctx),
):
    # flag absent => unknown => treated as "contains a person" (safe default): consent then required
    has_person = True if hasPerson is None else _flag(hasPerson)
    has_consent = _flag(consent)
    if has_person and not has_consent:
        raise ApiError("invalid", "image contains a person: tick the consent checkbox (you have the right to use it)",
                       {"hasPerson": True, "consent": False})
    # stream to disk in chunks: the size limit is enforced while reading (the ASGI guard also caps the raw body)
    head = await file.read(64 * 1024)
    mime = sniff_image(head)
    if mime is None:
        raise ApiError("invalid", "unsupported file: expected png, jpeg, webp, heic or heif image")
    aid, path = ctx.storage.new_upload_path(mime)
    h = hashlib.sha256()
    size = 0
    try:
        with path.open("wb") as out:
            chunk = head
            while chunk:
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise ApiError("invalid", "file too large (max 20 MB)")
                h.update(chunk)
                await asyncio.to_thread(out.write, chunk)
                chunk = await file.read(1024 * 1024)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    asset = ctx.storage.register_upload(
        aid, path, mime, h.hexdigest(), size,
        {"hasPerson": has_person, "consent": has_consent, "filename": (file.filename or "")[:200]},
    )
    ctx.storage.set_sidecar(asset.id, {"upload": asset.meta})
    return asset.model_dump(by_alias=True, mode="json")


@router.get("/assets/{asset_id}")
def get_asset(asset_id: str, ctx: AppContext = Depends(get_ctx)):
    a = ctx.storage.get(asset_id)
    return FileResponse(a.path, media_type=a.mime)  # Starlette handles Range


class ZipBody(CamelModel):
    asset_ids: list[str]


@router.post("/zip")
def zip_assets(body: ZipBody, ctx: AppContext = Depends(get_ctx)):
    buf = ctx.storage.build_zip(body.asset_ids)

    def chunks() -> Iterator[bytes]:
        try:
            while chunk := buf.read(1024 * 256):
                yield chunk
        finally:
            buf.close()

    name = time.strftime("ai-gen-studio-%Y%m%d-%H%M%S.zip")
    headers: dict[str, Any] = {"Content-Disposition": f'attachment; filename="{name}"'}
    return StreamingResponse(chunks(), media_type="application/zip", headers=headers)
