"""Hypothesis properties. Invariants come from requirements business rules only."""
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from vhelpers import *

S = settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])


def all_manifests(c):
    return [full_manifest(c, s["id"]) for s in summaries(c)]


def value_strategy(p):
    t = p.get("type")
    if p.get("values"):
        return st.sampled_from(p["values"])
    if t in ("bool", "boolean"):
        return st.booleans()
    if t in ("int", "integer", "number") and "min" in p and "max" in p:
        return st.integers(int(p["min"]), int(p["max"]))
    return None


@st.composite
def scenario(draw, manifests):
    m = draw(st.sampled_from(manifests))
    params = {}
    for p in params_of(m):
        vs = value_strategy(p)
        if vs is not None and draw(st.booleans()):
            params[p["key"]] = draw(vs)
    mode = draw(st.sampled_from(m["modes"])) if m.get("modes") else None
    return m, mode, params


def do_resolve(c, m, mode, params):
    body = {"modelId": m["id"], "params": {"prompt": "p", **params}}
    if mode:
        body["mode"] = mode
    return c.post("/api/resolve", json=body)


def violations(m, eff):
    """Business rules from requirements, evaluated on an effective param set."""
    mid = m["id"].lower()
    out = []
    res = pkey(m, "resolution")
    dur = pkey(m, "duration")
    size = pkey(m, "imagesize", "size") if m["kind"] == "image" else None
    r = str(eff.get(res, "")).lower() if res else ""
    if "veo" in mid:
        if r in ("1080p", "4k") and eff.get(dur) != 8:
            out.append(f"veo {r} needs duration 8, got {eff.get(dur)}")
        if "lite" in mid and r == "4k":
            out.append("veo lite 4k")
        last = pkey(m, "last")
        first = pkey(m, "first", "image", exclude=("last",))
        if last and eff.get(last) and not (first and eff.get(first)):
            out.append("lastFrame without image")
    if "omni" in mid and r:
        vp = omni_variant_param(m)
        sel = str(eff.get(vp["key"], "")) if vp else ""
        # 720p-only rule applies ONLY to the non-1.1 variant (separate manifest id or selected variant)
        if (is_omni_non_11(mid) or (sel and is_omni_non_11(sel))) and r != "720p":
            out.append(f"omni non-1.1 {r}")
    if "omni" in mid and (pkey(m, "negative") or pkey(m, "seed")):
        out.append("omni exposes negative/seed")
    if m["kind"] == "image" and "lite" in mid and size and eff.get(size) not in (None, "1K"):
        out.append(f"flash-lite size {eff.get(size)}")
    if m["kind"] == "image" and size and isinstance(eff.get(size), str) and eff[size].endswith("k"):
        out.append("lowercase k size")
    return out


@S
@given(data=st.data())
def test_resolve_never_returns_rule_violating_combination(shared_client, data):
    ms = all_manifests(shared_client)
    m, mode, params = data.draw(scenario(ms))
    r = do_resolve(shared_client, m, mode, params)
    assert r.status_code in (200, 400, 422), r.text
    if r.status_code != 200:
        assert api_error_kind(r) == "invalid"
        return
    b = r.json()
    if b["errors"]:
        return  # rejecting is always allowed; silently emitting a bad combo is not
    assert violations(m, b["effectiveParams"]) == []


@S
@given(data=st.data())
def test_resolve_is_idempotent(shared_client, data):
    ms = all_manifests(shared_client)
    m, mode, params = data.draw(scenario(ms))
    r1 = do_resolve(shared_client, m, mode, params)
    if r1.status_code != 200 or r1.json()["errors"]:
        return
    eff = r1.json()["effectiveParams"]
    r2 = do_resolve(shared_client, m, mode, {k: v for k, v in eff.items() if k != "prompt"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["errors"] == []
    assert r2.json()["effectiveParams"] == eff
    assert r2.json()["locked"] == r1.json()["locked"] or {l["key"] for l in r2.json()["locked"]} == {l["key"] for l in r1.json()["locked"]}


@S
@given(data=st.data())
def test_locked_fields_have_reasons_and_match_effective(shared_client, data):
    ms = all_manifests(shared_client)
    m, mode, params = data.draw(scenario(ms))
    r = do_resolve(shared_client, m, mode, params)
    if r.status_code != 200:
        return
    b = r.json()
    for l in b["locked"]:
        assert l["reason"] and l["key"] in b["effectiveParams"]


@S
@given(data=st.data(), n=st.integers(1, 24))
def test_estimate_min_le_max_and_monotonic_in_jobs(shared_client, data, n):
    ms = all_manifests(shared_client)
    m, mode, params = data.draw(scenario(ms))
    req = make_request(m, params=params, mode=mode)
    a = estimate(shared_client, req, make_sweep(n))
    if a.status_code != 200:
        assert api_error_kind(a) == "invalid"
        return
    a = a.json()
    assert 0 <= a["minUsd"] <= a["maxUsd"]
    assert a["jobCount"] >= n or m["kind"] == "video"
    if n < 24:
        b = estimate(shared_client, req, make_sweep(n + 1))
        assert b.status_code == 200
        b = b.json()
        assert b["minUsd"] >= a["minUsd"] - 1e-9 and b["maxUsd"] >= a["maxUsd"] - 1e-9
        assert b["jobCount"] >= a["jobCount"]


@S
@given(n=st.integers(1, 60))
def test_batch_cap_is_exactly_24(shared_client, n):
    ms = [full_manifest(shared_client, s["id"]) for s in summaries(shared_client) if s["kind"] == "image"]
    m = ms[0]
    r = estimate(shared_client, make_request(m), make_sweep(n))
    if n <= 24:
        assert r.status_code == 200, r.text
        assert r.json()["jobCount"] == n
    else:
        assert r.status_code >= 400 or any("24" in str(w) for w in r.json().get("warnings", []))
        p = post_batch(shared_client, make_request(m), make_sweep(n))
        assert 400 <= p.status_code < 500 and api_error_kind(p) == "invalid"


@settings(max_examples=15, deadline=None)
@given(prompt=st.sampled_from(["[blocked]", "x [blocked] y", "[BLOCKED-ish] [blocked]"]))
def test_blocked_never_retried_property(shared_client, prompt):
    import time
    done, _ = run_one(shared_client, prompt=prompt)
    j = done["jobs"][0]
    assert j["status"] == "blocked"
    time.sleep(0.2)
    j2 = shared_client.get(f"/api/batches/{j['batchId']}").json()["jobs"][0]
    assert j2["status"] == "blocked"
    for k in ("attempts", "attempt", "tries"):
        if k in j2:
            assert j2[k] <= 1


@settings(max_examples=25, deadline=None)
@given(blob=st.binary(min_size=1, max_size=2048))
def test_zip_roundtrips_arbitrary_upload_bytes(shared_client, blob):
    """Original bytes must come out of ZIP unchanged (no re-encode), for any content."""
    import hashlib
    r = shared_client.post("/api/uploads", files={"file": ("x.png", blob, "image/png")},
                           data={"hasPerson": "false", "consent": "false"})
    if r.status_code not in (200, 201):
        assert 400 <= r.status_code < 500  # content validation is allowed to refuse
        return
    a = r.json()
    a = a.get("asset", a)
    members = zip_members(shared_client.post("/api/zip", json={"assetIds": [a["id"]]}).content)
    assert hashlib.sha256(blob).hexdigest() in {hashlib.sha256(v).hexdigest() for n, v in members.items() if not n.endswith(".json")}


def test_properties_cover_the_stated_rules_at_least_once(shared_client):
    """Guard against vacuous properties: the discovery must have found each rule's subject."""
    ids = " ".join(s["id"].lower() for s in summaries(shared_client))
    for needle in ("veo", "omni"):
        assert needle in ids, f"no {needle} manifest: properties for its rules are vacuous"


def test_omni_11_manifest_not_restricted_to_720p_by_property(shared_client):
    """Guards the property against vacuity/over-reach: the 1.1 Omni model must still offer >720p."""
    for m in all_manifests(shared_client):
        if "omni" in m["id"].lower() and "1.1" in m["id"]:
            res = pkey(m, "resolution")
            assert {"1080p", "4k"} <= {str(v).lower() for v in values_of(m, res)}
            return
    raise AssertionError("Omni 1.1 manifest missing")
