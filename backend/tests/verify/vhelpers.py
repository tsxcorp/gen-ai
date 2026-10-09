"""Helpers for spec-blind verification tests.

Every guess about request SHAPES (the docs only give field names, not full
schemas) is isolated here so a spec clarification means a one-line change.
Guesses are listed in GUESSES and reported back as spec gaps.
"""
from __future__ import annotations

import io
import time
import zipfile

TERMINAL = {"succeeded", "failed", "blocked", "canceled"}

# 1x1 PNG
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360f8cfc0f01f0005000201a5f645400000000049454e44ae426082"
)

GUESSES = [
    "request = {modelId, mode, params{prompt,...}}; prompt lives in params['prompt']",
    "sweep = {prompts:[...], n:int, axes:{paramKey:[values]}}",
    "confirm_required is signalled by a >=400 response whose body contains 'confirm_required'",
    "upload multipart field name is 'file'; flags are form fields hasPerson/consent",
    "asset objects carry 'id'",
    "batch GET returns {jobs:[...]}",
]


def api_error_kind(resp) -> str | None:
    try:
        return resp.json().get("error", {}).get("kind")
    except Exception:
        return None


def summaries(client) -> list[dict]:
    r = client.get("/api/manifests")
    assert r.status_code == 200, r.text
    body = r.json()
    items = body if isinstance(body, list) else body.get("manifests", body.get("items"))
    assert isinstance(items, list) and items, f"unexpected manifest list: {body!r}"
    return items


def full_manifest(client, mid: str) -> dict:
    r = client.get(f"/api/manifests/{mid}")
    assert r.status_code == 200, r.text
    return r.json()


def find_model(client, *, kind=None, has=(), lacks=()):
    """Discover a manifest id by substrings of its id. Returns id or None."""
    for s in summaries(client):
        i = s["id"].lower()
        if kind and s.get("kind") != kind:
            continue
        if all(h in i for h in has) and not any(l in i for l in lacks):
            return s["id"]
    return None


def need_model(client, **kw):
    import pytest

    mid = find_model(client, **kw)
    if mid is None:
        pytest.skip(f"documented model not present in /api/manifests (criteria {kw}); "
                    f"present: {[s['id'] for s in summaries(client)]}")
    return mid


def params_of(m: dict) -> list[dict]:
    return m.get("params", [])


def pkey(m: dict, *needles, exclude=()):
    """Find a param key in manifest containing any needle (case-insens)."""
    for p in params_of(m):
        k = p["key"].lower().replace("_", "")
        if any(n in k for n in needles) and not any(e in k for e in exclude):
            return p["key"]
    return None


def pdef(m: dict, key: str) -> dict:
    return next(p for p in params_of(m) if p["key"] == key)


def values_of(m: dict, key: str) -> list:
    return pdef(m, key).get("values", [])


def mode_of(m: dict, preferred=None):
    modes = m.get("modes")
    if not modes:
        return None
    if preferred and preferred in modes:
        return preferred
    return modes[0]


def make_request(m: dict, prompt="a red apple", params=None, mode=None) -> dict:
    p = {"prompt": prompt}
    p.update(params or {})
    req = {"modelId": m["id"], "params": p}
    md = mode or mode_of(m)
    if md:
        req["mode"] = md
    return req


def make_sweep(n=1, prompts=None, axes=None) -> dict:
    s = {"n": n}
    if prompts is not None:
        s["prompts"] = prompts
    if axes:
        s["axes"] = axes
    return s


def post_batch(client, req, sweep=None, confirm=True):
    return client.post("/api/batches", json={
        "request": req, "sweep": sweep or make_sweep(1), "confirmOverThreshold": confirm})


def estimate(client, req, sweep=None):
    return client.post("/api/estimate", json={"request": req, "sweep": sweep or make_sweep(1)})


def wait_batch(client, batch_id, timeout=60.0, until=None):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        r = client.get(f"/api/batches/{batch_id}")
        assert r.status_code == 200, r.text
        last = r.json()
        jobs = last["jobs"]
        if until:
            if until(last):
                return last
        elif jobs and all(j["status"] in TERMINAL for j in jobs):
            return last
        time.sleep(0.05)
    raise AssertionError(f"batch {batch_id} did not settle in {timeout}s: {last}")


def run_one(client, model_id=None, prompt="a red apple", params=None, mode=None):
    """Create a 1-job batch on the given (or first image) model and wait."""
    mid = model_id or find_model(client, kind="image")
    m = full_manifest(client, mid)
    r = post_batch(client, make_request(m, prompt, params, mode))
    assert r.status_code in (200, 201, 202), r.text
    return wait_batch(client, r.json()["batchId"]), m


def fake_service_account(tag="X"):
    """Fake SA JSON with unmistakable secret markers (never a real key)."""
    body = "SECRETBODY" + tag * 20 + "ZZTOP" + tag * 12
    pem = "-----BEGIN " + "PRIVATE KEY-----\n" + body + "\n-----END " + "PRIVATE KEY-----\n"
    kid = "kid" + tag.lower() * 16
    sa = {
        "type": "service_account", "project_id": "demo-proj",
        "private_key_id": kid, "private_key": pem,
        "client_email": "svc@demo-proj.iam.gserviceaccount.com", "client_id": "1234567890",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    return sa, [body, kid]


def zip_members(data: bytes) -> dict[str, bytes]:
    z = zipfile.ZipFile(io.BytesIO(data))
    return {n: z.read(n) for n in z.namelist() if not n.endswith("/")}


def contains_any(blob: bytes | str, needles) -> list[str]:
    if isinstance(blob, str):
        blob = blob.encode("utf-8", "ignore")
    return [n for n in needles if n.encode() in blob]


def walk_numbers_usd(obj, factor):
    """Multiply every numeric 'usd' value in a manifest (any depth) by factor."""
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if k == "usd" and isinstance(v, (int, float)):
                obj[k] = v * factor
            elif k == "usd" and isinstance(v, list):
                obj[k] = [x * factor for x in v]
            else:
                walk_numbers_usd(v, factor)
    elif isinstance(obj, list):
        for x in obj:
            walk_numbers_usd(x, factor)
    return obj


def has_asset_ids(batch) -> list[dict]:
    out = []
    for j in batch["jobs"]:
        for a in j.get("assets", []) or []:
            assert "id" in a, f"asset without id: {a}"
            out.append(a)
    return out


def is_omni_non_11(text) -> bool:
    """Spec: `gemini-omni-flash-preview` (no '1.1') is the 720p-only Omni model."""
    t = str(text).lower()
    return "omni" in t and "1.1" not in t


def omni_variant_param(m: dict):
    """A param of an Omni manifest that selects the model variant (key mentions model/variant),
    or None. Values are discovered from the manifest at runtime."""
    for p in params_of(m):
        k = p["key"].lower()
        if ("variant" in k or k in ("model", "modelid", "model_id")) and p.get("values"):
            return p
    return None
