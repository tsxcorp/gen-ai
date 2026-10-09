"""Multi-provider (D6b): registry, masking, isolation, adapters (httpx.MockTransport: no network), manifests, costs."""
from __future__ import annotations

import json
import stat

import httpx
import pytest
from fastapi.testclient import TestClient

from app.adapters.base import OutputRef, SubmitHandle
from app.adapters.byteplus_seedance import (
    ArkClient,
    ByteplusConfig,
    SeedanceAdapter,
    ark_host,
    assert_ark_url,
    assert_download_url,
    parse_task,
)
from app.adapters.byteplus_seedance import normalize_error as ark_error
from app.adapters.demo import make_png
from app.adapters.openai_image import (
    OpenAIClient,
    OpenAIConfig,
    OpenAIImageAdapter,
    assert_openai_url,
    parse_images_response,
)
from app.adapters.openai_image import normalize_error as oai_error
from app.adapters.vertex_common import VertexClient, VertexConfig
from app.core import constraints
from app.core.cost import estimate_job_ex
from app.core.expand import expand
from app.errors import AdapterError, ApiError
from app.main import create_app
from app.providers import apply_put, mask_all
from app.schemas import GenerationRequest, InputAsset

OAI_KEY = "sk-unit-OPENAI-SECRET-0123456789"
BP_KEY = "bp-unit-BYTEPLUS-SECRET-0123456789"
H = {"host": "localhost"}


def job_for(manifests, model, mode=None, params=None, inputs=None, prompt="a cat"):
    jobs = expand(manifests[model], GenerationRequest(model_id=model, mode=mode, prompt=prompt, params=params or {}),
                  None, 24)
    j = jobs[0]
    j.inputs = inputs or {}
    return j


def run(coro):
    import asyncio

    return asyncio.run(coro)


def oai_client(handler, **cfg):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    return OpenAIClient(OpenAIConfig(api_key=OAI_KEY, **cfg), http=http)


def ark_client(handler, region="ap-southeast"):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False)
    return ArkClient(ByteplusConfig(api_key=BP_KEY, region=region), http=http)


# ------------------------------------------------------------------ API: registry / masking / isolation
@pytest.fixture()
def real(dirs):
    """Non-demo app (providers really unconfigured). Host pinned to localhost."""
    app = create_app(demo=False, lan=False, **dirs)
    with TestClient(app, headers=H) as c:
        c.ctx = app.state.ctx
        yield c


def test_get_providers_shape_all_unconfigured(client):
    body = client.get("/api/providers").json()
    assert set(body) == {"vertex", "openai", "byteplus"}
    assert body["openai"] == {"configured": False, "hasKey": False, "organization": None, "project": None}
    assert body["byteplus"] == {"configured": False, "hasKey": False, "region": None}
    assert body["vertex"]["authMethod"] is None and body["vertex"]["configured"] is False


def test_put_openai_masks_and_keeps_key_when_blank(client):
    r = client.put("/api/providers/openai", json={"apiKey": OAI_KEY, "organization": "org-abc", "project": "proj_1"})
    assert r.status_code == 200
    assert r.json() == {"configured": True, "hasKey": True, "organization": "org-abc", "project": "proj_1"}
    r = client.put("/api/providers/openai", json={"apiKey": "", "project": None})  # blank key = keep, null = clear
    assert r.status_code == 200 and r.json()["project"] is None and r.json()["organization"] == "org-abc"
    stored = json.loads((client.ctx.data_dir / "providers.json").read_text())
    assert stored["openai"]["apiKey"] == OAI_KEY
    assert stat.S_IMODE((client.ctx.data_dir / "providers.json").stat().st_mode) == 0o600
    for resp in (client.get("/api/providers"), client.get("/api/manifests")):
        assert OAI_KEY not in resp.text


def test_put_validation_never_echoes_key(client):
    bad_key = "has space SECRET-VALUE-XYZ"
    r = client.put("/api/providers/openai", json={"apiKey": bad_key})
    assert r.status_code == 400 and "SECRET-VALUE-XYZ" not in r.text
    assert client.put("/api/providers/openai", json={}).status_code == 400  # key required first time
    assert client.put("/api/providers/openai", json={"apiKey": OAI_KEY, "organization": "x y\r\nEvil: 1"}).status_code == 400
    assert client.put("/api/providers/byteplus", json={"apiKey": BP_KEY, "region": "evil.com/x"}).status_code == 400
    assert client.put("/api/providers/byteplus", json={"apiKey": BP_KEY, "region": "AP"}).status_code == 400
    assert client.put("/api/providers/nope", json={"apiKey": BP_KEY}).status_code == 404
    assert client.put("/api/providers/openai", content=b"[1]", headers={"content-type": "application/json"}).status_code == 400
    assert not (client.ctx.data_dir / "providers.json").exists()  # nothing half-saved


def test_byteplus_default_region_and_isolation(client):
    key = {"type": "service_account", "client_email": "a@b.c", "private_key": "VERTEX-PRIVATE-KEY"}
    assert client.put("/api/providers/vertex", json={"json": key, "projectId": "proj-test-1"}).status_code == 200
    assert client.put("/api/providers/openai", json={"apiKey": OAI_KEY}).status_code == 200
    r = client.put("/api/providers/byteplus", json={"apiKey": BP_KEY})
    assert r.json() == {"configured": True, "hasKey": True, "region": "ap-southeast"}
    before = json.loads((client.ctx.data_dir / "providers.json").read_text())
    # change / delete one provider: the other entries are byte-for-byte untouched
    client.put("/api/providers/byteplus", json={"apiKey": BP_KEY + "2", "region": "ap-southeast-2"})
    assert client.delete("/api/providers/openai").json()["configured"] is False
    after = json.loads((client.ctx.data_dir / "providers.json").read_text())
    assert after["vertex"] == before["vertex"] and "openai" not in after and after["byteplus"]["region"] == "ap-southeast-2"
    masked = client.get("/api/providers").json()
    assert masked["vertex"]["configured"] and not masked["openai"]["configured"] and masked["byteplus"]["configured"]
    assert client.delete("/api/providers/nope").status_code == 404
    assert client.delete("/api/providers/openai").status_code == 200  # idempotent


def test_vertex_adc_needs_no_key_and_drops_stored_key(client):
    key = {"type": "service_account", "client_email": "a@b.c", "private_key": "VERTEX-PRIVATE-KEY"}
    client.put("/api/providers/vertex", json={"json": key, "projectId": "proj-test-1"})
    r = client.put("/api/providers/vertex", json={"authMethod": "adc", "projectId": "proj-test-1", "location": "global"})
    assert r.status_code == 200
    assert r.json() == {"configured": True, "hasKey": False, "authMethod": "adc", "keySource": None,
                        "projectId": "proj-test-1", "location": "global", "gcsBucket": None}
    stored = json.loads((client.ctx.data_dir / "providers.json").read_text())["vertex"]
    assert "serviceAccountJson" not in stored and "VERTEX-PRIVATE-KEY" not in json.dumps(stored)
    assert client.put("/api/providers/vertex", json={"authMethod": "adc", "projectId": "proj-test-1",
                                                     "json": key}).status_code == 400
    assert client.put("/api/providers/vertex", json={"authMethod": "magic", "projectId": "proj-test-1"}).status_code == 400
    # invariant 13 still applies in adc mode
    assert client.put("/api/providers/vertex", json={"authMethod": "adc", "projectId": "proj-test-1",
                                                     "location": "evil.com/x"}).status_code == 400


def test_legacy_vertex_file_without_auth_method_still_works():
    cfg = {"projectId": "proj-test-1", "location": "global", "serviceAccountPath": "/x.json"}
    m = mask_all({"vertex": cfg})["vertex"]
    assert m["configured"] and m["authMethod"] == "service_account" and m["keySource"] == "path"
    assert "/x.json" not in json.dumps(mask_all({"vertex": cfg}))
    assert apply_put("vertex", {"projectId": "proj-test-1", "location": "global"}, cfg)["serviceAccountPath"] == "/x.json"


def test_vertex_adc_client_uses_google_auth_default(monkeypatch):
    cfg = VertexConfig.from_providers({"authMethod": "adc", "projectId": "proj-test-1", "location": "global",
                                       "serviceAccountPath": "/ignored.json"})
    assert cfg and cfg.auth_method == "adc" and cfg.service_account_path is None
    calls = []

    class Creds:
        valid = False
        token = None

        def refresh(self, _req):
            self.valid, self.token = True, "adc-token"

    import google.auth

    monkeypatch.setattr(google.auth, "default", lambda scopes=None: (calls.append(scopes) or Creds(), "p"))
    client = VertexClient(cfg)
    assert run(client.token()) == "adc-token" and calls
    assert run(client._auth_headers())["x-goog-user-project"] == "proj-test-1"


def test_manifests_list_has_provider_and_configured(client, real):
    ms = {m["id"]: m for m in client.get("/api/manifests").json()}
    assert ms["gpt-image-2.5-flare"]["provider"] == "openai" and ms["seedance-2.5"]["provider"] == "byteplus"
    assert all(m["configured"] is True for m in ms.values())  # demo
    ms = {m["id"]: m for m in real.get("/api/manifests").json()}
    assert ms["veo-3.1"]["configured"] is False and ms["gpt-image-2.5-sunburst"]["configured"] is False
    real.put("/api/providers/openai", json={"apiKey": OAI_KEY})
    ms = {m["id"]: m for m in real.get("/api/manifests").json()}
    assert ms["gpt-image-2.5-sunburst"]["configured"] is True and ms["seedance-2.5"]["configured"] is False
    assert real.get("/api/manifests/seedance-2.5").json()["configured"] is False


def test_not_configured_blocks_batches_but_not_estimates(real):
    req = {"request": {"modelId": "seedance-2.5", "prompt": "x"}}
    r = real.post("/api/batches", json=req)
    assert r.status_code == 400 and r.json()["error"]["kind"] == "not_configured"
    assert real.post("/api/estimate", json=req).status_code == 200
    assert real.post("/api/payload", json=req).status_code == 200
    r = real.post("/api/batches", json={"request": {"modelId": "gpt-image-2.5-sunburst", "prompt": "x"}})
    assert r.json()["error"]["kind"] == "not_configured"
    assert real.post("/api/providers/openai/test").json()["error"]["kind"] == "not_configured"


def test_provider_test_demo(client):
    for p in ("vertex", "openai", "byteplus"):
        assert client.post(f"/api/providers/{p}/test").json()["ok"] is True
    assert client.post("/api/providers/nope/test").status_code == 404


def test_demo_batches_on_new_providers(client):
    import time

    for model, extra in (("gpt-image-2.5-sunburst", {}), ("seedance-2.0-fast", {})):
        r = client.post("/api/batches", json={"request": {"modelId": model, "prompt": "demo " + model, **extra}})
        assert r.status_code == 200, r.text
        bid = r.json()["batchId"]
        for _ in range(100):
            b = client.get(f"/api/batches/{bid}").json()
            if b["status"] == "completed":
                break
            time.sleep(0.05)
        j = b["jobs"][0]
        assert j["status"] == "succeeded" and j["provider"] in ("openai", "byteplus")
        assert client.get(f"/api/assets/{j['assets'][0]['id']}").status_code == 200


# ------------------------------------------------------------------ manifests / constraints
def test_new_manifests_flags(manifests):
    for mid in ("gpt-image-2.5-sunburst", "gpt-image-2.5-flare", "seedance-2.5", "seedance-2.0",
                "seedance-2.0-fast", "seedance-2.0-mini"):
        m = manifests[mid]
        assert m.verified is False and m.verified_live is False
        assert m.limits.concurrency_group in ("openai", "byteplus")
    assert manifests["seedance-2.5"].limits.max_concurrent == 3 and manifests["gpt-image-2.5-flare"].limits.max_concurrent == 5
    for mid in ("seedance-2.5", "seedance-2.0", "seedance-2.0-fast", "seedance-2.0-mini"):
        assert manifests[mid].param("seed") is None and manifests[mid].param("negative_prompt") is None


def test_seedance_resolution_rules(manifests):
    res = {mid: manifests[mid].param("resolution").values for mid in manifests if mid.startswith("seedance")}
    assert "4k" in res["seedance-2.0"] and "4k" not in res["seedance-2.5"]
    assert res["seedance-2.0-fast"] == res["seedance-2.0-mini"] == ["480p", "720p"]
    r = constraints.resolve(manifests["seedance-2.0-fast"], "t2v", {"resolution": "1080p"})
    assert r.errors and r.errors[0]["key"] == "resolution"


def test_seedance_ratio_adaptive_with_frames(manifests):
    m = manifests["seedance-2.0"]
    r = constraints.resolve(m, "i2v", {"ratio": "9:16", "first_frame": "a1"})
    assert r.effective["ratio"] == "adaptive" and any(x["key"] == "ratio" for x in r.locked)
    assert constraints.resolve(m, "first_last", {"first_frame": "a", "last_frame": "b"}).effective["ratio"] == "adaptive"
    assert constraints.resolve(m, "t2v", {"ratio": "9:16"}).effective["ratio"] == "9:16"
    assert constraints.resolve(m, "t2v", {"seed": 1}).errors  # no seed


@pytest.mark.parametrize("size,ok", [
    ("1024x1024", True), ("auto", True), ("3840x2160", True), ("1280x3840", True), ("1000x1024", False),
    ("4096x1024", False), ("3840x1024", False), ("16x64", False), ("1024", False), ("axb", False),
    ("3840x3840", False), ("16x16", False),
])
def test_openai_size_rule(manifests, size, ok):
    r = constraints.resolve(manifests["gpt-image-2.5-sunburst"], "t2i", {"size": size})
    assert (not r.errors) is ok


def test_openai_transparent_background_forces_format(manifests):
    r = constraints.resolve(manifests["gpt-image-2.5-sunburst"], "t2i", {"background": "transparent", "output_format": "jpeg"})
    assert r.effective["output_format"] == "png"


# ------------------------------------------------------------------ cost
def test_seedance_cost_per_second(manifests):
    prices = {"entries": {"seedance-2.0": {"lastVerified": "2026-10-07", "variance": {"min": 1.0, "max": 1.15}}}}
    j = job_for(manifests, "seedance-2.0", params={"resolution": "720p", "duration": 10})
    lo, hi, _, unknown = estimate_job_ex(manifests["seedance-2.0"], j, prices, 9999)
    assert not unknown and lo == pytest.approx(1.5) and hi == pytest.approx(1.725)
    j = job_for(manifests, "seedance-2.0", params={"resolution": "4k", "duration": 5})
    assert estimate_job_ex(manifests["seedance-2.0"], j, prices, 9999)[0] == pytest.approx(3.9)


def test_gpt_image_cost_and_unknowns(manifests):
    prices = {"entries": {"gpt-image-2.5-sunburst": {"lastVerified": "2026-10-07"},
                          "gpt-image-2.5-flare": {"lastVerified": "2026-10-07", "unknown": True}}}
    m = manifests["gpt-image-2.5-sunburst"]
    lo, hi, _, unknown = estimate_job_ex(m, job_for(manifests, m.id, params={"quality": "low"}), prices, 9999)
    assert not unknown and lo == pytest.approx(0.006)
    for params in ({"quality": "xhigh"}, {"quality": "auto"}, {"size": "auto"}, {"size": "1280x1024"}):
        assert estimate_job_ex(m, job_for(manifests, m.id, params=params), prices, 9999)[3], params
    f = manifests["gpt-image-2.5-flare"]
    assert estimate_job_ex(f, job_for(manifests, f.id), prices, 9999)[3]


# ------------------------------------------------------------------ OpenAI adapter
def test_openai_url_allowlist():
    assert_openai_url("https://api.openai.com/v1/images/generations")
    for bad in ("http://api.openai.com/v1", "https://api.openai.com.evil.com/v1", "https://evil.com/api.openai.com",
                "https://user:pw@api.openai.com/v1", "https://api.openai.com:8443/v1", "https://openai.com/v1"):
        with pytest.raises(AdapterError):
            assert_openai_url(bad)


def test_openai_generation_request_and_response(manifests):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"], seen["org"], seen["body"] = str(req.url), req.headers["authorization"], \
            req.headers.get("openai-organization"), json.loads(req.content)
        import base64

        return httpx.Response(200, json={"output_format": "png", "data": [{"b64_json": base64.b64encode(make_png(8, 8, "z")).decode()}]})

    ad = OpenAIImageAdapter(manifests["gpt-image-2.5-sunburst"], oai_client(handler, organization="org-1"))
    job = job_for(manifests, "gpt-image-2.5-sunburst", params={"size": "1536x1024", "quality": "high"})
    handle = run(ad.submit(job))
    assert seen["url"] == "https://api.openai.com/v1/images/generations"
    assert seen["auth"] == f"Bearer {OAI_KEY}" and seen["org"] == "org-1"
    assert seen["body"] == {"model": "gpt-image-2.5-sunburst", "prompt": "a cat", "size": "1536x1024", "quality": "high",
                            "output_format": "png", "background": "auto", "moderation": "auto", "n": 1}
    assert OAI_KEY not in json.dumps(ad.build_payload(job))
    res = run(ad.poll(handle))
    assert res.state == "done" and res.outputs[0].mime == "image/png"


def test_openai_edit_is_multipart_with_images(manifests):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"], seen["ct"], seen["body"] = str(req.url), req.headers["content-type"], req.content
        return httpx.Response(200, json={"data": [{"b64_json": "aGk="}]})

    png = make_png(8, 8, "e")
    job = job_for(manifests, "gpt-image-2.5-sunburst", mode="edit", params={"reference_images": ["a1", "a2"]},
                  inputs={"reference_images": [InputAsset(id="a1", mime="image/png", data=png),
                                               InputAsset(id="a2", mime="image/png", data=png)]})
    ad = OpenAIImageAdapter(manifests["gpt-image-2.5-sunburst"], oai_client(handler))
    run(ad.submit(job))
    assert seen["url"].endswith("/v1/images/edits") and seen["ct"].startswith("multipart/form-data")
    assert seen["body"].count(b'name="image[]"') == 2 and b'name="model"' in seen["body"]
    assert b"output_compression" not in seen["body"]  # png: compression is not sent
    bare = job_for(manifests, "gpt-image-2.5-sunburst")
    bare.mode = "edit"
    with pytest.raises(AdapterError):  # edit without image bytes
        ad.build_payload(bare)


def test_openai_error_classification():
    blocked = oai_error(400, {"error": {"code": "moderation_blocked", "message": "no"}})
    assert blocked.kind == "blocked"
    assert oai_error(400, {"error": {"code": "invalid_value", "message": "this was blocked by moderation"}}).kind == "invalid"
    assert oai_error(429, {}).kind == "quota" and oai_error(401, {}).kind == "auth" and oai_error(403, {}).kind == "auth"
    assert oai_error(503, {}).kind == "network" and oai_error(504, {}).kind == "timeout"
    with pytest.raises(AdapterError):
        parse_images_response({"data": []})
    with pytest.raises(AdapterError):
        parse_images_response({"data": [{"url": "https://x"}]})


def test_openai_no_redirect_follow_and_no_resubmit_on_timeout(manifests):
    hits = []

    def redirect(req):
        hits.append(str(req.url))
        return httpx.Response(307, headers={"location": "https://evil.example/steal"})

    ad = OpenAIImageAdapter(manifests["gpt-image-2.5-sunburst"], oai_client(redirect))
    with pytest.raises(AdapterError) as e:
        run(ad.submit(job_for(manifests, "gpt-image-2.5-sunburst")))
    assert e.value.kind == "invalid" and hits == ["https://api.openai.com/v1/images/generations"]

    def read_timeout(req):
        raise httpx.ReadTimeout("slow", request=req)

    ad = OpenAIImageAdapter(manifests["gpt-image-2.5-sunburst"], oai_client(read_timeout))
    with pytest.raises(AdapterError) as e:
        run(ad.submit(job_for(manifests, "gpt-image-2.5-sunburst")))
    assert e.value.kind == "timeout" and not e.value.before_send

    def refused(req):
        raise httpx.ConnectError("no", request=req)

    ad = OpenAIImageAdapter(manifests["gpt-image-2.5-sunburst"], oai_client(refused))
    with pytest.raises(AdapterError) as e:
        run(ad.submit(job_for(manifests, "gpt-image-2.5-sunburst")))
    assert e.value.kind == "network" and e.value.before_send


def test_openai_config_never_reprs_the_key_and_rejects_bad_headers():
    cfg = OpenAIConfig.from_providers({"apiKey": OAI_KEY, "organization": "org-1"})
    assert OAI_KEY not in repr(cfg) and OAI_KEY not in repr(oai_client(lambda r: None))
    with pytest.raises(ApiError):
        OpenAIConfig.from_providers({"apiKey": OAI_KEY, "organization": "a b\r\nX: y"})
    assert OpenAIConfig.from_providers({"apiKey": ""}) is None


# ------------------------------------------------------------------ BytePlus adapter
def test_ark_host_and_url_checks():
    assert ark_host("ap-southeast") == "ark.ap-southeast.bytepluses.com"
    assert ark_host("ap-southeast-1") == "ark.ap-southeast-1.bytepluses.com"
    for bad in ("", "AP", "a.b", "a/b", "a-", "-a", "ap_southeast", "x" * 40, "evil.com#", "1ap"):
        with pytest.raises(AdapterError):
            ark_host(bad)
    assert_ark_url("https://ark.ap-southeast.bytepluses.com/api/v3/x", "ap-southeast")
    for bad in ("https://ark.ap-southeast.bytepluses.com.evil.com/x", "http://ark.ap-southeast.bytepluses.com/x",
                "https://ark.other.bytepluses.com/x", "https://evil.com/ark.ap-southeast.bytepluses.com"):
        with pytest.raises(AdapterError):
            assert_ark_url(bad, "ap-southeast")
    assert_download_url("https://tos-ap-southeast-1.bytepluses.com/v.mp4?sig=1")
    for bad in ("https://evil.com/v.mp4", "http://x.bytepluses.com/v.mp4", "https://bytepluses.com.evil.com/v.mp4",
                "https://127.0.0.1/v.mp4", "https://bytepluses.com/v.mp4", "https://u:p@x.bytepluses.com/v.mp4"):
        with pytest.raises(AdapterError):
            assert_download_url(bad)
    with pytest.raises(ApiError):
        ByteplusConfig.from_providers({"apiKey": BP_KEY, "region": "evil.com"})


def test_seedance_payload(manifests):
    m = manifests["seedance-2.5"]
    png = make_png(8, 8, "f")
    inputs = {"first_frame": [InputAsset(id="f", mime="image/png", data=png)],
              "last_frame": [InputAsset(id="l", mime="image/png", data=png)]}
    job = job_for(manifests, m.id, mode="first_last", params={"first_frame": "f", "last_frame": "l", "duration": 8},
                  inputs=inputs)
    p = SeedanceAdapter(m).build_payload(job)
    assert p["model"] == "dreamina-seedance-2-5-260628" and p["ratio"] == "adaptive" and p["duration"] == 8
    assert p["resolution"] == "720p" and p["generate_audio"] is True and p["watermark"] is False
    assert [c["type"] for c in p["content"]] == ["text", "image_url", "image_url"]
    assert [c.get("role") for c in p["content"][1:]] == ["first_frame", "last_frame"]
    assert p["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert not {"seed", "negative_prompt", "camera_fixed"} & set(p)
    t2v = SeedanceAdapter(m).build_payload(job_for(manifests, m.id, params={"ratio": "9:16"}))
    assert t2v["content"] == [{"type": "text", "text": "a cat"}] and t2v["ratio"] == "9:16"


def test_parse_task_states():
    assert parse_task({"status": "queued"}).state == "running" and parse_task({"status": "running"}).state == "running"
    done = parse_task({"status": "succeeded", "content": {"video_url": "https://x.bytepluses.com/v.mp4"}})
    assert done.state == "done" and done.outputs[0].mime == "video/mp4"
    assert parse_task({"status": "succeeded", "content": {}}).error.kind == "invalid"
    f = parse_task({"status": "failed", "error": {"code": "OutputVideoSensitiveContentDetected", "message": "m"}})
    assert f.state == "failed" and f.error.kind == "blocked"
    assert parse_task({"status": "failed", "error": {"code": "Weird", "message": "this was blocked by safety"}}).error.kind == "invalid"
    assert parse_task({"status": "failed", "error": {"code": "QuotaExceeded"}}).error.kind == "quota"
    assert parse_task({"status": "expired"}).error.kind == "timeout"
    assert ark_error(429, {}).kind == "quota" and ark_error(401, {}).kind == "auth" and ark_error(500, {}).kind == "network"
    assert ark_error(400, {"error": {"code": "InputTextSensitiveContentDetected"}}).kind == "blocked"
    assert ark_error(400, {"error": {"code": "InvalidParameter", "message": "sensitive"}}).kind == "invalid"


def test_seedance_submit_poll_download_flow(manifests, tmp_path):
    calls = []
    video = b"\x00\x00\x00\x18ftypmp42" + b"v" * 5000

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, str(req.url), req.headers.get("authorization")))
        if req.method == "POST":
            return httpx.Response(200, json={"id": "cgt-123"})
        if "tos-ap" in str(req.url):
            return httpx.Response(200, content=video)
        return httpx.Response(200, json={"status": "succeeded",
                                         "content": {"video_url": "https://tos-ap-southeast-1.bytepluses.com/v.mp4"}})

    m = manifests["seedance-2.0-mini"]
    ad = SeedanceAdapter(m, ark_client(handler))
    h = run(ad.submit(job_for(manifests, m.id)))
    assert h.id == "cgt-123" and calls[0][1] == "https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks"
    res = run(ad.poll(h))
    files = run(ad.download(res.outputs, tmp_path))
    assert files[0].path.read_bytes() == video and files[0].size_bytes == len(video)
    assert calls[0][2] == f"Bearer {BP_KEY}" and calls[1][2] == f"Bearer {BP_KEY}"
    assert calls[-1][2] is None  # the pre-signed URL never receives the API key
    assert sum(1 for c in calls if c[0] == "POST") == 1


def test_seedance_download_rejects_foreign_host_and_cleans_up(manifests, tmp_path):
    ad = SeedanceAdapter(manifests["seedance-2.0"], ark_client(lambda r: httpx.Response(200, content=b"x")))
    out = tmp_path / "out"
    with pytest.raises(AdapterError):
        run(ad.download([OutputRef(mime="video/mp4", uri="https://evil.example/v.mp4")], out))
    assert list(out.iterdir()) == []


def test_seedance_cancel_only_while_queued(manifests):
    log = []

    def make(status):
        def handler(req):
            log.append(req.method)
            return httpx.Response(200, json={"status": status})
        return handler

    h = SubmitHandle(id="cgt-1")
    ad = SeedanceAdapter(manifests["seedance-2.5"], ark_client(make("running")))
    assert run(ad.cancel(h)) is False and "DELETE" not in log
    ad = SeedanceAdapter(manifests["seedance-2.5"], ark_client(make("queued")))
    assert run(ad.cancel(h)) is True and "DELETE" in log
    with pytest.raises(AdapterError):
        run(ad.poll(SubmitHandle(id="../../etc")))


def test_ark_redirect_not_followed(manifests):
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(302, headers={"location": "https://evil.example/"})

    ad = SeedanceAdapter(manifests["seedance-2.5"], ark_client(handler))
    with pytest.raises(AdapterError) as e:
        run(ad.submit(job_for(manifests, "seedance-2.5")))
    assert e.value.kind == "invalid" and len(seen) == 1


def test_shared_concurrency_group_across_seedance_models(manifests):
    groups = {m.limits.concurrency_group for mid, m in manifests.items() if mid.startswith("seedance")}
    assert groups == {"byteplus"}
