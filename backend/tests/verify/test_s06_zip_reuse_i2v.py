"""Stories 6 (zip/download), 7 (reuse/vary), 8 (image -> video)."""
import hashlib
import json

from vhelpers import *


def make_assets(client, n=2):
    mid = find_model(client, kind="image")
    m = full_manifest(client, mid)
    r = post_batch(client, make_request(m), make_sweep(n))
    assert r.status_code in (200, 201, 202), r.text
    done = wait_batch(client, r.json()["batchId"])
    return done, m


def test_zip_contains_original_bytes_and_json_sidecar_per_asset(client):
    done, m = make_assets(client, 3)
    assets = has_asset_ids(done)
    assert len(assets) == 3
    z = client.post("/api/zip", json={"assetIds": [a["id"] for a in assets]})
    assert z.status_code == 200, z.text
    members = zip_members(z.content)
    digests = {hashlib.sha256(v).hexdigest(): n for n, v in members.items() if not n.endswith(".json")}
    for a in assets:
        assert a["sha256"] in digests, "asset bytes missing or re-encoded in ZIP"
        orig = client.get(f"/api/assets/{a['id']}").content
        assert hashlib.sha256(orig).hexdigest() == a["sha256"]
    jsons = {n: json.loads(v) for n, v in members.items() if n.endswith(".json")}
    assert len(jsons) == 3, "exactly one JSON params sidecar per asset"
    for a in assets:
        assert any(n.startswith(a["id"]) or a["id"] in n for n in jsons), f"no <id>.json for {a['id']}"
    for body in jsons.values():
        assert m["id"] in json.dumps(body), "sidecar must identify model/params"
        assert "prompt" in json.dumps(body)


def test_zip_sidecar_matches_job_params(client):
    done, m = make_assets(client, 1)
    j = done["jobs"][0]
    a = j["assets"][0]
    members = zip_members(client.post("/api/zip", json={"assetIds": [a["id"]]}).content)
    side = json.loads(next(v for n, v in members.items() if n.endswith(".json")))
    assert j["requestedParams"]["prompt"] in json.dumps(side)
    assert j["model"] in json.dumps(side)
    # every effective param value that is a scalar appears in the sidecar
    for k, v in j["effectiveParams"].items():
        if isinstance(v, (str, int, float, bool)) and k != "prompt":
            assert k in json.dumps(side) and str(v).lower() in json.dumps(side).lower(), (k, v)


def test_zip_unknown_asset_not_found(client):
    r = client.post("/api/zip", json={"assetIds": ["nope"]})
    assert r.status_code == 404 and api_error_kind(r) == "not_found"


def test_zip_does_not_leak_into_unselected(client):
    done, _ = make_assets(client, 2)
    assets = has_asset_ids(done)
    members = zip_members(client.post("/api/zip", json={"assetIds": [assets[0]["id"]]}).content)
    shas = {hashlib.sha256(v).hexdigest() for n, v in members.items() if not n.endswith(".json")}
    assert assets[0]["sha256"] in shas
    assert len([n for n in members if n.endswith(".json")]) == 1


def test_no_output_lost_within_session(client):
    done, _ = make_assets(client, 4)
    for a in has_asset_ids(done):
        assert client.get(f"/api/assets/{a['id']}").status_code == 200


def test_reuse_reloads_params_and_edit_makes_new_job(client):
    mid = find_model(client, kind="image")
    m = full_manifest(client, mid)
    done, _ = run_one(client, mid, prompt="orig prompt")
    first = done["jobs"][0]
    # Reuse: requestedParams are all that the panel needs, resubmitting gives a NEW job
    req = {"modelId": first["model"], "params": first["requestedParams"]}
    if mode_of(m):
        req["mode"] = mode_of(m)
    r2 = post_batch(client, req)
    assert r2.status_code in (200, 201, 202), r2.text
    second = wait_batch(client, r2.json()["batchId"])["jobs"][0]
    assert second["id"] != first["id"]
    assert second["effectiveParams"] == first["effectiveParams"]
    # Vary one field
    changed = dict(first["requestedParams"], prompt="edited prompt")
    req["params"] = changed
    r3 = post_batch(client, req)
    third = wait_batch(client, r3.json()["batchId"])["jobs"][0]
    assert third["id"] not in (first["id"], second["id"])
    assert third["effectiveParams"]["prompt"] == "edited prompt"
    # the original job is untouched
    assert client.get(f"/api/batches/{first['batchId']}").json()["jobs"][0]["requestedParams"]["prompt"] == "orig prompt"


def test_image_to_video_first_frame_resolves(client):
    """Story 8: an image asset can fill first_frame of a video model and the mode is accepted."""
    mid_v = need_model(client, kind="video", has=("veo",), lacks=("fast", "lite"))
    mv = full_manifest(client, mid_v)
    done, _ = make_assets(client, 1)
    asset = has_asset_ids(done)[0]
    first = pkey(mv, "first", "image", exclude=("last",))
    assert first, "video manifest must expose a first-frame/image param"
    mode = next((x for x in mv["modes"] if x in ("i2v", "image_to_video")), None)
    assert mode, f"no image-to-video mode in {mv['modes']}"
    r = client.post("/api/resolve", json={"modelId": mid_v, "mode": mode,
                                          "params": {"prompt": "animate", first: asset["id"]}})
    assert r.status_code == 200, r.text
    assert not r.json()["errors"], r.json()
    assert r.json()["effectiveParams"][first] == asset["id"]


def test_first_and_last_frame_accepted_together(client):
    mid_v = need_model(client, kind="video", has=("veo",), lacks=("fast", "lite"))
    mv = full_manifest(client, mid_v)
    done, _ = make_assets(client, 2)
    a, b = has_asset_ids(done)[:2]
    first, last = pkey(mv, "first", "image", exclude=("last",)), pkey(mv, "last")
    mode = next(x for x in mv["modes"] if "last" in x)
    r = client.post("/api/resolve", json={"modelId": mid_v, "mode": mode,
                                          "params": {"prompt": "x", first: a["id"], last: b["id"]}})
    assert r.status_code == 200, r.text
    assert not r.json()["errors"]
