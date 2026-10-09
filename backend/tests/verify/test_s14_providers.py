"""Multi-provider (D6b): US13-US16, invariants 1, 5, 10, 12, 13, 25, 26 (docs/architecture.md
'Cập nhật: đa provider'). Spec-blind, HTTP only.

Conventions (same as test_s13): demo mode via conftest, Host pinned to `localhost`.
Param keys / model ids are discovered at runtime; a test skips only when a documented model is
genuinely missing (see `need_provider_model`).
"""
import copy
import json
import logging
import os
import re
import socket
import stat
import sys
from pathlib import Path

import pytest
from vhelpers import *

PROVIDERS = ("vertex", "openai", "byteplus")
OK = (200, 201, 204)

OPENAI_KEY = "sk-proj-S14OPENAIKEY" + "Q9" * 12
OPENAI_KEY2 = "sk-proj-S14OPENAIKEY2" + "R7" * 12
BP_KEY = "bpkey-S14BYTEPLUSKEY" + "W5" * 12
BP_KEY2 = "bpkey-S14BYTEPLUSKEY2" + "V3" * 12


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


# ------------------------------------------------------------------ helpers
def norm(s):
    return str(s).lower().replace(".", "-").replace("_", "-")


def prov_of(s):
    return s.get("provider")


def models_of(c, provider):
    return [s for s in summaries(c) if prov_of(s) == provider]


def need_provider_model(c, provider, *, has=(), lacks=()):
    for s in models_of(c, provider):
        i = norm(s["id"])
        if all(h in i for h in has) and not any(x in i for x in lacks):
            return s["id"]
    pytest.skip(f"documented model not present: provider={provider} has={has} lacks={lacks}; "
                f"present for provider: {[s['id'] for s in models_of(c, provider)]}")


def openai_models(c):
    return [s["id"] for s in models_of(c, "openai")]


def seedance(c, kind):
    """kind: '2.5' | '2.0' | 'fast' | 'mini'"""
    if kind == "2.5":
        return need_provider_model(c, "byteplus", has=("seedance", "2-5"))
    if kind == "fast":
        return need_provider_model(c, "byteplus", has=("seedance", "fast"))
    if kind == "mini":
        return need_provider_model(c, "byteplus", has=("seedance", "mini"))
    return need_provider_model(c, "byteplus", has=("seedance", "2-0"), lacks=("fast", "mini"))


def sa(tag="S"):
    return fake_service_account(tag)


def put_vertex(c, tag="S", **over):
    body = {"authMethod": "service_account", "projectId": "demo-proj", "location": "global",
            "json": sa(tag)[0]}
    body.update(over)
    return c.put("/api/providers/vertex", json=body)


def put_openai(c, key=OPENAI_KEY, **over):
    body = {"apiKey": key}
    body.update(over)
    return c.put("/api/providers/openai", json=body)


def put_bp(c, key=BP_KEY, **over):
    body = {"apiKey": key}
    body.update(over)
    return c.put("/api/providers/byteplus", json=body)


def state_path(c):
    return c.data_dir / "providers.json"


def state_text(c):
    p = state_path(c)
    return p.read_text() if p.exists() else ""


def assert_mode_0600(c):
    p = state_path(c)
    if p.exists():
        assert stat.S_IMODE(p.stat().st_mode) == 0o600, oct(p.stat().st_mode)


def providers(c):
    r = c.get("/api/providers")
    assert r.status_code == 200, r.text
    return r.json()


def configure_all(c, tag="S"):
    assert put_vertex(c, tag).status_code in OK
    assert put_openai(c).status_code in OK
    assert put_bp(c).status_code in OK


def rejected(r):
    return r.status_code == 400 and api_error_kind(r) == "invalid"


# ------------------------------------------------------------------ GET /api/providers shape
def test_get_providers_unconfigured_shape_for_all_three(c):
    g = providers(c)
    assert set(PROVIDERS) <= set(g), g
    v, o, b = g["vertex"], g["openai"], g["byteplus"]
    for p in (v, o, b):
        assert p["configured"] is False and p["hasKey"] is False, p
    assert v["authMethod"] is None
    for k in ("projectId", "location", "gcsBucket"):
        assert k in v, v
    for k in ("organization", "project"):
        assert k in o, o
    assert "region" in b


def test_get_providers_after_configure_masks_and_reports(c):
    sa_, secrets = sa("M")
    assert put_vertex(c, "M", location="us-central1", gcsBucket="my-bucket-1").status_code in OK
    assert put_openai(c, organization="org-abc", project="proj_xyz").status_code in OK
    assert put_bp(c, region="ap-southeast").status_code in OK
    g = providers(c)
    assert g["vertex"]["configured"] is True and g["vertex"]["hasKey"] is True
    assert g["vertex"]["authMethod"] == "service_account"
    assert g["vertex"]["projectId"] == "demo-proj" and g["vertex"]["location"] == "us-central1"
    assert g["vertex"]["gcsBucket"] == "my-bucket-1"
    assert g["openai"]["configured"] is True and g["openai"]["hasKey"] is True
    assert g["openai"]["organization"] == "org-abc" and g["openai"]["project"] == "proj_xyz"
    assert g["byteplus"]["configured"] is True and g["byteplus"]["hasKey"] is True
    assert g["byteplus"]["region"] == "ap-southeast"
    raw = c.get("/api/providers").text
    assert not contains_any(raw, secrets + [OPENAI_KEY, BP_KEY])
    assert "apiKey" not in raw and "api_key" not in raw and "private_key" not in raw
    assert "BEGIN PRIVATE KEY" not in raw


def test_byteplus_region_defaults_to_ap_southeast(c):
    assert put_bp(c).status_code in OK
    assert providers(c)["byteplus"]["region"] == "ap-southeast"


# ------------------------------------------------------------------ OpenAI validation
def test_openai_api_key_required_first_time(c):
    for body in ({}, {"apiKey": ""}, {"apiKey": "   "}, {"organization": "org-x"}):
        r = c.put("/api/providers/openai", json=body)
        assert rejected(r), (body, r.status_code, r.text)
    g = providers(c)["openai"]
    assert g["configured"] is False and g["hasKey"] is False
    assert "org-x" not in state_text(c)


def test_openai_blank_key_keeps_existing_and_updates_other_fields(c):
    assert put_openai(c).status_code in OK
    for blank in ("", None):
        body = {"organization": "org-new"}
        if blank is not None:
            body["apiKey"] = blank
        r = c.put("/api/providers/openai", json=body)
        assert r.status_code in OK, (body, r.text)
    g = providers(c)["openai"]
    assert g["hasKey"] is True and g["configured"] is True and g["organization"] == "org-new"
    assert OPENAI_KEY in state_text(c), "blank key must keep the stored key"


def test_openai_new_key_replaces_old(c):
    assert put_openai(c).status_code in OK
    assert put_openai(c, OPENAI_KEY2).status_code in OK
    t = state_text(c)
    assert OPENAI_KEY2 in t and OPENAI_KEY not in t


# ------------------------------------------------------------------ BytePlus validation
BAD_REGIONS = ["evil.example/x?", "evil.example", "a.b", "ap-southeast.evil.example/", "ap-southeast/../x",
               "ap southeast", "AP-SOUTHEAST", "ap_southeast", "x@evil.example", "ap-southeast#",
               "ap-southeast?x=1", "http://evil.example", "//evil.example", "ap-southeast:443@evil.example",
               "ap-southeast\r\nHost: evil.example", "-", "ap-southeast.", "ap-southeast/", "a" * 200,
               "bytepluses.com", "..", "ap-southeast%2f.evil.example"]


@pytest.mark.parametrize("region", BAD_REGIONS)
def test_byteplus_hostile_region_rejected_not_stored(c, region):
    r = put_bp(c, region=region)
    assert rejected(r), (region, r.status_code, r.text)
    assert "evil.example" not in state_text(c)
    assert "evil.example" not in c.get("/api/providers").text
    assert BP_KEY not in r.text, "validation error must not echo the key"
    assert providers(c)["byteplus"]["configured"] is False


def test_byteplus_rejected_put_keeps_previous_config_and_key(c):
    assert put_bp(c, region="ap-southeast").status_code in OK
    before = state_text(c)
    r = c.put("/api/providers/byteplus", json={"region": "evil.example/x?"})
    assert rejected(r), r.text
    assert state_text(c) == before
    assert providers(c)["byteplus"]["region"] == "ap-southeast"


def test_byteplus_api_key_required_first_time(c):
    for body in ({}, {"apiKey": ""}, {"region": "ap-southeast"}):
        assert rejected(c.put("/api/providers/byteplus", json=body)), body
    assert providers(c)["byteplus"]["configured"] is False


def test_byteplus_blank_key_keeps_existing(c):
    assert put_bp(c).status_code in OK
    assert c.put("/api/providers/byteplus", json={"apiKey": "", "region": "ap-southeast"}).status_code in OK
    assert providers(c)["byteplus"]["hasKey"] is True
    assert BP_KEY in state_text(c)


# ------------------------------------------------------------------ Vertex validation (extended)
def test_vertex_adc_needs_no_key(c):
    r = c.put("/api/providers/vertex", json={"authMethod": "adc", "projectId": "demo-proj", "location": "global"})
    assert r.status_code in OK, r.text
    g = providers(c)["vertex"]
    assert g["configured"] is True and g["authMethod"] == "adc"
    assert g["projectId"] == "demo-proj"
    assert "private_key" not in state_text(c)


def test_vertex_service_account_without_key_first_time_rejected(c):
    r = c.put("/api/providers/vertex", json={"authMethod": "service_account", "projectId": "demo-proj",
                                             "location": "global"})
    assert rejected(r), (r.status_code, r.text)
    assert providers(c)["vertex"]["configured"] is False


@pytest.mark.parametrize("loc", ["evil.example/x?", "us-central1.evil.example/", "a.b", "GLOBAL", "us_central1", ""])
def test_vertex_adc_still_validates_location(c, loc):
    r = c.put("/api/providers/vertex", json={"authMethod": "adc", "projectId": "demo-proj", "location": loc})
    assert rejected(r), (loc, r.status_code)
    assert "evil.example" not in state_text(c)


@pytest.mark.parametrize("pid", ["A", "abcd", "UPPER-case-proj", "evil.example/x", "proj-ends-dash-", "x" * 40])
def test_vertex_adc_still_validates_project_id(c, pid):
    r = c.put("/api/providers/vertex", json={"authMethod": "adc", "projectId": pid, "location": "global"})
    assert rejected(r), (pid, r.status_code)
    assert pid not in state_text(c)


def test_vertex_unknown_auth_method_rejected(c):
    r = c.put("/api/providers/vertex", json={"authMethod": "password", "projectId": "demo-proj",
                                             "location": "global", "json": sa("U")[0]})
    assert rejected(r), r.status_code


def test_unknown_provider_id_is_not_accepted(c):
    for method in ("put", "post", "delete"):
        path = "/api/providers/nope" + ("/test" if method == "post" else "")
        r = getattr(c, method)(path, **({"json": {"apiKey": OPENAI_KEY}} if method == "put" else {}))
        assert r.status_code in (400, 404), (method, r.status_code)
    assert "nope" not in state_text(c)
    assert OPENAI_KEY not in state_text(c)


# ------------------------------------------------------------------ providers.json mode 0600
def test_providers_json_0600_after_every_put_and_delete(c):
    steps = [lambda: put_vertex(c), lambda: put_openai(c), lambda: put_bp(c),
             lambda: put_openai(c, OPENAI_KEY2), lambda: put_bp(c, region="ap-southeast"),
             lambda: c.delete("/api/providers/openai"), lambda: c.delete("/api/providers/byteplus"),
             lambda: c.put("/api/providers/vertex", json={"authMethod": "adc", "projectId": "demo-proj",
                                                           "location": "global"}),
             lambda: c.delete("/api/providers/vertex")]
    for i, step in enumerate(steps):
        r = step()
        assert r.status_code in OK, (i, r.status_code, r.text)
        assert_mode_0600(c)


def test_providers_json_0600_even_with_permissive_umask(mk):
    old = os.umask(0o000)
    try:
        c = mk()
        assert put_openai(c).status_code in OK
        assert state_path(c).exists()
        assert stat.S_IMODE(state_path(c).stat().st_mode) == 0o600
        assert c.delete("/api/providers/openai").status_code in OK
        assert_mode_0600(c)
    finally:
        os.umask(old)


def test_loose_providers_json_is_repaired_or_refused_on_start(mk, make_client):
    c1 = mk()
    assert put_openai(c1).status_code in OK
    p = state_path(c1)
    os.chmod(p, 0o644)
    try:
        c2 = mk(data_dir=c1.data_dir, tmp_dir=c1.tmp_dir)
    except Exception:
        return  # refusing to start is allowed (invariant 10)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600, "loose providers.json must be repaired on start"


# ------------------------------------------------------------------ isolation between providers (inv 26)
def test_put_of_one_provider_leaves_others_untouched(c):
    configure_all(c, "I")
    _, vsecrets = sa("I")
    before = providers(c)
    assert put_openai(c, OPENAI_KEY2, organization="org-2").status_code in OK
    after = providers(c)
    assert after["vertex"] == before["vertex"] and after["byteplus"] == before["byteplus"]
    t = state_text(c)
    assert BP_KEY in t and all(s in t for s in vsecrets) and OPENAI_KEY2 in t
    before = after
    assert put_bp(c, BP_KEY2, region="ap-southeast").status_code in OK
    after = providers(c)
    assert after["vertex"] == before["vertex"] and after["openai"] == before["openai"]
    assert OPENAI_KEY2 in state_text(c)


def test_delete_one_provider_leaves_others_untouched(c):
    configure_all(c, "J")
    _, vsecrets = sa("J")
    before = providers(c)
    for victim in PROVIDERS:
        c2 = c
        r = c2.delete(f"/api/providers/{victim}")
        assert r.status_code in OK, (victim, r.status_code, r.text)
        g = providers(c2)
        assert g[victim]["configured"] is False and g[victim]["hasKey"] is False, g[victim]
        for other in PROVIDERS:
            if other != victim:
                assert g[other] == before[other], (victim, other)
        assert_mode_0600(c2)
        # re-create the victim so the next iteration starts from the full set
        {"vertex": lambda: put_vertex(c2, "J"), "openai": lambda: put_openai(c2),
         "byteplus": lambda: put_bp(c2)}[victim]()
        before = providers(c2)


def test_delete_removes_that_key_material_only(c):
    configure_all(c, "K")
    _, vsecrets = sa("K")
    assert c.delete("/api/providers/openai").status_code in OK
    t = state_text(c)
    assert OPENAI_KEY not in t
    assert BP_KEY in t and all(s in t for s in vsecrets)
    assert c.delete("/api/providers/byteplus").status_code in OK
    t = state_text(c)
    assert BP_KEY not in t and all(s in t for s in vsecrets)
    assert c.delete("/api/providers/vertex").status_code in OK
    assert not contains_any(state_text(c), vsecrets + [OPENAI_KEY, BP_KEY])


def test_rejected_put_of_one_provider_does_not_disturb_others(c):
    configure_all(c, "L")
    before_state, before = state_text(c), providers(c)
    assert rejected(put_bp(c, region="evil.example/x?"))
    assert c.put("/api/providers/openai", json={"apiKey": OPENAI_KEY2, "organization": ["x"]}).status_code == 400
    assert rejected(put_vertex(c, "L", location="evil.example/x?"))
    assert providers(c) == before
    assert state_text(c) == before_state


def test_delete_then_get_shows_unconfigured_and_persists_across_restart(mk):
    c1 = mk()
    assert put_openai(c1).status_code in OK
    assert providers(c1)["openai"]["configured"] is True
    assert c1.delete("/api/providers/openai").status_code in OK
    g = providers(c1)["openai"]
    assert g["configured"] is False and g["hasKey"] is False
    assert OPENAI_KEY not in state_text(c1)
    c2 = mk(data_dir=c1.data_dir, tmp_dir=c1.tmp_dir)
    assert providers(c2)["openai"]["configured"] is False


def test_configured_state_persists_across_restart_masked(mk):
    c1 = mk()
    configure_all(c1, "R")
    _, vs = sa("R")
    c2 = mk(data_dir=c1.data_dir, tmp_dir=c1.tmp_dir)
    g = providers(c2)
    for p in PROVIDERS:
        assert g[p]["configured"] is True and g[p]["hasKey"] is True
    assert not contains_any(c2.get("/api/providers").content, vs + [OPENAI_KEY, BP_KEY])


# ------------------------------------------------------------------ POST /api/providers/{id}/test (demo)
@pytest.mark.parametrize("pid", PROVIDERS)
def test_provider_test_endpoint_ok_in_demo(c, pid):
    {"vertex": lambda: put_vertex(c, "T"), "openai": lambda: put_openai(c), "byteplus": lambda: put_bp(c)}[pid]()
    r = c.post(f"/api/providers/{pid}/test")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["ok"] is True and "message" in b, b
    assert not contains_any(r.content, [OPENAI_KEY, BP_KEY] + sa("T")[1])


@pytest.mark.parametrize("pid", PROVIDERS)
def test_provider_test_endpoint_does_not_modify_stored_state(c, pid):
    configure_all(c, "T")
    before = state_text(c)
    c.post(f"/api/providers/{pid}/test")
    assert state_text(c) == before
    assert_mode_0600(c)


# ------------------------------------------------------------------ Origin / Host / content-type guard on new routes (inv 12)
@pytest.mark.parametrize("pid", PROVIDERS)
def test_inv12_provider_writes_reject_foreign_origin_and_have_no_effect(c, pid):
    evil = {"origin": "http://evil.example"}
    body = {"vertex": {"authMethod": "adc", "projectId": "demo-proj", "location": "global"},
            "openai": {"apiKey": OPENAI_KEY}, "byteplus": {"apiKey": BP_KEY}}[pid]
    assert c.put(f"/api/providers/{pid}", json=body, headers=evil).status_code in (400, 403)
    assert c.post(f"/api/providers/{pid}/test", headers=evil).status_code in (400, 403)
    assert c.delete(f"/api/providers/{pid}", headers=evil).status_code in (400, 403)
    assert providers(c)[pid]["configured"] is False
    assert not state_text(c).strip() or OPENAI_KEY not in state_text(c)


def test_inv12_put_provider_requires_json_content_type(c):
    for ct in ({"content-type": "text/plain"}, {"content-type": "application/x-www-form-urlencoded"}, {}):
        r = c.put("/api/providers/openai", content=json.dumps({"apiKey": OPENAI_KEY}).encode(), headers=ct)
        assert r.status_code in (400, 415), (ct, r.status_code)
    assert providers(c)["openai"]["configured"] is False


def test_inv12_foreign_host_cannot_read_new_provider_shape(c):
    configure_all(c, "H")
    r = c.get("/api/providers", headers={"host": "evil.example"})
    assert r.status_code in (400, 403, 421)
    assert "hasKey" not in r.text


# ------------------------------------------------------------------ keys never leak anywhere (US15, inv 1)
def test_us15_no_provider_key_in_responses_sse_zip_logs_or_files(c, caplog, capsys):
    caplog.set_level(logging.DEBUG)
    _, vs = sa("Z")
    secrets = vs + [OPENAI_KEY, OPENAI_KEY2, BP_KEY, BP_KEY2]
    assert put_vertex(c, "Z").status_code in OK
    assert put_openai(c).status_code in OK
    assert put_bp(c).status_code in OK
    assert put_openai(c, OPENAI_KEY2).status_code in OK  # rotate
    assert put_bp(c, BP_KEY2).status_code in OK
    for pid in PROVIDERS:
        c.post(f"/api/providers/{pid}/test")
    # invalid PUTs that carry keys must not echo them
    c.put("/api/providers/byteplus", json={"apiKey": BP_KEY, "region": "evil.example/x?"})
    c.put("/api/providers/openai", json={"apiKey": OPENAI_KEY, "organization": 123})
    c.put("/api/providers/vertex", json={"projectId": "", "json": sa("Z")[0]})
    c.get("/api/providers")
    c.get("/api/manifests")
    assets = []
    for s in summaries(c):
        if s.get("provider") in PROVIDERS:
            done, _ = run_one(c, s["id"])
            assets += has_asset_ids(done)
            run_one(c, s["id"], prompt="[fail] x")
            run_one(c, s["id"], prompt="[blocked] x")
    assert assets
    z = c.post("/api/zip", json={"assetIds": [a["id"] for a in assets]})
    assert z.status_code == 200, z.text[:200]
    members = zip_members(z.content)
    sidecars = [n for n in members if n.endswith(".json")]
    assert sidecars, "zip must carry sidecars"
    for n, data in members.items():
        assert not contains_any(data, secrets), f"key in zip member {n}"
    ev = c.get("/api/events")
    assert not contains_any(ev.content, secrets)
    for blob in c.seen:
        assert not contains_any(blob, secrets), "provider key appeared in an HTTP response/header"
    assert not contains_any(caplog.text, secrets), "key material in logs"
    out = capsys.readouterr()
    assert not contains_any(out.out + out.err, secrets)
    for d, _, fs in os.walk(c.tmp_dir):
        for f in fs:
            assert not contains_any(Path(d, f).read_bytes(), secrets), f"key in temp file {f}"
    for d, _, fs in os.walk(c.data_dir):
        for f in fs:
            if f != "providers.json":
                assert not contains_any(Path(d, f).read_bytes(), secrets), f"key in {f}"
    # rotation: old keys are gone even from providers.json
    t = state_text(c)
    assert OPENAI_KEY not in t and BP_KEY not in t


def test_us15_job_requested_and_effective_params_carry_no_key(c):
    configure_all(c, "P")
    for pid in ("openai", "byteplus"):
        mid = models_of(c, pid)[0]["id"]
        done, _ = run_one(c, mid)
        assert not contains_any(json.dumps(done), [OPENAI_KEY, BP_KEY])


# ------------------------------------------------------------------ manifests: provider + configured
def test_manifest_list_entries_carry_provider_and_configured_demo(c):
    items = summaries(c)
    seen = set()
    for s in items:
        assert s.get("provider") in PROVIDERS, s
        assert s.get("configured") is True, f"demo mode: all configured, got {s}"
        seen.add(s["provider"])
    assert seen == set(PROVIDERS), seen


def test_openai_models_exist(c):
    ids = [norm(i) for i in openai_models(c)]
    if not ids:
        pytest.skip("no manifest with provider=openai present")
    for s in ("sunburst", "flare"):
        assert any("gpt-image-2-5" in i and s in i for i in ids), (s, ids)
    for s in models_of(c, "openai"):
        assert s["kind"] == "image"


def test_byteplus_models_exist(c):
    ids = [norm(s["id"]) for s in models_of(c, "byteplus")]
    if not ids:
        pytest.skip("no manifest with provider=byteplus present")
    assert any("2-5" in i for i in ids), ids
    assert any("2-0" in i and "fast" not in i and "mini" not in i for i in ids), ids
    assert any("fast" in i for i in ids), ids
    assert any("mini" in i for i in ids), ids
    for s in models_of(c, "byteplus"):
        assert s["kind"] == "video"


def test_new_manifests_flag_unverified_live_and_have_full_manifest(c):
    for pid in ("openai", "byteplus"):
        for s in models_of(c, pid):
            m = full_manifest(c, s["id"])
            assert m.get("provider", pid) == pid
            vl = m.get("verifiedLive", s.get("verifiedLive"))
            assert vl is False, f"{s['id']}: not yet called live => verifiedLive must be false (got {vl!r})"
            assert m.get("limits", {}).get("maxConcurrent", 1) >= 1


def test_default_max_concurrent_per_provider(c):
    expect = {"openai": 5, "byteplus": 3}
    for pid, n in expect.items():
        for s in models_of(c, pid):
            lim = full_manifest(c, s["id"]).get("limits", {})
            if "maxConcurrent" in lim:
                assert lim["maxConcurrent"] == n, (s["id"], lim)


# ------------------------------------------------------------------ not_configured (US13) in NON-demo mode
@pytest.fixture
def nondemo(tmp_path, monkeypatch):
    """App started WITHOUT AIGEN_DEMO and with no providers.json. Any socket use is recorded and refused,
    so the tests also prove that no adapter reached the network."""
    from conftest import ENV_KEYS, RecordingClient

    data, tmpd = tmp_path / "nd_data", tmp_path / "nd_tmp"
    data.mkdir()
    tmpd.mkdir()
    for k in ENV_KEYS + ["GOOGLE_APPLICATION_CREDENTIALS", "OPENAI_API_KEY", "ARK_API_KEY", "BYTEPLUS_API_KEY"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AIGEN_DATA_DIR", str(data))
    monkeypatch.setenv("AIGEN_TMP_DIR", str(tmpd))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    calls = []
    real_connect = socket.socket.connect

    def guard_connect(self, addr, *a, **kw):
        if self.family == getattr(socket, "AF_UNIX", -1):
            return real_connect(self, addr, *a, **kw)
        calls.append(("connect", addr))
        raise OSError("network disabled by test")

    def guard_gai(host, *a, **kw):
        calls.append(("getaddrinfo", host))
        raise socket.gaierror("network disabled by test")

    monkeypatch.setattr(socket.socket, "connect", guard_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", lambda self, addr, *a: calls.append(("connect_ex", addr)) or 111)
    monkeypatch.setattr(socket, "getaddrinfo", guard_gai)
    from app.main import create_app

    cl = RecordingClient(create_app())
    cl.__enter__()
    cl.headers["host"] = "localhost"
    cl.data_dir, cl.tmp_dir, cl.net_calls = data, tmpd, calls
    yield cl
    try:
        cl.__exit__(None, None, None)
    except Exception:
        pass


def nd_job_ids(cl):
    return re.findall(r'"id"\s*:\s*"([^"]+)"', cl.get("/api/events").text)


@pytest.mark.parametrize("provider", ["openai", "byteplus"])
def test_us13_unconfigured_provider_model_batch_is_not_configured_and_creates_no_job(nondemo, provider):
    cl = nondemo
    mid = models_of(cl, provider)[0]["id"] if models_of(cl, provider) else None
    if mid is None:
        pytest.skip(f"no {provider} model present")
    m = full_manifest(cl, mid)
    before = nd_job_ids(cl)
    for confirm in (True, False):
        r = post_batch(cl, make_request(m), make_sweep(2), confirm=confirm)
        assert r.status_code == 400 and api_error_kind(r) == "not_configured", (confirm, r.status_code, r.text)
        assert "message" in r.json()["error"]
    assert nd_job_ids(cl) == before, "no job may be created for an unconfigured provider"
    assert not cl.net_calls, f"adapter/network was touched: {cl.net_calls}"


def test_us13_unconfigured_vertex_model_also_not_configured(nondemo):
    cl = nondemo
    vs = models_of(cl, "vertex")
    if not vs:
        pytest.skip("no vertex model present")
    m = full_manifest(cl, vs[0]["id"])
    r = post_batch(cl, make_request(m), make_sweep(1))
    assert r.status_code == 400 and api_error_kind(r) == "not_configured", (r.status_code, r.text)
    assert not cl.net_calls, cl.net_calls


def test_us13_manifest_list_flags_unconfigured_in_non_demo(nondemo):
    for s in summaries(nondemo):
        assert s["provider"] in PROVIDERS
        assert s["configured"] is False, s
    assert not nondemo.net_calls


def test_us13_estimate_still_works_for_unconfigured_provider(nondemo):
    cl = nondemo
    for pid in ("openai", "byteplus"):
        ms = models_of(cl, pid)
        if not ms:
            continue
        m = full_manifest(cl, ms[0]["id"])
        r = estimate(cl, make_request(m), make_sweep(3))
        assert r.status_code == 200, (pid, r.text)
        b = r.json()
        assert b["jobCount"] == 3 and b["minUsd"] <= b["maxUsd"]
    assert not cl.net_calls


def test_us13_resolve_still_works_for_unconfigured_provider(nondemo):
    cl = nondemo
    for pid in ("openai", "byteplus"):
        ms = models_of(cl, pid)
        if ms:
            m = full_manifest(cl, ms[0]["id"])
            r = cl.post("/api/resolve", json={"modelId": m["id"], "mode": mode_of(m), "params": {"prompt": "x"}})
            assert r.status_code == 200, r.text


def test_us13_configuring_one_provider_unlocks_only_that_provider_without_network(nondemo):
    cl = nondemo
    assert put_openai(cl).status_code in OK
    cfg = {s["id"]: s["configured"] for s in summaries(cl)}
    for s in summaries(cl):
        assert s["configured"] is (s["provider"] == "openai"), s
    # byteplus still refused
    bs = models_of(cl, "byteplus")
    if bs:
        r = post_batch(cl, make_request(full_manifest(cl, bs[0]["id"])), make_sweep(1))
        assert r.status_code == 400 and api_error_kind(r) == "not_configured"
    assert not cl.net_calls, f"PUT/GET/manifests must not touch the network: {cl.net_calls}"
    assert cfg


def test_us13_deleting_a_provider_makes_its_models_not_configured_again(nondemo):
    cl = nondemo
    assert put_bp(cl).status_code in OK
    assert all(s["configured"] for s in models_of(cl, "byteplus"))
    assert cl.delete("/api/providers/byteplus").status_code in OK
    assert not any(s["configured"] for s in models_of(cl, "byteplus"))
    bs = models_of(cl, "byteplus")
    if bs:
        r = post_batch(cl, make_request(full_manifest(cl, bs[0]["id"])), make_sweep(1))
        assert api_error_kind(r) == "not_configured"
    assert not cl.net_calls


def test_us13_non_demo_has_no_providers_json_until_configured(nondemo):
    assert not state_path(nondemo).exists() or not state_text(nondemo).strip() or \
        not contains_any(state_text(nondemo), [OPENAI_KEY, BP_KEY])


# ------------------------------------------------------------------ US16 Seedance constraints via /api/resolve
def res_(c, m, params, mode=None):
    return c.post("/api/resolve", json={"modelId": m["id"], "mode": mode or mode_of(m),
                                        "params": {"prompt": "x", **params}})


def is_refused_or_coerced(r, key, bad):
    """True if the server did not let `bad` through for `key`."""
    if r.status_code >= 400:
        return True
    b = r.json()
    if b.get("errors"):
        return True
    return b["effectiveParams"].get(key) != bad


def frame_assets(c, n=2):
    mid = find_model(c, kind="image")
    out = []
    for i in range(n):
        done, _ = run_one(c, mid, prompt=f"frame {i}")
        out += has_asset_ids(done)
    assert len(out) >= n
    return out


def frame_modes(m):
    return [x for x in m.get("modes", []) if "first" in x or "i2v" in x or "image" in x or "last" in x]


@pytest.mark.parametrize("kind", ["2.5", "2.0", "fast", "mini"])
def test_us16_seedance_manifest_has_no_seed_or_negative(c, kind):
    m = full_manifest(c, seedance(c, kind))
    for bad in ("seed", "negative", "cfg", "camera"):
        assert pkey(m, bad) is None, f"{m['id']} exposes {bad}"


@pytest.mark.parametrize("kind", ["2.5", "2.0", "fast", "mini"])
def test_us16_seedance_resolve_does_not_pass_through_seed_or_negative(c, kind):
    m = full_manifest(c, seedance(c, kind))
    for key, val in (("seed", 42), ("negativePrompt", "blur"), ("negative_prompt", "blur")):
        r = res_(c, m, {key: val})
        assert r.status_code >= 400 or r.json().get("errors") or key not in r.json()["effectiveParams"], \
            (key, r.text)


@pytest.mark.parametrize("kind", ["2.5", "2.0", "fast", "mini"])
def test_us16_first_frame_forces_ratio_adaptive(c, kind):
    m = full_manifest(c, seedance(c, kind))
    ratio = pkey(m, "ratio", "aspect")
    first = pkey(m, "first", "image", exclude=("last",))
    fm = frame_modes(m)
    assert ratio, "seedance manifest must expose a ratio param"
    assert "adaptive" in [str(v) for v in values_of(m, ratio)], values_of(m, ratio)
    if not first or not fm:
        pytest.skip(f"{m['id']}: no first-frame param/mode (modes={m.get('modes')})")
    a = frame_assets(c, 1)[0]
    mode = next((x for x in fm if "last" not in x), fm[0])
    other = next(str(v) for v in values_of(m, ratio) if str(v) not in ("adaptive",))
    r = res_(c, m, {first: a["id"], ratio: other}, mode=mode)
    assert r.status_code == 200, r.text
    b = r.json()
    assert not b["errors"], b
    assert b["effectiveParams"][ratio] == "adaptive", b["effectiveParams"]
    locked = {l["key"]: l.get("reason") for l in b["locked"]}
    assert ratio in locked and locked[ratio], f"ratio must be locked with a reason: {b['locked']}"


@pytest.mark.parametrize("kind", ["2.5", "2.0", "fast", "mini"])
def test_us16_first_and_last_frame_forces_ratio_adaptive(c, kind):
    m = full_manifest(c, seedance(c, kind))
    ratio = pkey(m, "ratio", "aspect")
    first, last = pkey(m, "first", "image", exclude=("last",)), pkey(m, "last")
    mode = next((x for x in m.get("modes", []) if "last" in x), None)
    if not (first and last and mode):
        pytest.skip(f"{m['id']}: no first+last frame mode (modes={m.get('modes')})")
    a, b_ = frame_assets(c, 2)[:2]
    other = next(str(v) for v in values_of(m, ratio) if str(v) != "adaptive")
    r = res_(c, m, {first: a["id"], last: b_["id"], ratio: other}, mode=mode)
    assert r.status_code == 200, r.text
    b = r.json()
    assert not b["errors"], b
    assert b["effectiveParams"][ratio] == "adaptive"


@pytest.mark.parametrize("kind", ["2.5", "2.0", "fast", "mini"])
def test_us16_last_frame_without_first_frame_rejected(c, kind):
    m = full_manifest(c, seedance(c, kind))
    last = pkey(m, "last")
    mode = next((x for x in m.get("modes", []) if "last" in x), None)
    if not (last and mode):
        pytest.skip(f"{m['id']}: no last-frame mode")
    r = res_(c, m, {last: "asset-that-does-not-matter"}, mode=mode)
    assert r.status_code >= 400 or bool(r.json().get("errors"))


def test_us16_4k_only_on_seedance_2_0_non_fast_non_mini(c):
    res_values = {}
    for kind in ("2.5", "2.0", "fast", "mini"):
        try:
            m = full_manifest(c, seedance(c, kind))
        except pytest.skip.Exception:
            continue
        key = pkey(m, "resolution")
        assert key
        res_values[kind] = ([str(v).lower() for v in values_of(m, key)], m, key)
    if not res_values:
        pytest.skip("no seedance manifests")
    if "2.0" in res_values:
        assert "4k" in res_values["2.0"][0], res_values["2.0"][0]
    for kind in ("2.5", "fast", "mini"):
        if kind in res_values:
            vals, m, key = res_values[kind]
            assert "4k" not in vals, f"{kind} must not offer 4k: {vals}"
            r = res_(c, m, {key: "4k"})
            assert is_refused_or_coerced(r, key, "4k"), f"{kind}: 4k passed resolve: {r.text}"


@pytest.mark.parametrize("kind", ["fast", "mini"])
def test_us16_fast_and_mini_max_720p(c, kind):
    m = full_manifest(c, seedance(c, kind))
    key = pkey(m, "resolution")
    vals = [str(v).lower() for v in values_of(m, key)]
    assert vals and "720p" in vals
    assert "1080p" not in vals and "4k" not in vals, vals
    for bad in ("1080p", "4k"):
        r = res_(c, m, {key: bad})
        assert is_refused_or_coerced(r, key, bad), (bad, r.text)


def test_us16_seedance_2_5_has_1080p_but_not_4k(c):
    m = full_manifest(c, seedance(c, "2.5"))
    vals = [str(v).lower() for v in values_of(m, pkey(m, "resolution"))]
    assert "1080p" in vals and "4k" not in vals, vals


def test_us16_seedance_2_0_4k_resolves_clean(c):
    m = full_manifest(c, seedance(c, "2.0"))
    key = pkey(m, "resolution")
    if "4k" not in [str(v).lower() for v in values_of(m, key)]:
        pytest.fail("2.0 must offer 4k (US16)")
    val = next(v for v in values_of(m, key) if str(v).lower() == "4k")
    r = res_(c, m, {key: val})
    assert r.status_code == 200, r.text
    assert not r.json()["errors"]
    assert r.json()["effectiveParams"][key] == val


# ------------------------------------------------------------------ OpenAI size rule via /api/resolve
def openai_image(c):
    ids = openai_models(c)
    if not ids:
        pytest.skip("no openai model present")
    return full_manifest(c, ids[0])


def size_params(m, w, h):
    """Return params dict expressing a WxH size for this manifest, or skip."""
    k = pkey(m, "size", exclude=("quality",))
    if k and not pdef(m, k).get("values"):
        return {k: f"{w}x{h}"}, k
    wk, hk = pkey(m, "width"), pkey(m, "height")
    if wk and hk:
        return {wk: w, hk: h}, wk
    if k:
        return {k: f"{w}x{h}"}, k
    pytest.skip(f"{m['id']}: no size/width+height param to test the size rule through")


BAD_SIZES = [(1000, 1024, "not multiple of 16"), (1024, 1001, "not multiple of 16"),
             (4096, 1024, "edge > 3840"), (1024, 3856, "edge > 3840"),
             (3840, 1024, "ratio 3.75:1 > 3:1"), (1024, 3840, "ratio 1:3.75"),
             (3840, 1264, "ratio just > 3:1"), (16, 64, "ratio 4:1"), (3856, 3856, "edge > 3840 square"),
             (3840, 3840, "pixels 14,745,600 > 8,294,400"), (16, 16, "pixels 256 < 655,360"),
             (1024, 624, "pixels 638,976 just < 655,360"),
             (3840, 2176, "pixels 8,355,840 just > 8,294,400")]


@pytest.mark.parametrize("w,h,why", BAD_SIZES)
def test_us16_openai_size_rule_violations_rejected(c, w, h, why):
    for mid in openai_models(c) or pytest.skip("no openai model present"):
        m = full_manifest(c, mid)
        p, k = size_params(m, w, h)
        r = res_(c, m, p)
        if r.status_code == 200:
            b = r.json()
            assert b["errors"], f"{mid}: {w}x{h} ({why}) accepted: {b}"
            for e in b["errors"]:
                assert isinstance(e, dict) and "key" in e and "reason" in e, e
        else:
            assert rejected(r), (mid, w, h, r.status_code, r.text)


@pytest.mark.parametrize("w,h", [
    (1024, 1024), (1536, 1024), (3840, 1280), (1280, 3840),
    (3840, 2160),  # 8,294,400 px: exact upper bound
    (2880, 1440),  # 4,147,200 px
    (1024, 640),   # 655,360 px: exact lower bound
])
def test_us16_openai_valid_sizes_resolve_clean(c, w, h):
    for mid in openai_models(c) or pytest.skip("no openai model present"):
        m = full_manifest(c, mid)
        p, k = size_params(m, w, h)
        r = res_(c, m, p)
        assert r.status_code == 200, (mid, w, h, r.text)
        b = r.json()
        assert not b["errors"], (mid, w, h, b)
        for kk, vv in p.items():
            assert str(b["effectiveParams"][kk]) == str(vv)


def test_us16_openai_has_no_seed_negative_cfg(c):
    for mid in openai_models(c) or pytest.skip("no openai model present"):
        m = full_manifest(c, mid)
        for bad in ("seed", "negative", "cfg", "steps"):
            assert pkey(m, bad) is None, f"{mid} exposes {bad}"


# ------------------------------------------------------------------ demo generation + estimate (openai + seedance)
def one_model_per_provider(c):
    out = {}
    for pid in ("openai", "byteplus"):
        ms = models_of(c, pid)
        if not ms:
            pytest.skip(f"no {pid} model present")
        out[pid] = full_manifest(c, ms[0]["id"])
    return out


def test_demo_estimate_for_openai_and_seedance(c):
    for pid, m in one_model_per_provider(c).items():
        for n in (1, 4):
            r = estimate(c, make_request(m), make_sweep(n))
            assert r.status_code == 200, (pid, r.text)
            b = r.json()
            assert b["jobCount"] == n
            assert 0 <= b["minUsd"] <= b["maxUsd"], b
            assert isinstance(b["warnings"], list)
            if b.get("unknownPrice"):
                assert b.get("confirmRequired") is True, f"inv15: unknown price must need confirmation: {b}"


def test_estimate_scales_with_job_count_for_new_providers(c):
    for pid, m in one_model_per_provider(c).items():
        one = estimate(c, make_request(m), make_sweep(1)).json()
        four = estimate(c, make_request(m), make_sweep(4)).json()
        if one.get("unknownPrice"):
            continue
        assert four["minUsd"] == pytest.approx(4 * one["minUsd"], rel=1e-6), pid
        assert four["maxUsd"] == pytest.approx(4 * one["maxUsd"], rel=1e-6), pid


def test_unknown_price_flagged_for_new_provider_manifest(mk, tmp_path):
    """Emptying the price table of an openai/byteplus manifest must flag unknownPrice + confirmRequired."""
    base = mk()
    ms = [s for s in summaries(base) if s.get("provider") in ("openai", "byteplus")]
    if not ms:
        pytest.skip("no openai/byteplus manifest present")
    for s in ms[:2]:
        m = copy.deepcopy(full_manifest(base, s["id"]))
        m["pricing"]["table"] = []
        m["pricing"]["priceKey"] = None
        mdir = tmp_path / f"m_unp_{s['id']}"
        mdir.mkdir()
        (mdir / f"{s['id']}.yaml").write_text(json.dumps(m))
        c2 = mk(data_dir=tmp_path / f"d_{s['id']}", tmp_dir=tmp_path / f"t_{s['id']}", AIGEN_MANIFESTS_DIR=mdir)
        b = estimate(c2, make_request(full_manifest(c2, s["id"])), make_sweep(1)).json()
        assert b.get("unknownPrice") is True and b.get("confirmRequired") is True, (s["id"], b)
        r = post_batch(c2, make_request(full_manifest(c2, s["id"])), make_sweep(1), confirm=False)
        assert r.status_code == 409 and api_error_kind(r) == "confirm_required", (r.status_code, r.text)


@pytest.mark.parametrize("pid", ["openai", "byteplus"])
def test_demo_generation_succeeds_and_job_carries_identity(c, pid):
    ms = models_of(c, pid)
    if not ms:
        pytest.skip(f"no {pid} model present")
    m = full_manifest(c, ms[0]["id"])
    done, _ = run_one(c, m["id"])
    j = done["jobs"][0]
    assert j["status"] == "succeeded", j
    assert j["model"] == m["id"]
    assert j.get("provider") == pid, f"job must carry provider identity: {j}"
    assets = has_asset_ids(done)
    assert assets, "demo run must produce at least one asset"
    r = c.get(f"/api/assets/{assets[0]['id']}")
    assert r.status_code == 200 and len(r.content) > 0


def test_demo_failure_and_block_classification_for_new_providers(c):
    for pid, m in one_model_per_provider(c).items():
        failed, _ = run_one(c, m["id"], prompt="[fail] x")
        assert failed["jobs"][0]["status"] == "failed", pid
        blocked, _ = run_one(c, m["id"], prompt="[blocked] x")
        assert blocked["jobs"][0]["status"] == "blocked", pid
        j = blocked["jobs"][0]
        r = c.post(f"/api/jobs/{j['id']}/retry")
        assert r.status_code in (200, 201, 202, 400, 409)  # manual retry allowed, never auto (inv 5)


def test_blocked_job_of_new_provider_is_not_auto_retried(c):
    for pid, m in one_model_per_provider(c).items():
        done, _ = run_one(c, m["id"], prompt="[blocked] x")
        j = done["jobs"][0]
        assert j["status"] == "blocked"
        import time
        time.sleep(0.3)
        again = c.get(f"/api/batches/{done.get('batchId') or done.get('id')}").json()
        assert len(again["jobs"]) == len(done["jobs"]), "blocked job must not spawn automatic retries"


# ------------------------------------------------------------------ US14 mixed providers
def test_us14_mixed_provider_results_coexist_with_identity(c):
    configure_all(c, "X")
    picks = []
    nb = find_model(c, kind="image")  # a vertex image model
    if nb and prov_of(next(s for s in summaries(c) if s["id"] == nb)) != "vertex":
        nb = next((s["id"] for s in models_of(c, "vertex") if s["kind"] == "image"), None)
    oa = next((s["id"] for s in models_of(c, "openai") if s["kind"] == "image"), None)
    if not nb or not oa:
        pytest.skip(f"need one vertex image model and one openai image model (vertex={nb}, openai={oa})")
    results = {}
    for mid in (nb, oa):
        done, m = run_one(c, mid, prompt="a red apple")
        results[mid] = done
    jobs = [j for d in results.values() for j in d["jobs"]]
    assert all(j["status"] == "succeeded" for j in jobs), jobs
    by_model = {j["model"]: j for j in jobs}
    assert set(by_model) == {nb, oa}
    assert by_model[nb].get("provider") == "vertex"
    assert by_model[oa].get("provider") == "openai"
    # assets from both remain retrievable side by side
    for d in results.values():
        for a in has_asset_ids(d):
            assert c.get(f"/api/assets/{a['id']}").status_code == 200
    # ZIP of both sets: sidecars identify each job's model
    all_assets = [a["id"] for d in results.values() for a in has_asset_ids(d)]
    z = c.post("/api/zip", json={"assetIds": all_assets})
    assert z.status_code == 200
    blob = json.dumps({n: d.decode("utf-8", "ignore") for n, d in zip_members(z.content).items() if n.endswith(".json")})
    assert nb in blob and oa in blob


def test_us14_three_provider_batches_run_concurrently_and_all_succeed(c):
    configure_all(c, "Y")
    picks = []
    for pid in PROVIDERS:
        ms = models_of(c, pid)
        if not ms:
            pytest.skip(f"no {pid} model present")
        picks.append(ms[0])
    ids = []
    for s in picks:
        r = post_batch(c, make_request(full_manifest(c, s["id"])), make_sweep(2))
        assert r.status_code in (200, 201, 202), (s["id"], r.text)
        ids.append((s, r.json()["batchId"]))
    for s, bid in ids:
        done = wait_batch(c, bid)
        assert len(done["jobs"]) == 2
        for j in done["jobs"]:
            assert j["status"] == "succeeded", j
            assert j["model"] == s["id"] and j.get("provider") == s["provider"]


def test_job_requested_vs_effective_params_still_stored_for_new_providers(c):
    for pid, m in one_model_per_provider(c).items():
        done, _ = run_one(c, m["id"])
        j = done["jobs"][0]
        assert "requestedParams" in j and "effectiveParams" in j, j.keys()
