"""Hardening invariants 12-23 (docs/architecture.md), observed via HTTP in demo mode only.

Convention: the TestClient default Host is `testserver`, which invariant 12 says must be rejected,
so every client here is pinned to Host: localhost (a documented allowed host) by `mk`.
Invariants 14, 16, 18, 19, 24 are not observable through demo HTTP (see report); #17 is only weakly
observable (demo adapter has no raw-provider-error hook).
"""
import copy
import json
import os
import re
import time

import pytest
from vhelpers import *

TOKEN = "tok-s13-verify-9f3a"


@pytest.fixture
def mk(make_client):
    def _mk(**env):
        c = make_client(**env)
        c.headers["host"] = "localhost"
        return c

    return _mk


@pytest.fixture
def c(mk):
    return mk()


def img(c):
    mid = find_model(c, kind="image")
    return full_manifest(c, mid)


def settings(c):
    r = c.get("/api/settings")
    assert r.status_code == 200, r.text
    return r.json()


def put_settings(c, **over):
    return c.put("/api/settings", json={**settings(c), **over})


def err_kind(r):
    return api_error_kind(r)


# ---------------------------------------------------------------- invariant 12
@pytest.mark.parametrize("path", ["/api/providers", "/api/manifests", "/api/settings"])
def test_inv12_foreign_host_header_rejected(c, path):
    r = c.get(path, headers={"host": "evil.example"})
    assert r.status_code in (400, 403, 421), f"{path} answered {r.status_code} to Host: evil.example"
    assert "hasKey" not in r.text


def test_inv12_foreign_host_with_port_rejected(c):
    r = c.get("/api/providers", headers={"host": "evil.example:8000"})
    assert r.status_code in (400, 403, 421)


@pytest.mark.parametrize("host", ["localhost", "localhost:5173", "127.0.0.1", "127.0.0.1:8000", "[::1]", "[::1]:8000"])
def test_inv12_loopback_hosts_allowed(c, host):
    assert c.get("/api/manifests", headers={"host": host}).status_code == 200


def test_inv12_cross_origin_writes_rejected_and_have_no_effect(c):
    before = settings(c)
    evil = {"origin": "http://evil.example"}
    r = c.put("/api/settings", json={**before, "confirmThresholdUsd": 999}, headers=evil)
    assert r.status_code in (400, 403), r.status_code
    assert settings(c) == before
    r = c.post("/api/estimate", json={}, headers=evil)
    assert r.status_code in (400, 403)
    r = c.post("/api/providers/vertex/test", headers=evil)
    assert r.status_code in (400, 403)
    r = c.post("/api/uploads", files={"file": ("a.png", PNG, "image/png")},
               data={"hasPerson": "false", "consent": "false"}, headers=evil)
    assert r.status_code in (400, 403)
    # nothing was stored by the rejected upload
    assert not [f for _, _, fs in os.walk(c.tmp_dir) for f in fs]


def test_inv12_cross_origin_cancel_and_retry_rejected(c):
    done, _ = run_one(c, prompt="[fail] x")
    jid, bid = done["jobs"][0]["id"], done["batchId"] if "batchId" in done else None
    evil = {"origin": "http://evil.example"}
    assert c.post(f"/api/jobs/{jid}/retry", headers=evil).status_code in (400, 403)
    if bid:
        assert c.post(f"/api/batches/{bid}/cancel", headers=evil).status_code in (400, 403)


def test_inv12_same_origin_and_originless_writes_still_work(c):
    s = settings(c)
    assert c.put("/api/settings", json=s, headers={"origin": "http://localhost"}).status_code == 200
    assert c.put("/api/settings", json=s, headers={"origin": "http://localhost:5173"}).status_code == 200
    assert c.put("/api/settings", json=s).status_code == 200


@pytest.mark.parametrize("method,path", [("PUT", "/api/settings"), ("POST", "/api/estimate"), ("PUT", "/api/presets")])
def test_inv12_json_content_type_required(c, method, path):
    before = settings(c)
    body = json.dumps({**before, "confirmThresholdUsd": 777}) if path == "/api/settings" else "{}"
    for ct in ({"content-type": "text/plain"}, {"content-type": "application/x-www-form-urlencoded"}, {}):
        r = c.request(method, path, content=body.encode(), headers=ct)
        assert r.status_code in (400, 415), f"{method} {path} ct={ct} -> {r.status_code}"
    assert settings(c) == before


@pytest.mark.parametrize("path", ["/docs", "/openapi.json", "/redoc"])
def test_inv12_docs_need_token_in_lan_mode(mk, path):
    c = mk(AIGEN_LAN="1", AIGEN_TOKEN=TOKEN)
    assert c.get(path).status_code == 401, f"{path} open without token in LAN mode"
    assert c.get(path, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200


# ---------------------------------------------------------------- invariant 13
def vsa(tag="P"):
    return fake_service_account(tag)[0]


def put_vertex(c, **over):
    body = {"projectId": "demo-proj", "location": "global", "json": vsa()}
    body.update(over)
    return c.put("/api/providers/vertex", json=body)


def providers_state(c):
    p = c.data_dir / "providers.json"
    return p.read_text() if p.exists() else ""


BAD_LOCATIONS = ["evil.example/x?", "evil.example", "a.b", "us-central1.evil.example/", "us-central1/../x",
                 "us central1", "", "GLOBAL", "us_central1", "-aiplatform.googleapis.com", "x@evil.example",
                 "us-central1#", "us-central1?x=1", "central", "us-central"]


@pytest.mark.parametrize("loc", BAD_LOCATIONS)
def test_inv13_malicious_location_rejected_and_not_stored(c, loc):
    r = put_vertex(c, location=loc)
    assert r.status_code == 400 and err_kind(r) == "invalid", (loc, r.status_code, r.text)
    assert "evil.example" not in providers_state(c)
    assert "evil.example" not in c.get("/api/providers").text


@pytest.mark.parametrize("loc", ["global", "us-central1", "europe-west4", "asia-southeast1"])
def test_inv13_valid_locations_accepted(c, loc):
    assert put_vertex(c, location=loc).status_code in (200, 201, 204)


@pytest.mark.parametrize("pid", ["A", "abcd", "1abcde", "UPPER-case-proj", "proj_with_underscore", "x" * 40,
                                 "evil.example/x", "proj-ends-dash-", "p;rm -rf"])
def test_inv13_invalid_project_id_rejected(c, pid):
    r = put_vertex(c, projectId=pid)
    assert r.status_code == 400 and err_kind(r) == "invalid", (pid, r.status_code)
    assert pid not in providers_state(c)


@pytest.mark.parametrize("bucket", ["UPPER", "a", "bad bucket", "../x", "evil.example/x?", "-start", "end-",
                                    "b" * 70, "x\ny"])
def test_inv13_invalid_gcs_bucket_rejected(c, bucket):
    r = put_vertex(c, gcsBucket=bucket)
    assert r.status_code == 400 and err_kind(r) == "invalid", (bucket, r.status_code)
    assert bucket not in providers_state(c)


def test_inv13_valid_bucket_and_project_accepted(c):
    assert put_vertex(c, projectId="my-project-123", gcsBucket="my-bucket-1").status_code in (200, 201, 204)


def test_inv13_rejected_put_keeps_previous_config(c):
    assert put_vertex(c, location="us-central1").status_code in (200, 201, 204)
    before = providers_state(c)
    assert put_vertex(c, location="evil.example/x?").status_code == 400
    assert providers_state(c) == before
    assert "us-central1" in c.get("/api/providers").text


def test_inv13_location_only_put_cannot_redirect_existing_key(c):
    """Review finding 1 attack: PUT without key but with hostile location must not be stored."""
    assert put_vertex(c).status_code in (200, 201, 204)
    r = c.put("/api/providers/vertex", json={"projectId": "demo-proj", "location": "evil.example/x?"})
    assert r.status_code == 400
    assert "evil.example" not in providers_state(c)


# ---------------------------------------------------------------- invariant 15
@pytest.fixture
def unpriced(make_client, tmp_path, c):
    """Client whose only manifest has an emptied price table (price unknown)."""
    mid = find_model(c, kind="image")
    m = copy.deepcopy(full_manifest(c, mid))
    m["pricing"]["table"] = []
    m["pricing"]["priceKey"] = None
    mdir = tmp_path / "m_unpriced"
    mdir.mkdir()
    (mdir / f"{mid}.yaml").write_text(json.dumps(m))
    c2 = make_client(data_dir=tmp_path / "d_unp", tmp_dir=tmp_path / "t_unp", AIGEN_MANIFESTS_DIR=mdir)
    c2.headers["host"] = "localhost"
    return c2, full_manifest(c2, mid)


def test_inv15_unknown_price_flags_estimate(unpriced):
    c2, m = unpriced
    for n in (1, 24):
        r = estimate(c2, make_request(m), make_sweep(n))
        assert r.status_code == 200, r.text
        b = r.json()
        assert b.get("unknownPrice") is True, b
        assert b.get("confirmRequired") is True, b


def test_inv15_unknown_price_batch_requires_confirm(unpriced):
    c2, m = unpriced
    r = post_batch(c2, make_request(m), make_sweep(1), confirm=False)
    assert r.status_code == 409 and err_kind(r) == "confirm_required", (r.status_code, r.text)
    ok = post_batch(c2, make_request(m), make_sweep(1), confirm=True)
    assert ok.status_code in (200, 201, 202), ok.text


def test_inv15_known_price_does_not_set_unknown_flag(c):
    m = img(c)
    b = estimate(c, make_request(m), make_sweep(1)).json()
    assert not b.get("unknownPrice")


# ---------------------------------------------------------------- invariant 17 (weak)
def test_inv17_invalid_constraint_text_is_not_blocked(c):
    """Demo has no hook to inject a raw provider error; best effort: a [fail] job whose prompt carries
    the 'Invalid constraint' substring must not end as blocked."""
    done, _ = run_one(c, prompt="[fail] Invalid constraint on resolution")
    j = done["jobs"][0]
    assert j["status"] != "blocked" and (j.get("error") or {}).get("kind") != "blocked"


# ---------------------------------------------------------------- invariant 20
def lan(mk):
    return mk(AIGEN_LAN="1", AIGEN_TOKEN=TOKEN)


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def session_cookie(r):
    raw = [v for k, v in r.headers.multi_items() if k.lower() == "set-cookie"]
    assert raw, "POST /api/session set no cookie"
    return raw[0]


def test_inv20_session_requires_token(mk):
    c = lan(mk)
    assert c.post("/api/session").status_code == 401
    assert c.post("/api/session", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_inv20_session_cookie_flags(mk):
    c = lan(mk)
    r = c.post("/api/session", headers=auth())
    assert r.status_code in (200, 201, 204), r.text
    ck = session_cookie(r)
    assert re.search(r"(?i)\bHttpOnly\b", ck), ck
    assert re.search(r"(?i)SameSite=Strict", ck), ck
    assert TOKEN not in ck, "cookie must be an opaque session value, not the raw token"
    assert TOKEN not in r.text


def test_inv20_assets_served_with_cookie_only(mk):
    c = lan(mk)
    up = c.post("/api/uploads", files={"file": ("a.png", PNG, "image/png")},
                data={"hasPerson": "false", "consent": "false"}, headers=auth())
    assert up.status_code in (200, 201), up.text
    a = up.json()
    a = a.get("asset", a)
    url = f"/api/assets/{a['id']}"
    assert c.get(url).status_code == 401
    ck = session_cookie(c.post("/api/session", headers=auth())).split(";")[0]
    c.cookies.clear()
    got = c.get(url, headers={"Cookie": ck})
    assert got.status_code == 200 and got.content == PNG
    rng = c.get(url, headers={"Cookie": ck, "Range": "bytes=0-3"})
    assert rng.status_code in (200, 206)
    assert c.get(url, headers={"Cookie": "aigen_session=bogus; session=bogus"}).status_code == 401


def test_inv20_cookie_does_not_authorize_writes_cross_origin(mk):
    c = lan(mk)
    ck = session_cookie(c.post("/api/session", headers=auth())).split(";")[0]
    c.cookies.clear()
    r = c.put("/api/settings", json={}, headers={"Cookie": ck, "Origin": "http://evil.example"})
    assert r.status_code in (400, 401, 403)


def test_inv20_token_never_in_urls_responses_or_logs(mk, caplog, capsys):
    import logging
    caplog.set_level(logging.DEBUG)
    c = lan(mk)
    capsys.readouterr()  # drop the startup banner (it may announce the token once, by design)
    caplog.clear()
    c.post("/api/session", headers=auth())
    up = c.post("/api/uploads", files={"file": ("a.png", PNG, "image/png")},
                data={"hasPerson": "false", "consent": "false"}, headers=auth())
    c.get("/api/manifests", headers=auth())
    c.get("/api/settings", headers=auth())
    for blob in c.seen:
        assert TOKEN.encode() not in blob, "access token echoed in a response/header"
    assert "token=" not in up.text.lower()
    out = capsys.readouterr()
    assert TOKEN not in caplog.text + out.out + out.err


def test_inv20_job_assets_do_not_carry_token_urls(mk):
    c = lan(mk)
    c.headers.update(auth())
    done, _ = run_one(c)
    assert "token=" not in json.dumps(done).lower()
    assert TOKEN not in json.dumps(done)


# ---------------------------------------------------------------- invariant 21
def test_inv21_max_jobs_per_batch_hard_limit(c):
    before = settings(c)
    for v in (65, 1000, 10**12):
        r = put_settings(c, maxJobsPerBatch=v)
        assert r.status_code == 400 and err_kind(r) == "invalid", (v, r.status_code)
    assert settings(c) == before
    assert put_settings(c, maxJobsPerBatch=64).status_code == 200
    assert settings(c)["maxJobsPerBatch"] == 64


def test_inv21_negative_threshold_rejected(c):
    before = settings(c)
    for v in (-1, -0.01):
        r = put_settings(c, confirmThresholdUsd=v)
        assert r.status_code == 400 and err_kind(r) == "invalid", (v, r.status_code)
    assert settings(c) == before
    assert put_settings(c, confirmThresholdUsd=0).status_code == 200


def test_inv21_unknown_key_rejected(c):
    before = settings(c)
    r = put_settings(c, definitelyNotASetting=1)
    assert r.status_code == 400 and err_kind(r) == "invalid"
    assert settings(c) == before
    assert "definitelyNotASetting" not in c.get("/api/settings").text


def test_inv21_documented_timeout_and_poll_keys_accepted(c):
    r = put_settings(c, jobTimeoutSeconds=600, pollIntervalSeconds=5)
    assert r.status_code == 200, r.text
    s = settings(c)
    assert s["jobTimeoutSeconds"] == 600 and s["pollIntervalSeconds"] == 5


@pytest.mark.parametrize("key,bad", [("jobTimeoutSeconds", 0), ("jobTimeoutSeconds", -5),
                                     ("pollIntervalSeconds", 0), ("pollIntervalSeconds", -1),
                                     ("maxJobsPerBatch", 0), ("maxJobsPerBatch", 2.5), ("maxAttempts", 2.5)])
def test_inv21_nonsense_values_rejected(c, key, bad):
    before = settings(c)
    r = put_settings(c, **{key: bad})
    assert r.status_code == 400, (key, bad, r.status_code)
    assert settings(c) == before


def test_inv21_batch_cap_follows_lowered_setting(c):
    m = img(c)
    assert put_settings(c, maxJobsPerBatch=2).status_code == 200
    assert post_batch(c, make_request(m), make_sweep(3)).status_code == 400
    assert post_batch(c, make_request(m), make_sweep(2)).status_code in (200, 201, 202)


# ---------------------------------------------------------------- invariant 22
def prompt_axis(c, m, vals):
    return post_batch(c, make_request(m, "base prompt"), make_sweep(1, None, {"prompt": vals}))


def test_inv22_prompt_axis_yields_distinct_prompts(c):
    m = img(c)
    r = prompt_axis(c, m, ["prompt alpha", "prompt beta", "prompt gamma"])
    assert r.status_code in (200, 201, 202), r.text
    done = wait_batch(c, r.json()["batchId"])
    jobs = done["jobs"]
    assert len(jobs) == 3
    assert sorted(j["prompt"] for j in jobs) == ["prompt alpha", "prompt beta", "prompt gamma"]
    assert sorted(j["requestedParams"]["prompt"] for j in jobs) == ["prompt alpha", "prompt beta", "prompt gamma"]
    assert sorted(j["effectiveParams"]["prompt"] for j in jobs) == ["prompt alpha", "prompt beta", "prompt gamma"]
    assert "base prompt" not in {j["prompt"] for j in jobs}


def test_inv22_prompt_axis_estimate_per_job_prompts(c):
    m = img(c)
    r = estimate(c, make_request(m, "base prompt"), make_sweep(1, None, {"prompt": ["pa", "pb"]}))
    assert r.status_code == 200
    assert {p.get("prompt") for p in r.json()["perJob"]} == {"pa", "pb"}


def test_inv22_duplicate_axis_values_do_not_create_identical_jobs(c):
    m = img(c)
    ar = pkey(m, "aspect")
    v = values_of(m, ar)[0]
    r = estimate(c, make_request(m), make_sweep(1, None, {ar: [v, v, v]}))
    if r.status_code == 400:
        return  # rejecting is acceptable
    b = r.json()
    assert b["jobCount"] == 1, f"3 identical axis values billed as {b['jobCount']} jobs"


def test_inv22_force_collapsed_axis_does_not_duplicate_paid_jobs(c):
    mid = find_model(c, kind="video", has=("veo",), lacks=("fast", "lite"))
    if not mid:
        pytest.skip("no veo manifest")
    m = full_manifest(c, mid)
    dur, res = pkey(m, "duration"), pkey(m, "resolution")
    if not (dur and res and "1080p" in values_of(m, res)):
        pytest.skip("veo manifest lacks duration/1080p")
    durs = [d for d in values_of(m, dur)]
    assert len(durs) >= 2
    req = make_request(m, params={res: "1080p"})
    r = estimate(c, req, make_sweep(1, None, {dur: durs}))
    if r.status_code == 400:
        return
    b = r.json()
    # Under 1080p the duration is forced (review finding 11): jobs differing only in a forced axis are identical.
    r2 = post_batch(c, req, make_sweep(1, None, {dur: durs}))
    assert r2.status_code in (200, 201, 202), r2.text
    jobs = r2.json()["jobs"]
    sigs = [json.dumps({k: v for k, v in j["effectiveParams"].items()}, sort_keys=True) for j in jobs]
    assert len(set(sigs)) == len(sigs), "identical paid jobs created from a force-collapsed axis"
    assert b["jobCount"] == len(jobs)
    for j in jobs:
        c.post(f"/api/batches/{r2.json()['batchId']}/cancel")
        break


def test_inv22_huge_axis_product_rejected_fast(c):
    m = img(c)
    seed = pkey(m, "seed")
    prompts = [f"p{i}" for i in range(2000)]
    axes = {seed: list(range(2000))} if seed else {}
    if not axes:
        pytest.skip("no seed param to build a second axis")
    for fn in ("estimate", "batches"):
        t0 = time.time()
        sweep = make_sweep(1, prompts, axes)
        r = estimate(c, make_request(m), sweep) if fn == "estimate" else post_batch(c, make_request(m), sweep)
        dt = time.time() - t0
        assert r.status_code == 400 and err_kind(r) == "invalid", (fn, r.status_code)
        assert dt < 1.5, f"{fn}: cap check took {dt:.2f}s for 4M-combination sweep (product expanded before cap?)"


def test_inv22_absurd_n_rejected_fast(c):
    m = img(c)
    t0 = time.time()
    r = estimate(c, make_request(m), make_sweep(10**12))
    assert r.status_code == 400 and time.time() - t0 < 1.5


# ---------------------------------------------------------------- invariant 23
def walk(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk(v, f"{path}[{i}]")
    else:
        yield path, o


def assert_no_paths(c, obj, label):
    roots = {str(c.tmp_dir), str(c.data_dir), str(c.tmp_dir.resolve()), str(c.data_dir.resolve())}
    for p, v in walk(obj):
        assert not p.endswith(".path"), f"{label}: Asset.path exposed at {p}"
        if isinstance(v, str):
            assert not any(r in v for r in roots), f"{label}: absolute server path at {p}: {v}"


def test_inv23_no_absolute_paths_in_job_batch_upload_json(c):
    done, _ = run_one(c)
    assert has_asset_ids(done), "demo job produced no assets"
    assert_no_paths(c, done, "batch")
    jid = done["jobs"][0]["id"]
    r = c.get(f"/api/jobs/{jid}")
    if r.status_code == 200:
        assert_no_paths(c, r.json(), "job")
    up = c.post("/api/uploads", files={"file": ("a.png", PNG, "image/png")},
                data={"hasPerson": "false", "consent": "false"})
    assert up.status_code in (200, 201)
    assert_no_paths(c, up.json(), "upload")
    for blob in c.seen:
        assert str(c.tmp_dir).encode() not in blob, "tmp path in some response"


def test_inv23_no_absolute_paths_in_sse(c):
    done, _ = run_one(c)
    r = c.get("/api/events")  # review: finite snapshot for non-SSE clients
    assert r.status_code == 200
    assert str(c.tmp_dir) not in r.text and '"path"' not in r.text


def test_inv23_retry_reapplies_confirm_gate(c):
    m = img(c)
    assert put_settings(c, confirmThresholdUsd=0.01).status_code == 200
    r = post_batch(c, make_request(m, "[fail] x"), make_sweep(1), confirm=True)
    assert r.status_code in (200, 201, 202), r.text
    done = wait_batch(c, r.json()["batchId"])
    j = done["jobs"][0]
    assert j["status"] == "failed"
    rr = c.post(f"/api/jobs/{j['id']}/retry")
    assert rr.status_code == 409 and err_kind(rr) == "confirm_required", (rr.status_code, rr.text)


def test_inv23_retry_reapplies_unknown_price_gate(unpriced):
    c2, m = unpriced
    r = post_batch(c2, make_request(m, "[fail] x"), make_sweep(1), confirm=True)
    assert r.status_code in (200, 201, 202), r.text
    j = wait_batch(c2, r.json()["batchId"])["jobs"][0]
    rr = c2.post(f"/api/jobs/{j['id']}/retry")
    assert rr.status_code == 409 and err_kind(rr) == "confirm_required", (rr.status_code, rr.text)


def test_inv23_retry_reapplies_batch_cap(c):
    m = img(c)
    r = post_batch(c, make_request(m, "[fail] x"), make_sweep(4), confirm=True)
    assert r.status_code in (200, 201, 202), r.text
    done = wait_batch(c, r.json()["batchId"])
    assert put_settings(c, maxJobsPerBatch=1).status_code == 200
    j = done["jobs"][0]
    rr = c.post(f"/api/jobs/{j['id']}/retry")
    # batch already holds 4 jobs > cap 1: adding a retry must not silently exceed the cap
    assert rr.status_code == 400 and err_kind(rr) == "invalid", (rr.status_code, rr.text)
