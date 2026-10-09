"""presets.json / prompts.json CRUD and settings.json. File shape: {"items": [...]}."""
from __future__ import annotations

import math
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, ValidationError

from app.api.deps import get_ctx
from app.context import AppContext
from app.core.config_files import DEFAULT_SETTINGS, SETTING_LIMITS
from app.errors import ApiError

router = APIRouter(tags=["library"])


class Preset(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str | None = None
    name: str
    modelId: str  # noqa: N815
    mode: str | None = None
    params: dict[str, Any] = {}
    prompt: str | None = None


class PromptTemplate(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str | None = None
    name: str
    text: str
    tags: list[str] = []


KINDS = {"presets": (Preset, "presets.json"), "prompts": (PromptTemplate, "prompts.json")}


def _validate_items(kind: str, raw: Any) -> list[dict[str, Any]]:
    model, _ = KINDS[kind]
    items = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ApiError("invalid", "body must be a list or {items:[...]}")
    out = []
    for i, it in enumerate(items):
        try:
            obj = model.model_validate(it)
        except ValidationError as e:
            raise ApiError("invalid", f"item #{i} invalid", [{"loc": list(x["loc"]), "msg": x["msg"]} for x in e.errors()]) from None
        d = obj.model_dump(exclude_none=True)
        if not str(d["name"]).strip():
            raise ApiError("invalid", f"item #{i}: name is empty")
        d["id"] = d.get("id") or uuid.uuid4().hex[:12]
        out.append(d)
    if len({d["id"] for d in out}) != len(out):
        raise ApiError("invalid", "duplicate ids")
    return out


def _load(ctx: AppContext, kind: str) -> list[dict[str, Any]]:
    data = ctx.config.read(KINDS[kind][1], {"items": []})
    return data["items"] if isinstance(data, dict) else data


def _save(ctx: AppContext, kind: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    ctx.config.write(KINDS[kind][1], {"items": items})
    return {"items": items}


def _register(kind: str) -> None:
    @router.get(f"/{kind}", name=f"get_{kind}")
    def get_all(ctx: AppContext = Depends(get_ctx)):
        return {"items": _load(ctx, kind)}

    @router.put(f"/{kind}", name=f"put_{kind}")
    async def put_all(request: Request, ctx: AppContext = Depends(get_ctx)):
        try:
            raw = await request.json()
        except ValueError:
            raise ApiError("invalid", "body is not valid JSON") from None
        return _save(ctx, kind, _validate_items(kind, raw))

    @router.put(f"/{kind}/{{item_id}}", name=f"upsert_{kind}")
    async def upsert(item_id: str, request: Request, ctx: AppContext = Depends(get_ctx)):
        try:
            raw = await request.json()
        except ValueError:
            raise ApiError("invalid", "body is not valid JSON") from None
        if not isinstance(raw, dict):
            raise ApiError("invalid", "body must be an object")
        (item,) = _validate_items(kind, [{**raw, "id": item_id}])
        items = [i for i in _load(ctx, kind) if i["id"] != item_id] + [item]
        _save(ctx, kind, items)
        return item

    @router.delete(f"/{kind}/{{item_id}}", name=f"delete_{kind}")
    def delete(item_id: str, ctx: AppContext = Depends(get_ctx)):
        items = _load(ctx, kind)
        rest = [i for i in items if i["id"] != item_id]
        if len(rest) == len(items):
            raise ApiError("not_found", f"{kind[:-1]} {item_id} not found")
        _save(ctx, kind, rest)
        return {"ok": True}


for _k in KINDS:
    _register(_k)


@router.get("/settings")
def get_settings(ctx: AppContext = Depends(get_ctx)):
    return ctx.config.settings()


@router.put("/settings")
async def put_settings(request: Request, ctx: AppContext = Depends(get_ctx)):
    try:
        raw = await request.json()
    except ValueError:
        raise ApiError("invalid", "body is not valid JSON") from None
    if not isinstance(raw, dict):
        raise ApiError("invalid", "body must be an object")
    cur = ctx.config.settings()
    for k, v in raw.items():
        if k not in DEFAULT_SETTINGS:
            raise ApiError("invalid", f"unknown setting {k}")
        if k in SETTING_LIMITS:
            kind, lo, hi = SETTING_LIMITS[k]
            ok = isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi
            if ok and kind == "int" and v != int(v):
                ok = False
            if not ok:
                raise ApiError("invalid", f"setting {k} must be a {kind} within [{lo:g}, {hi:g}]")
            cur[k] = int(v) if kind == "int" else v
        else:
            if not (isinstance(v, str) and v.strip()):
                raise ApiError("invalid", f"setting {k} has an invalid value")
            cur[k] = v
    ctx.config.write("settings.json", cur)
    return cur
