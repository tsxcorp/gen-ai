"""Expand a GenerationRequest + Sweep into Jobs: prompts x axis1 x axis2 x variants.

Veo-style native grouping (architecture flow 3): variants of the same combo become one job with
variantCount=k (<= limits.maxVariantsNative) because they differ only by randomness.
"""
from __future__ import annotations

import itertools
import json
import math
import random
import uuid
from typing import Any

from app.core import constraints
from app.errors import ApiError
from app.schemas import GenerationRequest, Job, ModelManifest, Sweep

MAX_AXES = 2


def _dedupe(values: list[Any]) -> list[Any]:
    out: list[Any] = []
    for v in values:
        if not any(v == o and type(v) is type(o) for o in out):
            out.append(v)
    return out


def expand(
    m: ModelManifest,
    req: GenerationRequest,
    sweep: Sweep | None,
    max_jobs: int,
    batch_id: str | None = None,
) -> list[Job]:
    return expand_with_warnings(m, req, sweep, max_jobs, batch_id)[0]


def expand_with_warnings(
    m: ModelManifest,
    req: GenerationRequest,
    sweep: Sweep | None,
    max_jobs: int,
    batch_id: str | None = None,
) -> tuple[list[Job], list[str]]:
    sweep = sweep or Sweep()
    batch_id = batch_id or uuid.uuid4().hex
    warnings: list[str] = []
    if len(sweep.axes) > MAX_AXES:
        raise ApiError("invalid", f"at most {MAX_AXES} sweep axes", {"axes": len(sweep.axes)})
    mode = req.mode or m.modes[0]
    axes: list[tuple[str, list[Any]]] = []
    seen: set[str] = set()
    for ax in sweep.axes:
        if ax.param in seen:
            raise ApiError("invalid", f"duplicate axis {ax.param}")
        seen.add(ax.param)
        if not ax.values:
            raise ApiError("invalid", f"axis {ax.param} has no values")
        p = m.param(ax.param)
        if p is None:
            raise ApiError("invalid", f"axis param {ax.param} is not a param of {m.id}")
        if p.type in ("image", "imageList"):
            raise ApiError("invalid", f"axis param {ax.param} is an asset slot; sweep it with separate batches")
        if ax.param == "prompt":
            if sweep.prompts:
                raise ApiError("invalid", "use either sweep.prompts or a prompt axis, not both")
            if not all(isinstance(v, str) and v.strip() for v in ax.values):
                raise ApiError("invalid", "prompt axis values must be non-empty strings")
        if not p.supported or not constraints.applies(p, mode):
            warnings.append(f"axis {ax.param} ignored: not applicable to mode {mode} of {m.id}")
            continue
        values = _dedupe(list(ax.values))
        if len(values) < len(ax.values):
            warnings.append(f"axis {ax.param}: duplicate values removed")
        axes.append((ax.param, values))

    prompts = [p for p in sweep.prompts if p.strip()] or [req.prompt]
    slot_keys = {p.key for p in m.params if p.type in ("image", "imageList")}
    assets = {**{k: v for k, v in req.params.items() if k in slot_keys and v}, **req.assets}
    if not any(p.strip() for p in prompts) and not any(name == "prompt" for name, _ in axes):
        raise ApiError("invalid", "prompt is empty")

    # cap check BEFORE materialising the cartesian product (invariant 22)
    n_combos = math.prod(len(vals) for _, vals in axes)
    total_outputs = len(prompts) * n_combos * sweep.variants
    if total_outputs > max_jobs:
        raise ApiError(
            "invalid",
            f"batch has {total_outputs} jobs, over the limit of {max_jobs}",
            {"jobCount": total_outputs, "maxJobsPerBatch": max_jobs},
        )
    combos = list(itertools.product(*[vals for _, vals in axes])) if axes else [()]

    seed_param = m.param("seed")
    can_seed = seed_param is not None and seed_param.supported and sweep.seed_mode != "none"
    native = max(1, m.limits.max_variants_native)

    jobs: list[Job] = []
    problems: list[dict[str, Any]] = []
    for base_prompt in prompts:
        first_seen: dict[str, dict[str, Any]] = {}
        for combo in combos:
            axis = {name: v for (name, _), v in zip(axes, combo, strict=True)}
            prompt = axis.get("prompt", base_prompt)
            params = {**req.params, "prompt": prompt, **axis}
            res = constraints.resolve(m, req.mode, params, assets, check_assets=True)
            if not res.ok:
                problems.append({"axis": axis, "prompt": prompt, "errors": res.errors})
                continue
            eff = {**res.effective, "prompt": prompt}
            sig = json.dumps(eff, sort_keys=True, default=str)
            if sig in first_seen:  # a force rule (or a no-op axis) collapsed this combo onto an earlier one
                reasons = "; ".join(x["reason"] for x in res.locked) or "no effect"
                warnings.append(f"combination {axis} gives the same effective params as {first_seen[sig]} "
                                f"({reasons}); skipped to avoid a duplicate paid job")
                continue
            first_seen[sig] = axis
            remaining = sweep.variants
            while remaining > 0:
                k = min(native, remaining)
                remaining -= k
                job_eff = dict(eff)
                if can_seed and "seed" not in req.params and "seed" not in axis:
                    if sweep.seed_mode == "fixed" and sweep.seed is not None:
                        job_eff["seed"] = sweep.seed
                    elif sweep.seed_mode == "random":
                        job_eff["seed"] = random.randint(0, 2**32 - 1)
                jobs.append(Job(
                    id=uuid.uuid4().hex, batch_id=batch_id, model_id=m.id, provider=m.provider, mode=res.mode, prompt=prompt,
                    requested_params=params, effective_params=job_eff, locked=res.locked,
                    assets_in=dict(assets), variant_count=k, axis=axis,
                ))
    if problems:
        raise ApiError("invalid", "some combinations are invalid", {"problems": problems})
    return jobs, warnings
