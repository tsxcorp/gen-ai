"""Provider registry (vertex, openai, byteplus): per-provider config schema, validation, masking.

providers.json layout (0600, never leaves the backend):
  vertex   {authMethod, projectId, location, gcsBucket, serviceAccountJson|serviceAccountPath}
  openai   {apiKey, organization, project}
  byteplus {apiKey, region}
Every function works on ONE provider's dict; nothing here reads or writes another provider's entry (invariant 26).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.adapters.vertex_common import validate_vertex_fields
from app.errors import ApiError

PROVIDER_IDS = ("vertex", "openai", "byteplus")
DEFAULT_BYTEPLUS_REGION = "ap-southeast"
DEFAULT_VERTEX_LOCATION = "us-central1"

REGION_RE = re.compile(r"^[a-z]+(-[a-z0-9]+)*$")  # becomes part of a host name: no dots, no slashes
SECRET_RE = re.compile(r"^[\x21-\x7e]{8,512}$")  # printable ASCII, no whitespace/control chars (header injection)
IDENT_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")  # OpenAI organization / project ids (sent as headers)
SA_REQUIRED = ("client_email", "private_key")


def valid_region(v: str) -> bool:
    return len(v) <= 32 and bool(REGION_RE.fullmatch(v))


def _check_sa(info: Any) -> dict[str, Any]:
    if not isinstance(info, dict) or info.get("type") != "service_account" or any(not info.get(f) for f in SA_REQUIRED):
        raise ApiError("invalid", "not a service account key (needs type=service_account, client_email, private_key)")
    return info


def vertex_auth_method(cfg: dict[str, Any] | None) -> str | None:
    """'adc' | 'service_account' | None (nothing stored). Files written before authMethod existed are service_account."""
    if not isinstance(cfg, dict) or not cfg:
        return None
    if cfg.get("authMethod") == "adc":
        return "adc"
    return "service_account"


def is_configured(provider: str, cfg: Any) -> bool:
    if not isinstance(cfg, dict):
        return False
    if provider == "vertex":
        if not cfg.get("projectId"):
            return False
        return cfg.get("authMethod") == "adc" or bool(cfg.get("serviceAccountJson") or cfg.get("serviceAccountPath"))
    return isinstance(cfg.get("apiKey"), str) and bool(cfg["apiKey"])


def mask_one(provider: str, cfg: Any) -> dict[str, Any]:
    """Public view of one provider: flags and non-secret identifiers only."""
    cfg = cfg if isinstance(cfg, dict) else {}
    if provider == "vertex":
        auth = vertex_auth_method(cfg)
        has_key = auth == "service_account" and bool(cfg.get("serviceAccountJson") or cfg.get("serviceAccountPath"))
        return {
            "configured": is_configured("vertex", cfg), "hasKey": has_key, "authMethod": auth,
            "keySource": ("json" if cfg.get("serviceAccountJson") else "path") if has_key else None,
            "projectId": cfg.get("projectId"), "location": cfg.get("location"), "gcsBucket": cfg.get("gcsBucket"),
        }
    if provider == "openai":
        return {"configured": is_configured("openai", cfg), "hasKey": bool(cfg.get("apiKey")),
                "organization": cfg.get("organization"), "project": cfg.get("project")}
    return {"configured": is_configured("byteplus", cfg), "hasKey": bool(cfg.get("apiKey")),
            "region": cfg.get("region")}


def mask_all(data: dict[str, Any]) -> dict[str, Any]:
    return {p: mask_one(p, data.get(p)) for p in PROVIDER_IDS}


# ---------------------------------------------------------------- PUT validation
def _optional_str(body: dict[str, Any], key: str, current: Any) -> Any:
    """Absent -> keep the stored value; null/'' -> clear; otherwise a validated identifier."""
    if key not in body:
        return current
    v = body[key]
    if v is None or v == "":
        return None
    if not isinstance(v, str) or not IDENT_RE.fullmatch(v.strip()):
        raise ApiError("invalid", f"{key} has an invalid format")
    return v.strip()


def _api_key(body: dict[str, Any], current: dict[str, Any]) -> str:
    """Blank/absent key keeps the stored one; nothing stored -> required. The value is never echoed in errors."""
    raw = body.get("apiKey")
    if raw is None or raw == "":
        if isinstance(current.get("apiKey"), str) and current["apiKey"]:
            return current["apiKey"]
        raise ApiError("invalid", "apiKey is required")
    if not isinstance(raw, str) or not SECRET_RE.fullmatch(raw.strip()):
        raise ApiError("invalid", "apiKey has an invalid format (8-512 printable characters, no spaces)")
    return raw.strip()


def _put_openai(body: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    return {"apiKey": _api_key(body, current),
            "organization": _optional_str(body, "organization", current.get("organization")),
            "project": _optional_str(body, "project", current.get("project"))}


def _put_byteplus(body: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    region = body.get("region") if body.get("region") not in (None, "") else (
        current.get("region") or DEFAULT_BYTEPLUS_REGION)
    if not isinstance(region, str) or not valid_region(region.strip()):
        raise ApiError("invalid", "region has an invalid format (lowercase letters, digits, hyphens)")
    return {"apiKey": _api_key(body, current), "region": region.strip()}


def _put_vertex(body: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    method = body.get("authMethod") if body.get("authMethod") is not None else (
        vertex_auth_method(current) or "service_account")
    if method not in ("service_account", "adc"):
        raise ApiError("invalid", "authMethod must be service_account or adc")
    path, raw_json = body.get("serviceAccountPath"), body.get("json")
    if path and raw_json:
        raise ApiError("invalid", "send either serviceAccountPath or json, not both")
    project = body.get("projectId")
    if not isinstance(project, str) or not project.strip():
        raise ApiError("invalid", "projectId is required")
    location = body["location"] if "location" in body and body["location"] is not None else DEFAULT_VERTEX_LOCATION
    bucket = body.get("gcsBucket") or None
    if not isinstance(location, str) or (bucket is not None and not isinstance(bucket, str)):
        raise ApiError("invalid", "location and gcsBucket must be strings")
    # invariant 13: these end up in the URL that receives the Bearer token -> strict shapes
    validate_vertex_fields(project.strip(), location.strip(), bucket.strip() if bucket else None)

    cur = dict(current)
    if method == "adc":
        if path or raw_json:
            raise ApiError("invalid", "authMethod=adc does not take a service account key")
        cur.pop("serviceAccountJson", None)  # an unused key must not linger on disk
        cur.pop("serviceAccountPath", None)
    elif raw_json:
        try:
            info = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
        except ValueError:
            raise ApiError("invalid", "json is not valid JSON") from None
        cur["serviceAccountJson"] = _check_sa(info)
        cur.pop("serviceAccountPath", None)
    elif path:
        p = Path(str(path)).expanduser()
        try:
            _check_sa(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError, ApiError):  # one message for every failure: no file-existence/shape oracle
            raise ApiError("invalid", "serviceAccountPath is not a readable service account key file") from None
        cur["serviceAccountPath"] = str(p)
        cur.pop("serviceAccountJson", None)
    elif not (cur.get("serviceAccountJson") or cur.get("serviceAccountPath")):
        raise ApiError("invalid", "serviceAccountPath or json is required")
    cur.update({"authMethod": method, "projectId": project.strip(), "location": location.strip(),
                "gcsBucket": bucket.strip() if bucket else None})
    return cur


_PUT = {"vertex": _put_vertex, "openai": _put_openai, "byteplus": _put_byteplus}


def apply_put(provider: str, body: Any, current: Any) -> dict[str, Any]:
    """Validate a PUT body and return the NEW config of this one provider (caller stores it)."""
    if provider not in _PUT:
        raise ApiError("not_found", f"unknown provider {provider!r}", {"known": list(PROVIDER_IDS)})
    if not isinstance(body, dict):
        raise ApiError("invalid", "body must be an object")
    return _PUT[provider](body, current if isinstance(current, dict) else {})
