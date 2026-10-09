from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_ctx
from app.context import AppContext
from app.core.manifest import manifest_summary, manifest_warnings
from app.errors import ApiError

router = APIRouter(tags=["manifests"])


@router.get("/manifests")
def list_manifests(ctx: AppContext = Depends(get_ctx)):
    stale = int(ctx.config.settings()["staleDays"])
    return [{**manifest_summary(m, stale), "configured": ctx.provider_configured(m.provider)}
            for m in ctx.manifests.values()]


@router.get("/manifests/{model_id}")
def get_manifest(model_id: str, ctx: AppContext = Depends(get_ctx)):
    m = ctx.manifests.get(model_id)
    if m is None:
        raise ApiError("not_found", f"manifest {model_id} not found")
    out = m.model_dump(by_alias=True, mode="json")
    out["configured"] = ctx.provider_configured(m.provider)
    out["warnings"] = manifest_warnings(m, int(ctx.config.settings()["staleDays"]))
    return out
