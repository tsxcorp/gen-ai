"""Unit tests for invariants 12-23 (docs/architecture.md, review-v1). Demo mode / fake adapters only."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import time

import pytest
from fastapi.testclient import TestClient

from app.adapters.base import OutputRef, PollResult, SubmitHandle, redact_payload, write_outputs
from app.adapters.demo import DemoAdapter, make_png
from app.adapters.vertex_common import (
    VertexClient,
    VertexConfig,
    assert_google_url,
    host,
    normalize_error,
    valid_bucket,
    valid_location,
    valid_project,
)
from app.adapters.vertex_image import parse_generate_content
from app.adapters.vertex_veo import parse_operation
from app.core import constraints
from app.core.cost import estimate_job_ex
from app.core.events import EventHub
from app.core.expand import expand, expand_with_warnings
from app.core.jobs import JobManager
from app.core.storage import Storage, sweep_stale_runs
from app.errors import AdapterError, ApiError
from app.main import create_app
from app.schemas import Constraint, GenerationRequest, InputAsset, Sweep

PNG = make_png(8, 8, "x")
TOKEN = "tok-unit-hardening"
JSON = {"content-type": "application/json"}


# ------------------------------------------------------------------ guard middleware (12, 20)
@pytest.fixture()
def app_client(dirs):
    def make(lan=False, demo=True, **kw):
        app = create_app(demo=demo, lan=lan, token=TOKEN if lan else None, **dirs, **kw)
        c = TestClient(app)
        c.ctx = app.state.ctx
        c.headers["host"] = "localhost"
        return c

    return make


def test_foreign_host_rejected_and_loopback_allowed(app_client):
    c = app_client()
    for h in ("evil.example", "evil.example:8000", "localhost.evil.example", "127.0.0.1.evil.example"):
        assert c.get("/api/manifests", headers={"host": h}).status_code == 403, h
    for h in ("localhost", "localhost:5173", "127.0.0.1:8000", "[::1]", "[::1]:8000"):
        assert c.get("/api/manifests", headers={"host": h}).status_code == 200, h


def test_testserver_host_only_in_demo(app_client):
    assert app_client(demo=True).get("/api/health", headers={"host": "testserver"}).status_code == 200
    assert app_client(demo=False).get("/api/health", headers={"host": "testserver"}).status_code == 403


def test_lan_allows_ip_literal_hosts_not_names(app_client):
    c = app_client(lan=True)
    h = {"Authorization": f"Bearer {TOKEN}"}
    assert c.get("/api/manifests", headers={**h, "host": "192.168.1.20:8000"}).status_code == 200
    assert c.get("/api/manifests", headers={**h, "host": "rebind.example:8000"}).status_code == 403


def test_cross_origin_write_rejected_same_origin_ok(app_client):
    c = app_client()
    s = c.get("/api/settings").json()
    assert c.put("/api/settings", json=s, headers={"origin": "http://evil.example"}).status_code == 403
    assert c.put("/api/settings", json=s, headers={"origin": "null"}).status_code == 403
    assert c.put("/api/settings", json=s, headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert c.put("/api/settings", json=s, headers={"origin": "http://localhost:5173"}).status_code == 200
    assert c.put("/api/settings", json=s).status_code == 200
    assert c.post("/api/providers/vertex/test", headers={"origin": "http://evil.example"}).status_code == 403


def test_json_content_type_required_for_bodies(app_client):
    c = app_client()
    before = c.get("/api/settings").json()
    for ct in ("text/plain", "application/x-www-form-urlencoded", None):
        r = c.request("PUT", "/api/settings", content=b'{"confirmThresholdUsd": 1}',
                      headers={"content-type": ct} if ct else {"content-type": ""})
        assert r.status_code == 415, ct
    assert c.get("/api/settings").json() == before
    assert c.post("/api/batches/zzz/cancel").status_code == 404  # body-less POST needs no content type


def test_lan_docs_need_token_and_query_token_is_dead(app_client):
    c = app_client(lan=True)
    for path in ("/docs", "/openapi.json", "/redoc"):
        assert c.get(path).status_code == 401
        assert c.get(path, headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200
    assert c.get(f"/api/manifests?token={TOKEN}").status_code == 401
    assert c.get("/api/health").status_code == 200


def test_session_cookie_serves_assets_only(app_client):
    c = app_client(lan=True)
    auth = {"Authorization": f"Bearer {TOKEN}"}
    assert c.post("/api/session").status_code == 401
    up = c.post("/api/uploads", files={"file": ("a.png", PNG, "image/png")},
                data={"hasPerson": "false", "consent": "false"}, headers=auth)
    assert up.status_code == 200 and "path" not in up.json()
    aid = up.json()["id"]
    r = c.post("/api/session", headers=auth)
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and TOKEN not in cookie
    ck = {"Cookie": cookie.split(";")[0]}
    c.cookies.clear()
    assert c.get(f"/api/assets/{aid}").status_code == 401
    assert c.get(f"/api/assets/{aid}", headers=ck).content == PNG
    assert c.get("/api/events", headers=ck).status_code == 200
    assert c.get("/api/settings", headers=ck).status_code == 401  # cookie is not a general credential
    assert c.post("/api/zip", json={"assetIds": [aid]}, headers=ck).status_code == 401
    assert c.get(f"/api/assets/{aid}", headers={"Cookie": "aigen_session=bogus"}).status_code == 401


def test_oversize_upload_rejected_while_streaming(app_client, dirs):
    c = app_client()
    big = PNG + b"\0" * (23 * 1024 * 1024)
    r = c.post("/api/uploads", files={"file": ("a.png", big, "image/png")},
               data={"hasPerson": "false", "consent": "false"})
    assert r.status_code in (400, 413)
    assert [p for p in c.ctx.storage.run_dir.iterdir()] == []
    mid = PNG + b"\0" * (20 * 1024 * 1024 + 100_000)  # inside the multipart slack but over the file limit
    r = c.post("/api/uploads", files={"file": ("a.png", mid, "image/png")},
               data={"hasPerson": "false", "consent": "false"})
    assert r.status_code == 400 and "too large" in r.text
    assert [p for p in c.ctx.storage.run_dir.iterdir()] == []


def test_access_log_filter_strips_query():
    import logging

    from app.main import _StripQuery

    rec = logging.LogRecord("uvicorn.access", 20, "", 0, '%s - "%s %s HTTP/%s" %d',
                            ("1.2.3.4", "GET", "/api/x?token=secret", "1.1", 200), None)
    _StripQuery().filter(rec)
    assert "secret" not in rec.getMessage()


# ------------------------------------------------------------------ vertex fields (13)
@pytest.mark.parametrize("loc,ok", [("global", True), ("us-central1", True), ("europe-west4", True),
                                    ("evil.example/x?", False), ("GLOBAL", False), ("us-central", False),
                                    ("", False), ("a b", False), ("us-central1.evil.example", False)])
def test_location_shape(loc, ok):
    assert valid_location(loc) is ok


def test_project_and_bucket_shape():
    assert valid_project("my-project-123") and not valid_project("abcd") and not valid_project("UPPER-case1")
    assert valid_bucket("my-bucket_1") and not valid_bucket("a") and not valid_bucket("-bad") and not valid_bucket("1.2.3.4")
    assert not valid_bucket("a..b")


def test_host_and_google_guard():
    assert host("global") == "aiplatform.googleapis.com"
    assert host("us-central1") == "us-central1-aiplatform.googleapis.com"
    with pytest.raises(AdapterError):
        host("evil.example/x?")
    assert_google_url("https://us-central1-aiplatform.googleapis.com/v1/x")
    assert_google_url("https://storage.googleapis.com/storage/v1/b/x")
    for bad in ("http://aiplatform.googleapis.com/x", "https://evil.example/x", "https://googleapis.com.evil.example/",
                "https://u:p@aiplatform.googleapis.com/x", "https://evilgoogleapis.com/"):
        with pytest.raises(AdapterError):
            assert_google_url(bad)


async def test_client_never_sends_token_to_foreign_host():
    class Boom(VertexClient):
        async def token(self):  # must not even be asked for a token
            raise AssertionError("token requested for foreign host")

    with pytest.raises(AdapterError):
        await Boom(VertexConfig(project_id="proj-test-1")).request("POST", "https://evil.example/x", {})


def test_from_providers_rejects_hand_edited_location():
    with pytest.raises(ApiError):
        VertexConfig.from_providers({"projectId": "proj-test-1", "location": "evil.example/x?",
                                     "serviceAccountJson": {"a": 1}})


def test_providers_put_rejects_bad_fields(client):
    key = {"type": "service_account", "client_email": "a@b.c", "private_key": "K"}
    base = {"json": key, "projectId": "proj-test-1", "location": "global"}
    for over in ({"location": "evil.example/x?"}, {"location": ""}, {"projectId": "abc"}, {"gcsBucket": "Bad Bucket"}):
        r = client.put("/api/providers/vertex", json={**base, **over})
        assert r.status_code == 400, over
    assert client.get("/api/providers").json()["vertex"]["hasKey"] is False
    assert client.put("/api/providers/vertex", json={**base, "gcsBucket": "my-bucket-1"}).status_code == 200
    # one error message for every bad serviceAccountPath (no existence/shape oracle)
    msgs = {client.put("/api/providers/vertex", json={"serviceAccountPath": p, "projectId": "proj-test-1"}).text
            for p in ("/nonexistent/x.json", "/etc/hosts", "/etc/passwd")}
    assert len(msgs) == 1


# ------------------------------------------------------------------ blocked classification (7, 17, 12)
def test_blocked_only_from_structured_fields():
    assert normalize_error(400, {"error": {"message": "Invalid constraint on resolution"}}).kind == "invalid"
    for word in ("training", "Australia", "afraid", "policy violation", "RAI", "filtered"):
        assert normalize_error(400, {"error": {"message": word}}).kind == "invalid"
    assert normalize_error(400, {"error": {"details": [{"reason": "SAFETY"}]}}).kind == "blocked"
    assert normalize_error(400, {"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}}).kind == "blocked"
    assert normalize_error(400, {"raiMediaFilteredCount": 1}).kind == "blocked"


@pytest.mark.parametrize("code", [13, 14, 9, 2, 99, None])
def test_unrecognised_operation_error_code_is_not_resubmittable(code):
    r = parse_operation({"done": True, "error": {"code": code, "message": "boom"}})
    assert r.state == "failed" and r.error.kind == "invalid" and not r.error.before_send


def test_recognised_operation_codes_still_map():
    assert parse_operation({"done": True, "error": {"code": 8, "message": "q"}}).error.kind == "quota"
    assert parse_operation({"done": True, "error": {"code": 4, "message": "t"}}).error.kind == "timeout"


# ------------------------------------------------------------------ outputs (5, 6, 18, 19)
def test_veo_partial_group_warns():
    vid = base64.b64encode(b"mp4").decode()
    r = parse_operation({"done": True, "response": {"videos": [{"bytesBase64Encoded": vid}],
                                                    "raiMediaFilteredCount": 3, "raiMediaFilteredReasons": ["r1"]}})
    assert r.state == "done" and len(r.outputs) == 1 and r.outputs[0].data == b"mp4"
    assert any("raiMediaFilteredCount=3" in w for w in r.warnings)
    full = parse_operation({"done": True, "response": {"videos": [{"gcsUri": "gs://b/o.mp4"}]}})
    assert full.warnings == []


def test_thought_images_never_collected():
    png = base64.b64encode(PNG).decode()
    thought = {"thought": True, "inlineData": {"mimeType": "image/png", "data": base64.b64encode(b"draft").decode()}}
    real = {"inlineData": {"mimeType": "image/png", "data": png}}
    outs = parse_generate_content({"candidates": [{"content": {"parts": [thought, real, thought]}}]})
    assert [o.data for o in outs] == [PNG]
    with pytest.raises(AdapterError) as e:
        parse_generate_content({"candidates": [{"finishReason": "STOP", "content": {"parts": [thought]}}]})
    assert e.value.kind == "invalid"


async def test_write_outputs_streams_and_hashes(tmp_path):
    big = b"v" * 5_000_000
    b64 = base64.b64encode(big).decode()
    from app.adapters.base import inline_output

    ref = inline_output("video/mp4", b64)
    assert ref.data is None and ref.b64 is not None  # too big to hold decoded
    small = inline_output("video/mp4", base64.b64encode(b"abc").decode())
    assert small.data == b"abc"
    files = await write_outputs([ref, small], tmp_path)
    assert files[0].path.read_bytes() == big
    assert files[0].sha256 == hashlib.sha256(big).hexdigest() and files[0].size_bytes == len(big)
    assert files[1].sha256 == hashlib.sha256(b"abc").hexdigest()


async def test_write_outputs_uri_uses_fetch_and_cleans_up_on_failure(tmp_path):
    async def fetch(uri, path):
        path.write_bytes(b"streamed")
        return 8, hashlib.sha256(b"streamed").hexdigest()

    ok = await write_outputs([OutputRef("video/mp4", uri="gs://b/o")], tmp_path, fetch)
    assert ok[0].path.read_bytes() == b"streamed"

    async def boom(uri, path):
        raise AdapterError("network", "x")

    before = set(tmp_path.iterdir())
    with pytest.raises(AdapterError):
        await write_outputs([OutputRef("video/mp4", data=b"first"), OutputRef("video/mp4", uri="gs://b/o")],
                            tmp_path, boom)
    assert set(tmp_path.iterdir()) == before  # all-or-nothing


def test_asset_path_never_serialised(client):
    r = client.post("/api/batches", json={"request": {"modelId": "nano-banana-2.1", "prompt": "x"}}).json()
    deadline = time.time() + 10
    while time.time() < deadline:
        b = client.get(f"/api/batches/{r['batchId']}").json()
        if all(j["status"] == "succeeded" for j in b["jobs"]):
            break
        time.sleep(0.05)
    assert b["jobs"][0]["assets"] and "path" not in b["jobs"][0]["assets"][0]
    assert str(client.ctx.tmp_dir) not in client.get("/api/events").text
    assert str(client.ctx.tmp_dir) not in str(b)


# ------------------------------------------------------------------ runner (14, 8, 23)
class Fake(DemoAdapter):
    """Adapter with a scripted submit / poll / download."""

    poll_interval_s = 0.0

    def __init__(self, m, submit=None, polls=None, download_errors=None, outputs=1):
        super().__init__(m)
        self.submit_calls = self.poll_calls = self.download_calls = 0
        self._submit, self._polls = list(submit or []), list(polls or [])
        self._dl = list(download_errors or [])
        self.n_out = outputs
        self.seen_inputs: list[int] = []

    async def submit(self, job):
        self.submit_calls += 1
        self.seen_inputs.append(sum(len(v) for v in job.inputs.values()))
        if self._submit and (step := self._submit.pop(0)):
            raise step
        return SubmitHandle(id="operations/op-123", data={})

    async def poll(self, handle):
        self.poll_calls += 1
        if self._polls:
            step = self._polls.pop(0)
            if isinstance(step, Exception):
                raise step
            if step is not None:
                return step
        return PollResult(state="done", outputs=[OutputRef("image/png", PNG) for _ in range(self.n_out)])

    async def download(self, outputs, dest):
        self.download_calls += 1
        if self._dl and (step := self._dl.pop(0)):
            raise step
        return await write_outputs(outputs, dest)


SET = {"maxAttempts": 4, "retryBaseSeconds": 0.005, "retryMaxSeconds": 0.01, "jobTimeoutSeconds": 5,
       "pollIntervalSeconds": 0.01, "maxJobsPerBatch": 24, "confirmThresholdUsd": 5, "staleDays": 30}


def mgr_for(manifests, tmp_path, ad, settings=None, prices=None):
    s = {**SET, **(settings or {})}
    return JobManager(manifests, Storage(tmp_path), EventHub(), lambda _m: ad, lambda: dict(s), prices)


def run_batch(m, mgr, n=1, prompt="p", model_kw=None):
    jobs = expand(m, GenerationRequest(model_id=m.id, prompt=prompt, **(model_kw or {})), Sweep(variants=n), 64)
    return mgr.create_batch(jobs, {}, False, jobs[0].batch_id)


async def test_poll_network_error_retries_poll_never_resubmits(manifests, tmp_path):
    m = manifests["veo-3.1"]
    ad = Fake(m, polls=[AdapterError("network", "blip"), AdapterError("timeout", "slow"), None])
    mgr = mgr_for(manifests, tmp_path, ad)
    j = (await mgr.wait_batch(run_batch(m, mgr).id)).jobs[0]
    assert j.status == "succeeded" and ad.submit_calls == 1 and ad.poll_calls == 3
    assert j.operation_id == "operations/op-123" and j.attempts == 1


async def test_poll_errors_exhausted_fail_without_resubmit(manifests, tmp_path):
    m = manifests["veo-3.1"]
    ad = Fake(m, polls=[AdapterError("network", "down")] * 50)
    mgr = mgr_for(manifests, tmp_path, ad)
    j = (await mgr.wait_batch(run_batch(m, mgr).id)).jobs[0]
    assert j.status == "failed" and ad.submit_calls == 1
    assert "operations/op-123" in j.error.message


async def test_poll_timeout_fails_with_operation_id(manifests, tmp_path):
    m = manifests["veo-3.1"]
    ad = Fake(m, polls=[PollResult(state="running")] * 1000)
    ad.poll_interval_s = None  # use settings.pollIntervalSeconds (invariant 21)
    mgr = mgr_for(manifests, tmp_path, ad, {"jobTimeoutSeconds": 0.2, "pollIntervalSeconds": 0.02})
    t0 = time.monotonic()
    j = (await mgr.wait_batch(run_batch(m, mgr).id)).jobs[0]
    assert j.status == "failed" and j.error.kind == "timeout" and "operations/op-123" in j.error.message
    assert ad.submit_calls == 1 and 0.15 < time.monotonic() - t0 < 3
    assert 3 <= ad.poll_calls <= 40  # polled at the configured interval, not the adapter's 15 s


async def test_failed_operation_after_submit_is_not_resubmitted_even_for_quota(manifests, tmp_path):
    m = manifests["veo-3.1"]
    ad = Fake(m, polls=[PollResult(state="failed", error=AdapterError("quota", "q"))])
    mgr = mgr_for(manifests, tmp_path, ad)
    j = (await mgr.wait_batch(run_batch(m, mgr).id)).jobs[0]
    assert j.status == "failed" and j.error.kind == "quota" and ad.submit_calls == 1


async def test_blocked_after_submit_is_blocked(manifests, tmp_path):
    m = manifests["veo-3.1"]
    ad = Fake(m, polls=[PollResult(state="failed", error=AdapterError("blocked", "rai"))])
    mgr = mgr_for(manifests, tmp_path, ad)
    j = (await mgr.wait_batch(run_batch(m, mgr).id)).jobs[0]
    assert j.status == "blocked" and ad.submit_calls == 1


async def test_download_error_retries_download_only(manifests, tmp_path):
    m = manifests["veo-3.1"]
    ad = Fake(m, download_errors=[AdapterError("network", "reset")])
    mgr = mgr_for(manifests, tmp_path, ad)
    j = (await mgr.wait_batch(run_batch(m, mgr).id)).jobs[0]
    assert j.status == "succeeded" and ad.submit_calls == 1 and ad.download_calls == 2


async def test_submit_quota_still_retried_and_inputs_freed(manifests, tmp_path):
    m = manifests["veo-3.1"]
    ad = Fake(m, submit=[AdapterError("quota", "429")])
    mgr = mgr_for(manifests, tmp_path, ad)
    up = mgr.storage.save_bytes(PNG, "image/png", "upload")
    jobs = expand(m, GenerationRequest(model_id=m.id, mode="i2v", prompt="p", assets={"first_frame": up.id}), None, 24)
    b = mgr.create_batch(jobs, {}, False, jobs[0].batch_id)
    j = (await mgr.wait_batch(b.id)).jobs[0]
    assert j.status == "succeeded" and ad.submit_calls == 2 and ad.seen_inputs == [1, 1]
    assert j.inputs == {}  # reference bytes released once the request was sent


async def test_group_with_fewer_outputs_gets_warning(manifests, tmp_path):
    m = manifests["veo-3.1"]
    ad = Fake(m, outputs=2)
    ad.m = m
    mgr = mgr_for(manifests, tmp_path, ad)
    jobs = expand(m, GenerationRequest(model_id=m.id, prompt="p"), Sweep(variants=4), 24)
    assert jobs[0].variant_count == 4
    j = (await mgr.wait_batch(mgr.create_batch(jobs, {}, False, jobs[0].batch_id).id)).jobs[0]
    assert j.status == "succeeded" and len(j.assets) == 2
    assert any("2 of 4" in w for w in j.warnings)


async def test_retry_reapplies_cap_and_cost_gate(manifests, tmp_path):
    m = manifests["nano-banana-2.1"]
    prices = {"entries": {m.id: {"lastVerified": "2026-10-07"}}}
    ad = Fake(m, submit=[AdapterError("invalid", "x")] * 3)
    mgr = mgr_for(manifests, tmp_path, ad, {"maxJobsPerBatch": 3}, lambda: prices)
    b = await mgr.wait_batch(run_batch(m, mgr, 3).id)
    assert [j.status for j in b.jobs] == ["failed"] * 3
    new = mgr.retry_job(b.jobs[0].id)  # replaces the failed job inside a full batch: allowed
    assert new.retry_of == b.jobs[0].id
    await mgr.wait_batch(b.id)
    mgr2 = mgr_for(manifests, tmp_path / "2", Fake(m, submit=[AdapterError("invalid", "x")] * 3),
                   {"maxJobsPerBatch": 1}, lambda: prices)
    b2 = await mgr2.wait_batch(run_batch(m, mgr2, 3).id)  # batch built under a larger cap
    with pytest.raises(ApiError) as e:
        mgr2.retry_job(b2.jobs[0].id)
    assert e.value.kind == "invalid"
    mgr3 = mgr_for(manifests, tmp_path / "3", Fake(m, submit=[AdapterError("invalid", "x")]),
                   {"confirmThresholdUsd": 0.0001}, lambda: prices)
    b3 = await mgr3.wait_batch(run_batch(m, mgr3).id)
    with pytest.raises(ApiError) as e:
        mgr3.retry_job(b3.jobs[0].id)
    assert e.value.kind == "confirm_required"
    assert mgr3.retry_job(b3.jobs[0].id, confirm=True).status == "queued"


async def test_adapter_clients_closed_on_shutdown_and_reset(manifests, tmp_path):
    closed: list[str] = []

    class C:
        def __init__(self, n):
            self.n = n

        async def aclose(self):
            closed.append(self.n)

    m = manifests["nano-banana-2.1"]
    ad = Fake(m)
    ad.client = C("a")
    mgr = mgr_for(manifests, tmp_path, ad)
    await mgr.wait_batch(run_batch(m, mgr).id)
    mgr.reset_adapters()
    await asyncio.sleep(0.05)
    assert closed == ["a"]
    mgr._adapters["x"] = ad
    ad.client = C("b")
    await mgr.shutdown()
    assert closed == ["a", "b"]


def test_stale_run_dirs_swept_at_startup(tmp_path):
    (tmp_path / "run-stale").mkdir()
    (tmp_path / "run-stale" / "v.mp4").write_bytes(b"x")
    (tmp_path / "run-999999999-dead").mkdir()
    keep = tmp_path / "keep"
    keep.mkdir()
    s1 = Storage(tmp_path)
    assert not (tmp_path / "run-stale").exists() and not (tmp_path / "run-999999999-dead").exists()
    assert keep.exists() and s1.run_dir.exists()
    s2 = Storage(tmp_path)  # another app object in the same process must not delete the first one's files
    assert s1.run_dir.exists() and s2.run_dir.exists()
    assert sweep_stale_runs(tmp_path) == 0


# ------------------------------------------------------------------ cost (15)
def test_unknown_price_flagged(manifests):
    m = manifests["gemini-3.1-flash-lite-image"]
    j = expand(m, GenerationRequest(model_id=m.id, prompt="x"), None, 24)[0]
    lo, hi, w, unknown = estimate_job_ex(m, j, {"entries": {m.id: {"unknown": True, "lastVerified": "2026-10-07"}}})
    assert unknown and (lo, hi) == (0.0, 0.0) and any("unknown" in x for x in w)
    m2 = manifests["nano-banana-2.1"]
    j2 = expand(m2, GenerationRequest(model_id=m2.id, prompt="x"), None, 24)[0]
    assert estimate_job_ex(m2, j2, {"entries": {m2.id: {"lastVerified": "2026-10-07"}}})[3] is False


def test_estimate_requires_confirmation_when_price_unknown(client):
    body = {"request": {"modelId": "gemini-3.1-flash-lite-image", "prompt": "x"}}
    est = client.post("/api/estimate", json=body).json()
    assert est["unknownPrice"] is True and est["confirmRequired"] is True and est["maxUsd"] == 0
    r = client.post("/api/batches", json=body)
    assert r.status_code == 409 and r.json()["error"]["kind"] == "confirm_required"
    assert client.post("/api/batches", json={**body, "confirmOverThreshold": True}).status_code == 200
    ok = client.post("/api/estimate", json={"request": {"modelId": "nano-banana-2.1", "prompt": "x"}}).json()
    assert ok["unknownPrice"] is False and ok["confirmRequired"] is False


# ------------------------------------------------------------------ sweep (11, 22)
def test_prompt_axis_applies_to_each_job(manifests):
    m = manifests["nano-banana-2.1"]
    jobs = expand(m, GenerationRequest(model_id=m.id, prompt="base"),
                  Sweep(axes=[{"param": "prompt", "values": ["A", "B"]}]), 24)
    assert [j.prompt for j in jobs] == ["A", "B"]
    assert [j.effective_params["prompt"] for j in jobs] == ["A", "B"]
    assert [j.requested_params["prompt"] for j in jobs] == ["A", "B"]
    with pytest.raises(ApiError):
        expand(m, GenerationRequest(model_id=m.id, prompt="base"),
               Sweep(prompts=["x", "y"], axes=[{"param": "prompt", "values": ["A"]}]), 24)
    with pytest.raises(ApiError):
        expand(m, GenerationRequest(model_id=m.id, prompt="base"), Sweep(axes=[{"param": "prompt", "values": [""]}]), 24)


def test_cap_checked_before_product(manifests):
    m = manifests["nano-banana-2.1"]
    t0 = time.monotonic()
    with pytest.raises(ApiError) as e:
        expand(m, GenerationRequest(model_id=m.id, prompt="p"),
               Sweep(axes=[{"param": "seed", "values": list(range(3000))},
                           {"param": "seed2", "values": list(range(3000))}]), 24)
    assert "seed2" in e.value.message  # unknown param still reported first
    with pytest.raises(ApiError) as e:
        expand(m, GenerationRequest(model_id=m.id, prompt="p"),
               Sweep(prompts=[f"p{i}" for i in range(3000)], axes=[{"param": "seed", "values": list(range(3000))}]), 24)
    assert e.value.details["jobCount"] == 9_000_000 and time.monotonic() - t0 < 1


def test_duplicate_and_collapsed_axis_values_not_billed_twice(manifests):
    m = manifests["veo-3.1"]
    req = GenerationRequest(model_id=m.id, prompt="p", params={"resolution": "1080p"})
    jobs, warns = expand_with_warnings(m, req, Sweep(axes=[{"param": "duration", "values": [4, 6, 8]}]), 24)
    assert len(jobs) == 1 and jobs[0].effective_params["duration"] == 8
    assert len([w for w in warns if "skipped" in w]) == 2
    jobs, warns = expand_with_warnings(m, GenerationRequest(model_id=m.id, prompt="p"),
                                       Sweep(axes=[{"param": "aspect_ratio", "values": ["16:9", "16:9"]}]), 24)
    assert len(jobs) == 1 and any("duplicate" in w for w in warns)


def test_axis_not_applicable_to_mode_is_dropped_with_warning(manifests):
    m = manifests["veo-3.1"]
    jobs, warns = expand_with_warnings(
        m, GenerationRequest(model_id=m.id, mode="t2v", prompt="p"),
        Sweep(axes=[{"param": "resize_mode", "values": ["crop", "pad"]}]), 24)  # i2v-only param
    assert len(jobs) == 1 and any("resize_mode" in w and "not applicable" in w for w in warns)


def test_estimate_surfaces_sweep_warnings(client):
    r = client.post("/api/estimate", json={"request": {"modelId": "veo-3.1", "prompt": "p", "params": {"resolution": "1080p"}},
                                           "sweep": {"axes": {"duration": [4, 6, 8]}}}).json()
    assert r["jobCount"] == 1 and any("skipped" in w for w in r["warnings"])


def test_redact_keeps_long_text_but_hides_base64():
    cjk = "猫" * 400
    long_en = ("word " * 100).strip()
    assert redact_payload({"p": cjk, "q": long_en}) == {"p": cjk, "q": long_en}
    assert redact_payload({"d": base64.b64encode(b"x" * 600).decode()})["d"].startswith("<base64")


# ------------------------------------------------------------------ settings (21)
def test_settings_hard_limits(client):
    def put(**kw):
        return client.put("/api/settings", json=kw)

    assert put(maxJobsPerBatch=64).status_code == 200
    for bad in ({"maxJobsPerBatch": 65}, {"maxJobsPerBatch": 2.5}, {"confirmThresholdUsd": -1},
                {"maxAttempts": 2.5}, {"pollIntervalSeconds": 0}, {"jobTimeoutSeconds": -3}, {"nope": 1},
                {"staleDays": True}, {"enhancerModel": ""}):
        assert put(**bad).status_code == 400, bad
    assert put(confirmThresholdUsd=0, jobTimeoutSeconds=600, pollIntervalSeconds=5).status_code == 200
    s = client.get("/api/settings").json()
    assert s["jobTimeoutSeconds"] == 600 and s["pollIntervalSeconds"] == 5 and s["confirmThresholdUsd"] == 0


def test_settings_file_cannot_exceed_hard_limits(dirs):
    import json

    (dirs["data_dir"] / "settings.json").write_text(json.dumps({"maxJobsPerBatch": 5000, "bogus": 1}))
    c = TestClient(create_app(demo=True, lan=False, **dirs))
    c.headers["host"] = "localhost"
    s = c.get("/api/settings").json()
    assert s["maxJobsPerBatch"] == 64 and "bogus" not in s and s["jobTimeoutSeconds"] == 900


# ------------------------------------------------------------------ constraints (13)
def _with_constraints(m, *cs):
    m2 = m.model_copy(deep=True)
    m2.constraints = [Constraint.model_validate(c) for c in cs]
    return m2


def test_block_rules_evaluated_after_fixpoint(manifests):
    m = manifests["veo-3.1"]
    # block matches the INTERMEDIATE state (duration 4) but a later force rule moves duration to 8
    m2 = _with_constraints(
        m,
        {"when": {"duration": 4}, "block": True, "reason": "no 4s"},
        {"when": {"resolution": "1080p"}, "then": {"duration": 8}, "reason": "1080p => 8s"},
    )
    ok = constraints.resolve(m2, "t2v", {"resolution": "1080p", "duration": 4})
    assert ok.ok and ok.effective["duration"] == 8
    bad = constraints.resolve(m2, "t2v", {"resolution": "720p", "duration": 4})
    assert [e["reason"] for e in bad.errors] == ["no 4s"]


def test_list_then_is_an_allowed_set(manifests):
    m = manifests["veo-3.1"]
    m2 = _with_constraints(m, {"when": {"resolution": "4k"}, "then": {"duration": [6, 8]}, "reason": "4k: 6 or 8"})
    assert constraints.resolve(m2, "t2v", {"resolution": "4k", "duration": 6}).effective["duration"] == 6
    assert constraints.resolve(m2, "t2v", {"resolution": "4k", "duration": 4}).effective["duration"] == 6
    r = constraints.resolve(m2, "t2v", {"resolution": "4k"})  # default 8 is inside the set
    assert r.effective["duration"] == 8 and r.locked == [{"key": "duration", "reason": "4k: 6 or 8"}]


# ------------------------------------------------------------------ manifests (12)
def test_manifests_do_not_claim_live_verification(manifests, client):
    for m in manifests.values():
        assert m.verified_live is False and (m.verified is False or m.status == "preview"), m.id
    summary = {x["id"]: x for x in client.get("/api/manifests").json()}
    assert all(x["verifiedLive"] is False for x in summary.values())
    assert any("live API" in w for w in summary["veo-3.1"]["warnings"])


def test_input_asset_model_unchanged():
    assert InputAsset(id="a", mime="image/png", data=b"x").gcs_uri is None
