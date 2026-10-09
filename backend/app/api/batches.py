from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_ctx
from app.api.planning import PlanBody, plan
from app.context import AppContext
from app.errors import ApiError
from app.schemas import Batch

router = APIRouter(tags=["batches"])


def _batch_out(b: Batch) -> dict:
    return b.model_dump(by_alias=True, mode="json")


@router.post("/batches")
async def create_batch(body: PlanBody, ctx: AppContext = Depends(get_ctx)):
    ctx.ensure_configured(ctx.manifest(body.request.model_id))  # before any planning/spending
    _, jobs, est = plan(ctx, body.request, body.sweep)
    if est["confirmRequired"] and not body.confirm_over_threshold:
        why = ("price is unknown for this model/params (estimate $0 is not real)" if est["unknownPrice"]
               else f"estimated max ${est['maxUsd']:.2f} exceeds ${est['thresholdUsd']:.2f}")
        raise ApiError(
            "confirm_required",
            f"{why}; resend with confirmOverThreshold=true",
            {"minUsd": est["minUsd"], "maxUsd": est["maxUsd"], "thresholdUsd": est["thresholdUsd"],
             "jobCount": est["jobCount"], "unknownPrice": est["unknownPrice"]},
        )
    batch_id = jobs[0].batch_id
    ctx.jobs.create_batch(jobs, est, body.confirm_over_threshold, batch_id)
    return {"batchId": batch_id, "jobs": [j.model_dump(by_alias=True, mode="json") for j in jobs], "estimate": est,
            "confirmed": body.confirm_over_threshold}


@router.get("/batches/{batch_id}")
def get_batch(batch_id: str, ctx: AppContext = Depends(get_ctx)):
    return _batch_out(ctx.jobs.get_batch(batch_id))


@router.post("/batches/{batch_id}/cancel")
async def cancel_batch(batch_id: str, ctx: AppContext = Depends(get_ctx)):
    b = ctx.jobs.cancel_batch(batch_id)
    return {"ok": True, "batchId": b.id, "status": b.status, "counts": b.counts}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, ctx: AppContext = Depends(get_ctx)):
    return ctx.jobs.get_job(job_id).model_dump(by_alias=True, mode="json")


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, request: Request, ctx: AppContext = Depends(get_ctx)):
    """Optional JSON body {confirmOverThreshold: bool}; a retry spends money again, so it passes the same gate."""
    confirm = False
    raw = await request.body()
    if raw.strip():
        try:
            body = json.loads(raw)
        except ValueError:
            raise ApiError("invalid", "body is not valid JSON") from None
        confirm = isinstance(body, dict) and body.get("confirmOverThreshold") is True
    ctx.ensure_configured(ctx.manifests[ctx.jobs.get_job(job_id).model_id])
    return ctx.jobs.retry_job(job_id, confirm=confirm).model_dump(by_alias=True, mode="json")
