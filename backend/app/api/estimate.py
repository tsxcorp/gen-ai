from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.adapters.base import redact_payload
from app.adapters.factory import payload_builder
from app.api.deps import get_ctx
from app.api.planning import PlanBody, plan
from app.context import AppContext
from app.core import constraints
from app.schemas import CamelModel

router = APIRouter(tags=["estimate"])


class ResolveBody(CamelModel):
    model_id: str
    mode: str | None = None
    params: dict[str, Any] = {}


@router.post("/resolve")
def resolve(body: ResolveBody, ctx: AppContext = Depends(get_ctx)):
    m = ctx.manifest(body.model_id)
    r = constraints.resolve(m, body.mode, body.params)
    return {"mode": r.mode, "effectiveParams": r.effective, "locked": r.locked, "errors": r.errors}


@router.post("/estimate")
def estimate(body: PlanBody, ctx: AppContext = Depends(get_ctx)):
    _, _, est = plan(ctx, body.request, body.sweep)
    return est


@router.post("/payload")
def payload(body: PlanBody, ctx: AppContext = Depends(get_ctx)):
    """Raw-request tab: the exact payload build_payload produces for each job (inline base64 redacted)."""
    m, jobs, _ = plan(ctx, body.request, body.sweep)
    adapter = payload_builder(m, ctx.config.providers(), ctx.demo)
    out = []
    for j in jobs:
        j.inputs = ctx.jobs._load_inputs(j)
        try:
            out.append({"jobId": j.id, "variantCount": j.variant_count, "axis": j.axis,
                        "payload": redact_payload(adapter.build_payload(j))})
        finally:
            j.inputs = {}
    return {"payloads": out}
