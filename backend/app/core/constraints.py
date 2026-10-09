"""Constraint engine: manifest params + declarative when/then/block rules -> effective params.

Backend is the final authority. force (`then`) locks a value with a reason; forbid (`block`) rejects.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.schemas import ModelManifest, Param

_RATIO = re.compile(r"^\d+:\d+$")
_SIZE = re.compile(r"^(\d{1,5})x(\d{1,5})$")
MAX_ITER = 10


@dataclass
class Resolved:
    mode: str
    effective: dict[str, Any] = field(default_factory=dict)
    locked: list[dict[str, str]] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    return a == b


def _in(value: Any, options: list[Any]) -> bool:
    return any(_same(value, o) for o in options)


def applies(p: Param, mode: str) -> bool:
    return not p.applies_to_modes or mode in p.applies_to_modes


def check_value(p: Param, v: Any) -> str | None:
    """Return an error message or None."""
    t = p.type
    if t == "bool":
        return None if isinstance(v, bool) else "must be boolean"
    if t == "int":
        if isinstance(v, bool) or not isinstance(v, int):
            return "must be integer"
    elif t == "float":
        if isinstance(v, bool) or not isinstance(v, int | float):
            return "must be number"
    elif t == "text":
        if not isinstance(v, str):
            return "must be string"
        return check_size(p, v) if p.size_rule is not None else None
    elif t == "ratio":
        if not isinstance(v, str) or not _RATIO.match(v):
            return "must look like W:H"
    if p.values is not None and not _in(v, p.values):
        return f"must be one of {p.values}"
    if p.range is not None and isinstance(v, int | float) and not isinstance(v, bool):
        if v < p.range.min or v > p.range.max:
            return f"must be within [{p.range.min}, {p.range.max}]"
    if t == "enum" and p.values is None:
        return "enum param has no values"
    return None


def check_size(p: Param, v: str) -> str | None:
    rule = p.size_rule
    assert rule is not None
    if v in rule.allow:
        return None
    m = _SIZE.fullmatch(v)
    if not m:
        return "must look like WxH" + (f" or one of {rule.allow}" if rule.allow else "")
    w, h = int(m.group(1)), int(m.group(2))
    if w <= 0 or h <= 0 or w % rule.multiple_of or h % rule.multiple_of:
        return f"both edges must be positive multiples of {rule.multiple_of}"
    if rule.max_edge is not None and max(w, h) > rule.max_edge:
        return f"longest edge must be <= {rule.max_edge}"
    if rule.max_ratio is not None and max(w, h) > rule.max_ratio * min(w, h):
        return f"aspect ratio must be at most {rule.max_ratio:g}:1"
    if rule.min_pixels is not None and w * h < rule.min_pixels:
        return f"total pixels must be >= {rule.min_pixels}"
    if rule.max_pixels is not None and w * h > rule.max_pixels:
        return f"total pixels must be <= {rule.max_pixels}"
    return None


def _match(when: dict[str, Any], state: dict[str, Any]) -> bool:
    for k, want in when.items():
        have = state.get(k)
        if have is None:
            return False
        opts = want if isinstance(want, list) else [want]
        if not _in(have, opts):
            return False
    return True


def resolve(
    m: ModelManifest,
    mode: str | None,
    params: dict[str, Any] | None,
    assets: dict[str, Any] | None = None,
    check_assets: bool = False,
) -> Resolved:
    mode = mode or m.modes[0]
    res = Resolved(mode=mode)
    if mode not in m.modes:
        res.errors.append({"key": "mode", "reason": f"mode must be one of {m.modes}"})
        return res
    params = dict(params or {})
    by_key = {p.key: p for p in m.params}

    # 1. defaults for applicable, supported, value-typed params
    eff: dict[str, Any] = {}
    for p in m.params:
        if p.supported and applies(p, mode) and p.type not in ("image", "imageList") and p.default is not None:
            eff[p.key] = p.default

    # 2. user values (validated); unknown/unsupported -> error, inapplicable to mode -> dropped
    for k, v in params.items():
        p = by_key.get(k)
        if p is None:
            res.errors.append({"key": k, "reason": f"unknown param for model {m.id}"})
            continue
        if not p.supported:
            res.errors.append({"key": k, "reason": f"{m.id} does not support {k}"})
            continue
        if not applies(p, mode):
            continue
        if p.type in ("image", "imageList"):
            # asset id(s) may be given here (same as the `assets` map); echoed so Reuse keeps the slots
            ids = v if isinstance(v, list) else [v]
            if v is None:
                continue
            if not all(isinstance(i, str) and i for i in ids) or (p.type == "image" and len(ids) != 1):
                res.errors.append({"key": k, "reason": "expected an asset id" + ("" if p.type == "image" else " list")})
                continue
            eff[k] = v
            continue
        if v is None:
            eff.pop(k, None)
            continue
        msg = check_value(p, v)
        if msg:
            res.errors.append({"key": k, "reason": msg})
            continue
        eff[k] = v

    # 3. force rules to fixpoint. A scalar `then` forces the value; a list `then` is an ALLOWED SET (same as the
    #    frontend): a value outside it snaps to the first entry. Block rules are NOT part of the loop.
    locked: dict[tuple[str, str], None] = {}
    for _ in range(MAX_ITER):
        changed = False
        state = {**eff, "mode": mode}
        for c in m.constraints:
            if c.block or not _match(c.when, state):
                continue
            for k, v in (c.then or {}).items():
                p = by_key[k]
                if not applies(p, mode):
                    continue
                opts = v if isinstance(v, list) else [v]
                if not opts:
                    continue
                locked[(k, c.reason)] = None
                if len(opts) == 1:
                    target = opts[0]
                    if not _same(eff.get(k), target):
                        eff[k] = target
                        changed = True
                elif not _in(eff.get(k), opts):
                    eff[k] = opts[0]
                    changed = True
        if not changed:
            break
    else:
        res.errors.append({"key": "*", "reason": "constraints do not converge"})
    # block rules: evaluated once, on the state AFTER the fixpoint (matches frontend/constraints.ts)
    final = {**eff, "mode": mode}
    blocked: dict[str, dict[str, str]] = {}
    for c in m.constraints:
        if c.block and _match(c.when, final):
            blocked[c.reason] = {"key": ",".join(c.when), "reason": c.reason}
    res.errors.extend(blocked.values())
    res.locked = [{"key": k, "reason": r} for (k, r) in locked]
    res.effective = eff

    # 4. assets (only when asked: /resolve has no assets)
    slots = {k: v for k, v in eff.items() if (p := by_key.get(k)) and p.type in ("image", "imageList")}
    if check_assets or slots:  # a bare /resolve (no slots yet) must not demand them; partial slots are validated
        res.errors.extend(check_asset_slots(m, mode, {**slots, **(assets or {})}))
    return res


def check_asset_slots(m: ModelManifest, mode: str, assets: dict[str, Any]) -> list[dict[str, str]]:
    errs: list[dict[str, str]] = []
    by_key = {p.key: p for p in m.params}
    for slot, val in assets.items():
        p = by_key.get(slot)
        if p is None or p.type not in ("image", "imageList"):
            errs.append({"key": slot, "reason": f"unknown asset slot for model {m.id}"})
            continue
        if not p.supported or not applies(p, mode):
            errs.append({"key": slot, "reason": f"slot {slot} not available in mode {mode}"})
            continue
        ids = val if isinstance(val, list) else [val]
        if p.type == "image" and len(ids) != 1:
            errs.append({"key": slot, "reason": "exactly one asset expected"})
        if p.type == "imageList" and p.max_items is not None and len(ids) > p.max_items:
            errs.append({"key": slot, "reason": f"at most {p.max_items} assets"})
    for p in m.params:
        if p.type in ("image", "imageList") and p.supported and p.required and applies(p, mode):
            if not assets.get(p.key):
                errs.append({"key": p.key, "reason": f"{p.key} is required in mode {mode}"})
    return errs
