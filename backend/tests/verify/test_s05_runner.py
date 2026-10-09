"""Story 5 job runner: retry policy, blocked/invalid never retried, cancel, downloads to temp."""
import hashlib
import os
import time

from vhelpers import *


def img_model(client):
    return full_manifest(client, find_model(client, kind="image"))


def test_quota_then_success(client):
    done, _ = run_one(client, prompt="[quota] a cat")
    j = done["jobs"][0]
    assert j["status"] == "succeeded", j


def test_blocked_is_normalized_and_not_retried(client):
    done, _ = run_one(client, prompt="[blocked] something")
    j = done["jobs"][0]
    assert j["status"] == "blocked"
    assert j["error"]["kind"] == "blocked" and j["error"]["message"]
    time.sleep(1.5)  # a hidden retry would flip it or add attempts
    again = client.get(f"/api/batches/{done['batchId'] if 'batchId' in done else j['batchId']}").json()["jobs"][0]
    assert again["status"] == "blocked"
    for k in ("attempts", "attempt", "tries"):
        if k in again:
            assert again[k] <= 1, f"blocked job was retried ({k}={again[k]})"


def test_invalid_is_failed_not_retried(client):
    done, _ = run_one(client, prompt="[fail] x")
    j = done["jobs"][0]
    assert j["status"] == "failed"
    assert j["error"]["kind"] == "invalid" and j["error"]["message"]
    time.sleep(1.0)
    again = client.get(f"/api/batches/{j['batchId']}").json()["jobs"][0]
    assert again["status"] == "failed"
    for k in ("attempts", "attempt", "tries"):
        if k in again:
            assert again[k] <= 1


def test_mixed_batch_isolates_failures(client):
    m = img_model(client)
    r = post_batch(client, make_request(m), make_sweep(1, ["ok one", "[blocked] b", "[fail] f", "ok two"]))
    assert r.status_code in (200, 201, 202), r.text
    done = wait_batch(client, r.json()["batchId"])
    by = {j["requestedParams"]["prompt"]: j["status"] for j in done["jobs"]}
    assert by == {"ok one": "succeeded", "[blocked] b": "blocked", "[fail] f": "failed", "ok two": "succeeded"}


def test_retry_only_applies_to_failed_jobs(client):
    done, _ = run_one(client, prompt="fine")
    ok = done["jobs"][0]
    r = client.post(f"/api/jobs/{ok['id']}/retry")
    assert 400 <= r.status_code < 500, "retrying a succeeded job must be rejected"


def test_manual_retry_of_failed_job_creates_new_job(client):
    done, _ = run_one(client, prompt="[fail] x")
    bad = done["jobs"][0]
    r = client.post(f"/api/jobs/{bad['id']}/retry")
    assert r.status_code in (200, 201, 202), r.text
    new = r.json()
    new = new.get("job", new)
    assert new["id"] != bad["id"]
    assert new["requestedParams"] == bad["requestedParams"]


def test_retry_unknown_job_404(client):
    r = client.post("/api/jobs/nope/retry")
    assert r.status_code == 404 and api_error_kind(r) == "not_found"


def test_success_downloads_file_to_temp_immediately(client):
    done, _ = run_one(client)
    j = done["jobs"][0]
    a = j["assets"][0]
    assert a["mime"].startswith(("image/", "video/"))
    assert len(a["sha256"]) == 64
    r = client.get(f"/api/assets/{a['id']}")
    assert r.status_code == 200
    assert hashlib.sha256(r.content).hexdigest() == a["sha256"]
    files = [os.path.join(d, f) for d, _, fs in os.walk(client.tmp_dir) for f in fs]
    assert files, "asset must be stored under AIGEN_TMP_DIR"
    assert not a.get("url", "").startswith("http"), "no provider URL may be kept"


def test_asset_range_request(client):
    done, _ = run_one(client)
    a = done["jobs"][0]["assets"][0]
    full = client.get(f"/api/assets/{a['id']}").content
    r = client.get(f"/api/assets/{a['id']}", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206
    assert r.content == full[:10]


def test_unknown_asset_404(client):
    r = client.get("/api/assets/nope")
    assert r.status_code == 404 and api_error_kind(r) == "not_found"


def test_cancel_batch_cancels_unsent_jobs_and_settles(slow_client):
    c = slow_client
    m = img_model(c)
    r = post_batch(c, make_request(m), make_sweep(24))
    assert r.status_code in (200, 201, 202), r.text
    bid = r.json()["batchId"]
    cr = c.post(f"/api/batches/{bid}/cancel")
    assert cr.status_code == 200, cr.text
    done = wait_batch(c, bid, timeout=90)
    st = [j["status"] for j in done["jobs"]]
    assert "canceled" in st, f"no queued job was canceled: {st}"
    assert set(st) <= {"succeeded", "canceled", "failed"}  # sent ones may finish (best-effort)
    # canceled stays canceled
    time.sleep(1.0)
    later = [j["status"] for j in c.get(f"/api/batches/{bid}").json()["jobs"]]
    assert later == st


def test_cancel_does_not_touch_other_batches(slow_client):
    c = slow_client
    m = img_model(c)
    a = post_batch(c, make_request(m), make_sweep(24)).json()["batchId"]
    b = post_batch(c, make_request(m), make_sweep(2)).json()["batchId"]
    c.post(f"/api/batches/{a}/cancel")
    done_b = wait_batch(c, b, timeout=90)
    assert all(j["status"] == "succeeded" for j in done_b["jobs"])


def test_cancel_unknown_batch_404(client):
    r = client.post("/api/batches/nope/cancel")
    assert r.status_code == 404


def test_cancel_finished_batch_is_harmless(client):
    done, _ = run_one(client)
    bid = done["jobs"][0]["batchId"]
    r = client.post(f"/api/batches/{bid}/cancel")
    assert r.status_code == 200
    again = client.get(f"/api/batches/{bid}").json()["jobs"]
    assert [j["status"] for j in again] == ["succeeded"]


def test_events_stream_endpoint_exists(client):
    with client.stream("GET", "/api/events") as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
