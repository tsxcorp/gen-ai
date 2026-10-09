"""Story 1 (panel follows model) + DoD 'no hardcoded model list' + V1 parameter tables."""
import pytest
from vhelpers import *


def resolve(client, m, params, mode=None):
    return client.post("/api/resolve", json={
        "modelId": m["id"], "mode": mode or mode_of(m), "params": {"prompt": "x", **params}})


def test_manifest_list_has_required_fields_and_v1_models(client):
    items = summaries(client)
    for s in items:
        for f in ("id", "kind", "status", "lastVerified"):
            assert f in s, (s, f)
        assert s["kind"] in ("image", "video")
    kinds = {s["kind"] for s in items}
    assert kinds == {"image", "video"}
    ids = " ".join(s["id"].lower() for s in items)
    # D6/D14: V1 = Nano Banana + Omni + Veo; Sora and Imagen are out
    assert "veo" in ids and "omni" in ids and ("banana" in ids or "image" in ids)
    assert "sora" not in ids and "imagen" not in ids


def test_unknown_manifest_is_not_found(client):
    r = client.get("/api/manifests/does-not-exist")
    assert r.status_code == 404
    assert api_error_kind(r) == "not_found"


def test_veo_1080p_forces_duration_8_with_reason(client):
    mid = need_model(client, kind="video", has=("veo",), lacks=("fast", "lite"))
    m = full_manifest(client, mid)
    dur, res = pkey(m, "duration"), pkey(m, "resolution")
    assert dur and res, "veo manifest must expose duration and resolution params"
    r = resolve(client, m, {res: "1080p", dur: 4})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["effectiveParams"][dur] == 8
    locked = {l["key"]: l.get("reason") for l in b["locked"]}
    assert dur in locked and locked[dur], "duration must be locked with a non-empty reason"


@pytest.mark.parametrize("res_value", ["1080p", "4k"])
def test_veo_high_res_forces_8(client, res_value):
    mid = need_model(client, kind="video", has=("veo",), lacks=("fast", "lite"))
    m = full_manifest(client, mid)
    dur, res = pkey(m, "duration"), pkey(m, "resolution")
    for d in (4, 6):
        r = resolve(client, m, {res: res_value, dur: d})
        assert r.status_code == 200, r.text
        assert r.json()["effectiveParams"][dur] == 8


def test_veo_720p_leaves_duration_free(client):
    mid = need_model(client, kind="video", has=("veo",), lacks=("fast", "lite"))
    m = full_manifest(client, mid)
    dur, res = pkey(m, "duration"), pkey(m, "resolution")
    for d in (4, 6, 8):
        r = resolve(client, m, {res: "720p", dur: d})
        assert r.status_code == 200, r.text
        assert r.json()["effectiveParams"][dur] == d
        assert dur not in {l["key"] for l in r.json()["locked"]}


def test_veo_duration_table(client):
    mid = need_model(client, kind="video", has=("veo",), lacks=("fast", "lite"))
    m = full_manifest(client, mid)
    assert sorted(values_of(m, pkey(m, "duration"))) == [4, 6, 8]
    assert pdef(m, pkey(m, "duration"))["default"] == 8
    assert set(values_of(m, pkey(m, "resolution"))) == {"720p", "1080p", "4k"}
    assert set(values_of(m, pkey(m, "aspectratio"))) == {"16:9", "9:16"}
    assert pkey(m, "negative") and pkey(m, "seed")  # Veo supports both


def test_veo_lite_has_no_4k(client):
    mid = need_model(client, kind="video", has=("veo", "lite"))
    m = full_manifest(client, mid)
    res = pkey(m, "resolution")
    assert "4k" not in [str(v).lower() for v in values_of(m, res)]
    r = resolve(client, m, {res: "4k"})
    if r.status_code == 200:
        b = r.json()
        assert b["errors"] or b["effectiveParams"][res] != "4k"
    else:
        assert api_error_kind(r) == "invalid"


def test_veo_last_frame_requires_first_frame(client):
    mid = need_model(client, kind="video", has=("veo",), lacks=("fast", "lite"))
    m = full_manifest(client, mid)
    assert "first_last" in m.get("modes", []) or any("last" in x for x in m.get("modes", []))
    last = pkey(m, "last")
    assert last, "manifest must expose a last-frame param"
    r = resolve(client, m, {last: "asset-that-does-not-matter"}, mode=next(x for x in m["modes"] if "last" in x))
    # no first frame/image supplied => must be rejected, never silently accepted
    ok = r.status_code >= 400 or bool(r.json().get("errors"))
    assert ok, "lastFrame without image must be invalid"


def test_flash_lite_image_only_1k(client):
    mid = need_model(client, kind="image", has=("lite",))
    m = full_manifest(client, mid)
    size = pkey(m, "imagesize", "size")
    assert [str(v) for v in values_of(m, size)] == ["1K"]
    r = resolve(client, m, {size: "2K"})
    if r.status_code == 200:
        b = r.json()
        assert b["errors"] or b["effectiveParams"][size] == "1K"
    else:
        assert api_error_kind(r) == "invalid"


def test_image_size_values_use_uppercase_K(client):
    for s in summaries(client):
        if s["kind"] != "image" or "banana" not in s["id"].lower() and "gemini" not in s["id"].lower():
            continue
        m = full_manifest(client, s["id"])
        size = pkey(m, "imagesize", "size")
        for v in values_of(m, size):
            assert not str(v).endswith("k"), f"{s['id']}: lowercase k is rejected by Vertex: {v}"


def test_image_models_have_no_negative_cfg_steps(client):
    for s in summaries(client):
        if s["kind"] == "image" and ("banana" in s["id"] or "gemini" in s["id"]):
            m = full_manifest(client, s["id"])
            for bad in ("negative", "cfg", "steps"):
                assert pkey(m, bad) is None, f"{s['id']} exposes {bad}"


def test_nano_banana_aspect_ratio_extras_only_on_2_1(client):
    extras = {"1:4", "4:1", "1:8", "8:1"}
    nb = [s["id"] for s in summaries(client) if s["kind"] == "image" and s.get("provider") == "vertex"]
    seen_with = seen_without = 0
    for i in nb:
        m = full_manifest(client, i)
        ar = pkey(m, "aspectratio")
        vals = {str(v) for v in values_of(m, ar)}
        if "2.1" in i:
            assert extras <= vals, i
            seen_with += 1
        else:
            assert not (extras & vals), i
            seen_without += 1
    if not seen_with:
        pytest.skip("no nano-banana 2.1 manifest present")


def test_omni_has_no_negative_or_seed(client):
    mid = need_model(client, kind="video", has=("omni",))
    m = full_manifest(client, mid)
    assert pkey(m, "negative") is None
    assert pkey(m, "seed") is None


def test_omni_11_offers_all_resolutions(client):
    """Corrected spec: gemini-omni-1.1-flash(-preview) = 360p, 720p (default), 1080p, 4k."""
    cands = [s["id"] for s in summaries(client)
             if s["kind"] == "video" and "omni" in s["id"].lower() and "1.1" in s["id"]]
    assert cands, "Omni 1.1 manifest missing"
    m = full_manifest(client, cands[0])
    res = pkey(m, "resolution")
    assert res, "Omni 1.1 must expose a resolution param"
    assert {str(v).lower() for v in values_of(m, res)} == {"360p", "720p", "1080p", "4k"}
    assert str(pdef(m, res)["default"]).lower() == "720p"
    for v in ("360p", "1080p", "4k"):
        r = resolve(client, m, {res: v})
        assert r.status_code == 200, r.text
        b = r.json()
        assert not b["errors"], b
        assert str(b["effectiveParams"][res]).lower() == v


def test_omni_non_11_variant_only_720p(client):
    """Corrected spec: `gemini-omni-flash-preview` (no '1.1') supports only 720p. It may be a
    separate manifest or a variant param of the Omni manifest; discovered at runtime."""
    checked = 0
    for s in summaries(client):
        if s["kind"] != "video" or "omni" not in s["id"].lower():
            continue
        m = full_manifest(client, s["id"])
        res = pkey(m, "resolution")
        if is_omni_non_11(s["id"]):
            targets = [({}, res, m)]
        else:
            vp = omni_variant_param(m)
            vals = [v for v in (vp or {}).get("values", []) if is_omni_non_11(v)]
            targets = [({vp["key"]: v}, res, m) for v in vals]
        for extra, res, m in targets:
            checked += 1
            if not extra:  # separate manifest: offered set must be exactly 720p
                assert [str(v).lower() for v in values_of(m, res)] == ["720p"]
            r = resolve(client, m, {**extra, res: "1080p"})
            if r.status_code == 200:
                b = r.json()
                assert b["errors"] or b["effectiveParams"][res] == "720p"
            else:
                assert api_error_kind(r) == "invalid"
    if not checked:
        pytest.skip("non-1.1 Omni variant (gemini-omni-flash-preview) not exposed by the app")


def test_omni_aspect_and_audio(client):
    mid = need_model(client, kind="video", has=("omni",))
    m = full_manifest(client, mid)
    assert set(values_of(m, pkey(m, "aspectratio"))) == {"16:9", "9:16"}
    assert pdef(m, pkey(m, "aspectratio"))["default"] == "16:9"


def test_manifests_carry_governance_fields(client):
    for s in summaries(client):
        m = full_manifest(client, s["id"])
        assert m["lastVerified"], s["id"]
        assert m["status"] in ("ga", "preview", "deprecated"), s["id"]
        assert m.get("pricing"), f"{s['id']} has no pricing: cost estimate impossible"
    veo = find_model(client, kind="video", has=("veo",), lacks=("fast", "lite"))
    if veo:
        assert full_manifest(client, veo).get("sunsetDate") == "2026-11-17"


def test_resolve_unknown_model_is_error(client):
    r = client.post("/api/resolve", json={"modelId": "nope", "mode": "t2v", "params": {}})
    assert r.status_code in (400, 404, 422)
    assert api_error_kind(r) in ("invalid", "not_found")


def test_switching_model_keeps_prompt_contract(client):
    """DoD: switching model keeps the prompt. Server side: resolve of the same prompt on two
    different models echoes the same prompt in effectiveParams."""
    ids = [s["id"] for s in summaries(client)][:2]
    for i in ids:
        m = full_manifest(client, i)
        r = client.post("/api/resolve", json={"modelId": i, "mode": mode_of(m),
                                              "params": {"prompt": "keep me"}})
        assert r.status_code == 200, r.text
        assert "keep me" in str(r.json()["effectiveParams"])
