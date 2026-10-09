"""Shared request -> jobs -> estimate pipeline used by /estimate, /batches and /payload."""
from __future__ import annotations

from typing import Any

from app.context import AppContext
from app.core.cost import estimate_jobs
from app.core.expand import expand_with_warnings
from app.core.manifest import manifest_warnings
from app.errors import ApiError
from app.schemas import CamelModel, GenerationRequest, Job, ModelManifest, Sweep


class PlanBody(CamelModel):
    request: GenerationRequest
    sweep: Sweep | None = None
    confirm_over_threshold: bool = False


def _check_assets(ctx: AppContext, jobs: list[Job]) -> None:
    for j in jobs:
        for slot, val in j.assets_in.items():
            for aid in val if isinstance(val, list) else [val]:
                try:
                    ctx.storage.get(str(aid))
                except ApiError:
                    raise ApiError("invalid", f"asset {aid} (slot {slot}) does not exist or was cleaned up") from None


def plan(ctx: AppContext, req: GenerationRequest, sweep: Sweep | None) -> tuple[ModelManifest, list[Job], dict[str, Any]]:
    m = ctx.manifest(req.model_id)
    s = ctx.config.settings()
    jobs, expand_warnings = expand_with_warnings(m, req, sweep, int(s.get("maxJobsPerBatch", 24)))
    _check_assets(ctx, jobs)
    est = estimate_jobs(m, jobs, ctx.prices(), int(s.get("staleDays", 30)))
    warnings = manifest_warnings(m, int(s.get("staleDays", 30))) + expand_warnings + est["warnings"]
    threshold = float(s["confirmThresholdUsd"])
    return m, jobs, {
        # jobCount = requested outputs (what the batch cap counts); requestCount = provider requests after
        # native grouping (= number of Job objects in the batch)
        "jobCount": sum(j.variant_count for j in jobs),
        "outputCount": sum(j.variant_count for j in jobs),
        "requestCount": len(jobs),
        "minUsd": est["minUsd"],
        "maxUsd": est["maxUsd"],
        "perJob": est["perJob"],
        "warnings": warnings,
        "thresholdUsd": threshold,
        # invariant 15: an unknown price is not "$0" -> always needs an explicit confirmation
        "unknownPrice": est["unknownPrice"],
        "confirmRequired": est["unknownPrice"] or est["maxUsd"] > threshold,
        "maxJobsPerBatch": int(s.get("maxJobsPerBatch", 24)),
    }
