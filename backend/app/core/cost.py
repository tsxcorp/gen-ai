"""Cost estimator: range [min,max] USD from manifest.pricing + data/prices.json (never hardcoded)."""
from __future__ import annotations

from datetime import date
from typing import Any

from app.schemas import Job, ModelManifest


def _row_compatible(when: dict[str, Any], eff: dict[str, Any]) -> bool:
    for k, want in when.items():
        if k not in eff:
            continue  # unspecified -> any row may apply (widens the range)
        opts = want if isinstance(want, list) else [want]
        have = eff[k]
        if not any(have == o and isinstance(have, bool) == isinstance(o, bool) for o in opts):
            return False
    return True


def price_warnings(entry: dict[str, Any], stale_days: int, today: date) -> list[str]:
    w: list[str] = []
    lv = entry.get("lastVerified")
    if not lv:
        w.append("price has no lastVerified; may be stale")
    else:
        age = (today - date.fromisoformat(lv)).days
        if age > stale_days:
            w.append(f"price may be stale: last verified {age} days ago (>{stale_days})")
    return w


def estimate_job_ex(
    m: ModelManifest,
    job: Job,
    prices: dict[str, Any],
    stale_days: int = 30,
    today: date | None = None,
) -> tuple[float, float, list[str], bool]:
    """(min, max, warnings, unknown). `unknown` means the price could not be determined: the $0 returned is NOT
    an estimate and callers must require confirmation (invariant 15)."""
    today = today or date.today()
    entry = prices.get("entries", {}).get(m.pricing.price_key or m.id)
    if entry is None:
        entry = {}
        warnings = [f"no prices.json entry for {m.id}: price may be stale (no lastVerified)"]
    else:
        warnings = price_warnings(entry, stale_days, today)
    table = entry["table"] if "table" in entry else [r.model_dump() for r in m.pricing.table]
    rows = [r for r in table if r.get("usd") is not None and _row_compatible(r.get("when", {}), job.effective_params)]
    if entry.get("unknown") and not rows:
        return 0.0, 0.0, [*warnings, f"price unknown for {m.id}; confirmation required"], True
    if not rows:
        return 0.0, 0.0, [*warnings, f"price unknown for {m.id} with these params; estimate counts as $0, "
                                      "confirmation required"], True
    units = float(job.variant_count)
    if m.pricing.unit == "per_second":
        dur = job.effective_params.get("duration")
        if dur is None:
            return 0.0, 0.0, [*warnings, "duration unknown; cannot estimate per-second price; "
                                          "confirmation required"], True
        units *= float(dur)
    var = entry.get("variance", {})
    lo = min(r["usd"] for r in rows) * units * float(var.get("min", 1.0))
    hi = max(r["usd"] for r in rows) * units * float(var.get("max", 1.0))
    return round(lo, 6), round(hi, 6), warnings, False


def estimate_job(
    m: ModelManifest,
    job: Job,
    prices: dict[str, Any],
    stale_days: int = 30,
    today: date | None = None,
) -> tuple[float, float, list[str]]:
    lo, hi, w, _ = estimate_job_ex(m, job, prices, stale_days, today)
    return lo, hi, w


def estimate_jobs(
    m: ModelManifest, jobs: list[Job], prices: dict[str, Any], stale_days: int = 30, today: date | None = None
) -> dict[str, Any]:
    per_job: list[dict[str, Any]] = []
    warnings: list[str] = []
    lo_t = hi_t = 0.0
    any_unknown = False
    for j in jobs:
        lo, hi, w, unknown = estimate_job_ex(m, j, prices, stale_days, today)
        j.cost_estimate_usd = [lo, hi]
        per_job.append({"jobId": j.id, "minUsd": lo, "maxUsd": hi, "variantCount": j.variant_count,
                        "axis": j.axis, "prompt": j.prompt, "unknownPrice": unknown})
        any_unknown = any_unknown or unknown
        lo_t += lo
        hi_t += hi
        for x in w:
            if x not in warnings:
                warnings.append(x)
    return {"minUsd": round(lo_t, 6), "maxUsd": round(hi_t, 6), "perJob": per_job, "warnings": warnings,
            "unknownPrice": any_unknown}
