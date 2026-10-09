"""Load + validate manifests (YAML). Cross-checks constraints/defaults/pricing against params."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.schemas import ModelManifest


class ManifestError(Exception):
    pass


def _as_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else [v]


def validate_manifest(m: ModelManifest) -> None:
    errs: list[str] = []
    keys = [p.key for p in m.params]
    if len(keys) != len(set(keys)):
        errs.append("duplicate param keys")
    if not m.modes:
        errs.append("modes is empty")
    by_key = {p.key: p for p in m.params}
    for p in m.params:
        for mode in p.applies_to_modes:
            if mode not in m.modes:
                errs.append(f"param {p.key}: unknown mode {mode}")
        if p.type == "enum":
            if not p.values:
                errs.append(f"param {p.key}: enum without values")
            elif p.default is not None and p.default not in p.values:
                errs.append(f"param {p.key}: default {p.default!r} not in values")
        if p.supported and p.type not in ("image", "imageList") and not p.provider_path:
            errs.append(f"param {p.key}: supported param needs providerPath")
    for i, c in enumerate(m.constraints):
        if bool(c.then) == c.block:
            errs.append(f"constraint #{i}: exactly one of then/block required")
        for k, v in c.when.items():
            if k == "mode":
                for mode in _as_list(v):
                    if mode not in m.modes:
                        errs.append(f"constraint #{i}: unknown mode {mode}")
            elif k not in by_key:
                errs.append(f"constraint #{i}: when-key {k} is not a param")
        for k, v in (c.then or {}).items():
            p = by_key.get(k)
            if p is None:
                errs.append(f"constraint #{i}: then-key {k} is not a param")
            elif p.type == "enum" and p.values and any(x not in p.values for x in _as_list(v)):
                errs.append(f"constraint #{i}: forced {k}={v!r} not in values")
    for i, row in enumerate(m.pricing.table):
        for k in row.when:
            if k not in by_key:
                errs.append(f"pricing row #{i}: when-key {k} is not a param")
    try:
        date.fromisoformat(m.last_verified)
    except ValueError:
        errs.append("lastVerified must be YYYY-MM-DD")
    if errs:
        raise ManifestError(f"manifest {m.id}: " + "; ".join(errs))


def load_manifests(directory: Path) -> dict[str, ModelManifest]:
    out: dict[str, ModelManifest] = {}
    for f in sorted(Path(directory).glob("*.y*ml")):
        try:
            raw = yaml.safe_load(f.read_text(encoding="utf-8"))
            m = ModelManifest.model_validate(raw)
        except (yaml.YAMLError, ValidationError) as e:
            raise ManifestError(f"{f.name}: {e}") from e
        validate_manifest(m)
        if m.id in out:
            raise ManifestError(f"duplicate manifest id {m.id}")
        out[m.id] = m
    return out


def manifest_warnings(m: ModelManifest, stale_days: int = 30, today: date | None = None) -> list[str]:
    today = today or date.today()
    w: list[str] = []
    age = (today - date.fromisoformat(m.last_verified)).days
    if age > stale_days:
        w.append(f"manifest last verified {age} days ago (>{stale_days}); parameters may be outdated")
    if m.status == "deprecated":
        w.append("model is deprecated")
    if m.sunset_date:
        left = (date.fromisoformat(m.sunset_date) - today).days
        if left < 0:
            w.append(f"model sunset date {m.sunset_date} has passed")
        elif left <= 60:
            w.append(f"model sunsets on {m.sunset_date} ({left} days)")
    if not m.verified or not m.verified_live:
        w.append("payload not confirmed by a live API call: fields marked [?] may be rejected by the provider")
    if m.status == "preview":
        w.append("preview model: schema/behaviour may change")
    return w


def manifest_summary(m: ModelManifest, stale_days: int = 30) -> dict[str, Any]:
    return {
        "id": m.id, "label": m.label, "provider": m.provider, "kind": m.kind, "status": m.status,
        "sunsetDate": m.sunset_date, "lastVerified": m.last_verified,
        "verified": m.verified, "verifiedLive": m.verified_live,
        "warnings": manifest_warnings(m, stale_days),
    }
