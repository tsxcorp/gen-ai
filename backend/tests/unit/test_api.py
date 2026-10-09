from __future__ import annotations

import io
import json
import os
import stat
import time
import zipfile

from fastapi.testclient import TestClient

from app.adapters.demo import make_png
from app.main import create_app


def wait(client, bid, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        b = client.get(f"/api/batches/{bid}").json()
        if b["status"] == "completed":
            return b
        time.sleep(0.03)
    raise AssertionError("batch did not complete")


def test_manifest_endpoints(client):
    ms = client.get("/api/manifests").json()
    assert len(ms) == 14 and {"id", "kind", "status", "sunsetDate", "lastVerified", "provider", "configured"} <= set(ms[0])
    full = client.get("/api/manifests/veo-3.1").json()
    assert full["params"] and full["constraints"] and full["pricing"]["table"]
    r = client.get("/api/manifests/nope")
    assert r.status_code == 404 and r.json()["error"]["kind"] == "not_found"


def test_resolve_and_error_envelope(client):
    r = client.post("/api/resolve", json={"modelId": "veo-3.1", "mode": "t2v", "params": {"resolution": "1080p", "duration": 6}})
    j = r.json()
    assert j["effectiveParams"]["duration"] == 8 and j["locked"][0]["key"] == "duration" and not j["errors"]
    bad = client.post("/api/resolve", json={"modelId": "zzz"})
    assert bad.status_code == 400 and bad.json()["error"]["kind"] == "invalid"
    assert client.post("/api/resolve", json={"nothing": 1}).json()["error"]["kind"] == "invalid"


def test_estimate_and_confirm_threshold(client):
    est = client.post("/api/estimate", json={"request": {"modelId": "nano-banana-2.1", "prompt": "x"}, "sweep": {"variants": 6}}).json()
    assert est["jobCount"] == est["requestCount"] == 6 and est["minUsd"] == est["maxUsd"] == 0.204 and not est["confirmRequired"]
    req = {"request": {"modelId": "veo-3.1", "prompt": "x", "params": {"resolution": "4k"}}, "sweep": {"variants": 4}}
    est = client.post("/api/estimate", json=req).json()
    assert est["confirmRequired"] and est["maxUsd"] > 5
    r = client.post("/api/batches", json=req)
    assert r.status_code == 409 and r.json()["error"]["kind"] == "confirm_required"
    assert client.post("/api/batches", json={**req, "confirmOverThreshold": True}).status_code == 200


def test_threshold_configurable(client):
    client.put("/api/settings", json={"confirmThresholdUsd": 0.05})
    est = client.post("/api/estimate", json={"request": {"modelId": "nano-banana-2.1", "prompt": "x"}, "sweep": {"variants": 3}}).json()
    assert est["confirmRequired"]
    assert client.put("/api/settings", json={"bogus": 1}).status_code == 400


def test_estimate_batch_limit(client):
    r = client.post("/api/estimate", json={"request": {"modelId": "nano-banana-2.1", "prompt": "x"}, "sweep": {"variants": 25}})
    assert r.status_code == 400 and "limit" in r.json()["error"]["message"]


def test_batch_n3_zip_and_sidecar(client):
    r = client.post("/api/batches", json={"request": {"modelId": "nano-banana-2.1", "prompt": "fox"}, "sweep": {"variants": 3}}).json()
    assert len(r["jobs"]) == 3
    b = wait(client, r["batchId"])
    ids = [a["id"] for j in b["jobs"] for a in j["assets"]]
    assert len(ids) == 3 and all(j["status"] == "succeeded" for j in b["jobs"])
    orig = client.get(f"/api/assets/{ids[0]}")
    assert orig.headers["content-type"] == "image/png" and orig.content.startswith(b"\x89PNG")
    z = zipfile.ZipFile(io.BytesIO(client.post("/api/zip", json={"assetIds": ids}).content))
    names = z.namelist()
    assert len(names) == 6
    side = json.loads(z.read(f"{ids[0]}.json"))
    assert side["job"]["effectiveParams"]["image_size"] == "1K" and "requestedParams" in side["job"]
    png_name = next(n for n in names if n.startswith(ids[0]) and n.endswith(".png"))
    assert z.read(png_name) == orig.content  # byte-identical
    assert client.post("/api/zip", json={"assetIds": ["nope"]}).status_code == 404


def test_blocked_not_retried_manual_retry_ok(client):
    r = client.post("/api/batches", json={"request": {"modelId": "nano-banana-2.1", "prompt": "x [blocked]"}}).json()
    b = wait(client, r["batchId"])
    j = b["jobs"][0]
    assert j["status"] == "blocked" and j["error"]["kind"] == "blocked" and j["attempts"] == 1
    new = client.post(f"/api/jobs/{j['id']}/retry").json()
    assert new["id"] != j["id"] and new["status"] in ("queued", "running", "blocked")
    assert client.post("/api/jobs/zzz/retry").status_code == 404


def test_quota_recovers(client):
    r = client.post("/api/batches", json={"request": {"modelId": "nano-banana-2.1", "prompt": "x [quota]"}}).json()
    j = wait(client, r["batchId"])["jobs"][0]
    assert j["status"] == "succeeded" and j["attempts"] == 2


def test_uploads_consent_rule(client):
    png = make_png(8, 8, "u")
    bad = client.post("/api/uploads", files={"file": ("a.png", png, "image/png")}, data={"hasPerson": "true", "consent": "false"})
    assert bad.status_code == 400 and bad.json()["error"]["kind"] == "invalid"
    ok = client.post("/api/uploads", files={"file": ("a.png", png, "image/png")}, data={"hasPerson": "true", "consent": "true"})
    assert ok.status_code == 200 and ok.json()["kind"] == "upload"
    assert client.post("/api/uploads", files={"file": ("a.txt", b"hello", "text/plain")}, data={}).status_code == 400
    aid = ok.json()["id"]
    r = client.post("/api/batches", json={"request": {"modelId": "veo-3.1-fast", "mode": "i2v", "prompt": "x", "assets": {"first_frame": aid}}})
    assert r.status_code == 200
    miss = client.post("/api/estimate", json={"request": {"modelId": "veo-3.1-fast", "mode": "i2v", "prompt": "x"}})
    assert miss.status_code == 400
    p = client.post("/api/payload", json={"request": {"modelId": "veo-3.1-fast", "mode": "i2v", "prompt": "x", "assets": {"first_frame": aid}}}).json()
    assert "image" in p["payloads"][0]["payload"]["instances"][0]


def test_providers_masked_and_perms(client):
    assert client.get("/api/providers").json()["vertex"]["hasKey"] is False
    key = {"type": "service_account", "client_email": "a@b.c", "private_key": "SECRET-KEY-MATERIAL"}
    r = client.put("/api/providers/vertex", json={"json": key, "projectId": "proj-test-1", "location": "global"})
    assert r.status_code == 200
    for resp in (r, client.get("/api/providers")):
        assert "SECRET-KEY-MATERIAL" not in resp.text and "a@b.c" not in resp.text
    assert client.get("/api/providers").json()["vertex"] == {
        "configured": True, "hasKey": True, "authMethod": "service_account", "keySource": "json", "projectId": "proj-test-1", "location": "global", "gcsBucket": None}
    path = client.ctx.data_dir / "providers.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    bad = client.put("/api/providers/vertex", json={"json": {"type": "x", "private_key": "SECRET-KEY-MATERIAL"}, "projectId": "proj-test-1"})
    assert bad.status_code == 400 and "SECRET-KEY-MATERIAL" not in bad.text
    assert client.put("/api/providers/vertex", content=b"{", headers={"content-type": "application/json"}).status_code == 400


def test_providers_loose_perms_are_fixed(dirs):
    p = dirs["data_dir"] / "providers.json"
    p.write_text("{}")
    os.chmod(p, 0o644)
    create_app(demo=True, lan=False, **dirs)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_presets_and_prompts_roundtrip(client, dirs):
    items = [{"name": "P1", "modelId": "veo-3.1", "params": {"resolution": "720p"}}]
    out = client.put("/api/presets", json={"items": items}).json()
    assert out["items"][0]["id"]
    assert client.get("/api/presets").json() == out
    assert json.loads((dirs["data_dir"] / "presets.json").read_text()) == out
    assert client.put("/api/prompts", json=[{"name": "", "text": "x"}]).status_code == 400
    assert client.put("/api/prompts", json=[{"name": "n", "text": "hello"}]).status_code == 200
    assert client.get("/api/prompts").json()["items"][0]["text"] == "hello"


def test_enhance_demo_deterministic(client):
    a = client.post("/api/enhance", json={"modelId": "nano-banana-2.1", "prompt": "a cat"}).json()["suggestion"]
    b = client.post("/api/enhance", json={"modelId": "nano-banana-2.1", "prompt": "a cat"}).json()["suggestion"]
    assert a == b and a.startswith("a cat")
    assert client.post("/api/enhance", json={"modelId": "nano-banana-2.1", "prompt": " "}).status_code == 400


def test_sse_stream_format_and_snapshot(client):
    q = client.ctx.hub.subscribe()
    r = client.post("/api/batches", json={"request": {"modelId": "nano-banana-2.1", "prompt": "x"}}).json()
    eid, ev, data = q.get_nowait()
    assert ev == "batch.updated" and "id" in data and eid >= 1
    from app.core.events import EventHub

    assert EventHub.format("job.updated", {"a": 1}, 7) == 'id: 7\nevent: job.updated\ndata: {"a": 1}\n\n'
    wait(client, r["batchId"])
    # no `Accept: text/event-stream` -> finite snapshot of recent events (does not hang)
    snap = client.get("/api/events")
    assert snap.headers["content-type"].startswith("text/event-stream")
    assert "event: job.updated" in snap.text and "event: batch.updated" in snap.text


def test_cancel_endpoint(client):
    r = client.post("/api/batches", json={"request": {"modelId": "nano-banana-2.1", "prompt": "x"}, "sweep": {"variants": 10}}).json()
    c = client.post(f"/api/batches/{r['batchId']}/cancel")
    assert c.status_code == 200 and c.json()["ok"]
    assert client.post("/api/batches/zzz/cancel").status_code == 404


def test_token_middleware_only_in_lan(dirs):
    open_app = TestClient(create_app(demo=True, lan=False, **dirs))
    assert open_app.get("/api/manifests").status_code == 200
    lan = TestClient(create_app(demo=True, lan=True, token="t0k", **dirs))
    assert lan.get("/api/manifests").status_code == 401
    assert lan.get("/api/manifests").json()["error"]["kind"] == "auth"
    assert lan.get("/api/manifests", headers={"Authorization": "Bearer t0k"}).status_code == 200
    assert lan.get("/api/manifests?token=t0k").status_code == 401  # invariant 20: never accepted from the URL
    assert lan.get("/api/manifests", headers={"X-Access-Token": "bad"}).status_code == 401


def test_lan_generates_random_token(dirs, capsys):
    a = create_app(demo=True, lan=True, **dirs).state.ctx.token
    b = create_app(demo=True, lan=True, **dirs).state.ctx.token
    assert a and b and a != b and len(a) >= 24
    assert a in capsys.readouterr().out


def test_lan_env_token_not_printed_and_still_required(dirs, monkeypatch, capsys):
    env_token = "production-env-token-must-not-appear-in-logs"
    monkeypatch.setenv("AIGEN_TOKEN", env_token)
    app = create_app(demo=True, lan=True, **dirs)
    assert app.state.ctx.token == env_token
    with TestClient(app) as lan:
        missing = lan.get("/api/manifests")
        assert missing.status_code == 401
        assert missing.json()["error"]["kind"] == "auth"
        assert lan.get("/api/manifests", headers={"X-Access-Token": "wrong-token"}).status_code == 401
        assert lan.get("/api/manifests", headers={"X-Access-Token": env_token}).status_code == 200
    captured = capsys.readouterr()
    assert env_token not in captured.out
    assert env_token not in captured.err

def test_tmp_cleanup_on_shutdown(dirs):
    app = create_app(demo=True, lan=False, **dirs)
    run_dir = app.state.ctx.storage.run_dir
    with TestClient(app) as c:
        r = c.post("/api/batches", json={"request": {"modelId": "nano-banana-2.1", "prompt": "x"}}).json()
        wait(c, r["batchId"])
        assert any(run_dir.iterdir())
    assert not run_dir.exists()
