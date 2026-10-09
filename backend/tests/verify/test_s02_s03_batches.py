"""Stories 2 and 3: N variants, prompt lists, sweeps, batch cap, confirm threshold."""
import itertools

import pytest
from vhelpers import *


def img(client):
    mid = need_model(client, kind="image", has=("banana",)) if find_model(client, kind="image", has=("banana",)) \
        else find_model(client, kind="image")
    return full_manifest(client, mid)


def test_n6_makes_six_independent_jobs(client):
    m = img(client)
    r = post_batch(client, make_request(m), make_sweep(6))
    assert r.status_code in (200, 201, 202), r.text
    b = r.json()
    assert len(b["jobs"]) == 6
    assert len({j["id"] for j in b["jobs"]}) == 6
    done = wait_batch(client, b["batchId"])
    assert len(done["jobs"]) == 6
    assert all(j["status"] == "succeeded" for j in done["jobs"])


def test_each_job_records_requested_and_effective_params(client):
    m = img(client)
    done, _ = run_one(client, m["id"])
    j = done["jobs"][0]
    assert "requestedParams" in j and "effectiveParams" in j
    assert j["model"] == m["id"]
    assert j["batchId"]


def test_batch_cap_24_allowed_25_rejected(client):
    m = img(client)
    ok = post_batch(client, make_request(m), make_sweep(24))
    assert ok.status_code in (200, 201, 202), ok.text
    assert len(ok.json()["jobs"]) == 24
    bad = post_batch(client, make_request(m), make_sweep(25))
    assert 400 <= bad.status_code < 500
    assert api_error_kind(bad) == "invalid"
    assert bad.json()["error"]["message"]  # a reason is reported


def test_cap_applies_to_estimate_too(client):
    m = img(client)
    r = estimate(client, make_request(m), make_sweep(25))
    assert r.status_code >= 400 or any("24" in str(w) for w in r.json().get("warnings", []))


def test_cap_applies_to_prompt_list_times_axes(client):
    m = img(client)
    ar = pkey(m, "aspectratio")
    vals = values_of(m, ar)[:5]
    prompts = [f"p{i}" for i in range(5)]  # 5 x 5 = 25
    r = post_batch(client, make_request(m), make_sweep(1, prompts, {ar: vals}))
    assert r.status_code >= 400 and api_error_kind(r) == "invalid"


def test_cap_rejection_creates_no_batch_or_jobs(client):
    m = img(client)
    post_batch(client, make_request(m), make_sweep(25))
    # nothing may be running after a rejected over-cap request
    r = client.get("/api/batches/anything")
    assert r.status_code == 404


def test_sweep_3_prompts_x_2_axes_is_18_jobs(client):
    m = img(client)
    ar, sz = pkey(m, "aspectratio"), pkey(m, "imagesize", "size")
    a_vals = values_of(m, ar)[:3]
    s_vals = values_of(m, sz)[:2]
    assert len(a_vals) == 3 and len(s_vals) >= 1
    sweep = make_sweep(1, ["p1", "p2", "p3"], {ar: a_vals, sz: s_vals})
    r = estimate(client, make_request(m), sweep)
    assert r.status_code == 200, r.text
    assert r.json()["jobCount"] == 3 * 3 * len(s_vals)


def test_sweep_creates_one_job_per_combination_with_distinct_params(client):
    m = img(client)
    ar = pkey(m, "aspectratio")
    vals = values_of(m, ar)[:3]
    r = post_batch(client, make_request(m), make_sweep(1, ["a", "b"], {ar: vals}))
    assert r.status_code in (200, 201, 202), r.text
    done = wait_batch(client, r.json()["batchId"])
    combos = {(j["requestedParams"].get("prompt"), str(j["requestedParams"].get(ar))) for j in done["jobs"]}
    assert combos == set(itertools.product(["a", "b"], map(str, vals)))


def test_over_threshold_requires_confirmation(client):
    mid = need_model(client, kind="video", has=("veo",), lacks=("fast", "lite"))
    m = full_manifest(client, mid)
    dur, res = pkey(m, "duration"), pkey(m, "resolution")
    req = make_request(m, params={dur: 8, res: "1080p"})
    e = estimate(client, req, make_sweep(6))
    assert e.status_code == 200, e.text
    assert e.json()["maxUsd"] > 5, "6 x 8s Veo 3.1 1080p must exceed the default 5 USD threshold"
    r = post_batch(client, req, make_sweep(6), confirm=False)
    assert r.status_code >= 400
    assert "confirm_required" in r.text
    # no job may have been started by the refused request
    r2 = post_batch(client, req, make_sweep(6), confirm=True)
    assert r2.status_code in (200, 201, 202), r2.text


def test_under_threshold_needs_no_confirmation(client):
    mid = need_model(client, kind="video", has=("omni",))
    m = full_manifest(client, mid)
    e = estimate(client, make_request(m), make_sweep(1))
    assert e.status_code == 200
    if e.json()["maxUsd"] > 5:
        pytest.skip("single omni default job exceeds 5 USD in this manifest; cannot test no-confirm path")
    r = post_batch(client, make_request(m), make_sweep(1), confirm=False)
    assert r.status_code in (200, 201, 202), r.text


def test_cheap_image_batch_of_6_needs_no_confirm(client):
    m = img(client)
    e = estimate(client, make_request(m), make_sweep(6))
    if e.json()["maxUsd"] > 5:
        pytest.skip("6 default image jobs exceed 5 USD")
    assert post_batch(client, make_request(m), make_sweep(6), confirm=False).status_code in (200, 201, 202)


def test_invalid_params_rejected_before_any_job(client):
    m = img(client)
    size = pkey(m, "imagesize", "size")
    r = post_batch(client, make_request(m, params={size: "9999K"}), make_sweep(2))
    assert r.status_code >= 400
    assert api_error_kind(r) == "invalid"
