"""Stories 11 (safety/uploads) and 12 (keys, providers.json, LAN token) + guardrails."""
import json
import os
import re
import stat
from pathlib import Path

import pytest
from conftest import REPO
from vhelpers import *


def upload(client, person, consent, data=PNG, name="a.png"):
    return client.post("/api/uploads", files={"file": (name, data, "image/png")},
                       data={"hasPerson": str(person).lower(), "consent": str(consent).lower()})


# ---- story 11
def test_upload_with_person_and_no_consent_rejected(client):
    r = upload(client, True, False)
    assert 400 <= r.status_code < 500
    assert api_error_kind(r) == "invalid"


def test_rejected_upload_is_not_retrievable(client):
    upload(client, True, False)
    files = [f for _, _, fs in os.walk(client.tmp_dir) for f in fs]
    assert not files, f"rejected upload left bytes in temp: {files}"


@pytest.mark.parametrize("person,consent", [(True, True), (False, False), (False, True)])
def test_upload_allowed_cases_return_asset(client, person, consent):
    r = upload(client, person, consent)
    assert r.status_code in (200, 201), r.text
    a = r.json()
    a = a.get("asset", a)
    got = client.get(f"/api/assets/{a['id']}")
    assert got.status_code == 200 and got.content == PNG


def test_upload_missing_flags_rejected_or_treated_as_person(client):
    r = client.post("/api/uploads", files={"file": ("a.png", PNG, "image/png")})
    if r.status_code in (200, 201):
        pytest.fail("upload without explicit hasPerson/consent flags must not be silently accepted")
    assert 400 <= r.status_code < 500


def test_blocked_job_is_normalized(client):
    done, _ = run_one(client, prompt="[blocked] x")
    j = done["jobs"][0]
    assert j["status"] == "blocked" and j["error"]["kind"] == "blocked" and j["error"]["message"]


def test_originals_not_reencoded(client):
    """Never: re-encode. Demo adapter output must round-trip byte-identically through API."""
    done, _ = run_one(client)
    a = done["jobs"][0]["assets"][0]
    import hashlib
    assert hashlib.sha256(client.get(f"/api/assets/{a['id']}").content).hexdigest() == a["sha256"]


# ---- story 12
def put_vertex(client, sa, **extra):
    body = {"projectId": "demo-proj", "location": "global"}
    body.update(extra)
    for form in (sa, json.dumps(sa)):
        r = client.put("/api/providers/vertex", json={**body, "json": form})
        if r.status_code in (200, 201, 204):
            return r
    return r


def test_providers_put_then_get_masked_and_never_leaks(client):
    sa, secrets = fake_service_account("A")
    r = put_vertex(client, sa)
    assert r.status_code in (200, 201, 204), r.text
    g = client.get("/api/providers")
    assert g.status_code == 200
    txt = g.text
    assert not contains_any(txt, secrets)
    assert "BEGIN PRIVATE KEY" not in txt and "private_key" not in txt
    assert re.search(r'"hasKey"\s*:\s*true', txt), txt


def test_providers_json_mode_0600_and_outside_responses(client):
    sa, _ = fake_service_account("B")
    assert put_vertex(client, sa).status_code in (200, 201, 204)
    p = client.data_dir / "providers.json"
    assert p.exists()
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    # rewrite stays 0600 (no umask race)
    assert put_vertex(client, sa, location="us-central1").status_code in (200, 201, 204)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_providers_persist_across_restart_but_get_stays_masked(make_client):
    c1 = make_client()
    sa, secrets = fake_service_account("C")
    assert put_vertex(c1, sa).status_code in (200, 201, 204)
    c2 = make_client(data_dir=c1.data_dir, tmp_dir=c1.tmp_dir)
    g = c2.get("/api/providers")
    assert not contains_any(g.content, secrets)
    assert "hasKey" in g.text


def test_providers_put_invalid_rejected(client):
    r = client.put("/api/providers/vertex", json={"projectId": ""})
    assert 400 <= r.status_code < 500 and api_error_kind(r) == "invalid"


def test_key_never_in_any_response_zip_log_or_temp(client, caplog, capsys):
    import logging
    caplog.set_level(logging.DEBUG)
    sa, secrets = fake_service_account("D")
    put_vertex(client, sa)
    client.post("/api/providers/vertex/test")  # may fail auth; must not echo key
    client.get("/api/providers")
    done, _ = run_one(client)
    assets = has_asset_ids(done)
    z = client.post("/api/zip", json={"assetIds": [a["id"] for a in assets]})
    client.get("/api/manifests")
    run_one(client, prompt="[blocked] x")
    run_one(client, prompt="[fail] x")
    client.post("/api/enhance", json={"modelId": find_model(client, kind="image"), "prompt": "x"})
    for blob in client.seen:
        assert not contains_any(blob, secrets), "service-account key material appeared in an HTTP response"
    assert not contains_any(z.content, secrets)
    assert not contains_any(caplog.text, secrets), "key material in logs"
    out = capsys.readouterr()
    assert not contains_any(out.out + out.err, secrets)
    for d, _, fs in os.walk(client.tmp_dir):
        for f in fs:
            assert not contains_any(Path(d, f).read_bytes(), secrets), f"key in temp file {f}"
    for d, _, fs in os.walk(client.data_dir):
        for f in fs:
            if f != "providers.json":
                assert not contains_any(Path(d, f).read_bytes(), secrets), f"key in {f}"


def test_error_responses_never_echo_key(client):
    sa, secrets = fake_service_account("E")
    r = client.put("/api/providers/vertex", json={"projectId": "", "json": sa})
    assert not contains_any(r.content, secrets)


# ---- LAN token (env names AIGEN_LAN / AIGEN_TOKEN are a guess, see report)
def test_lan_mode_requires_token(make_client):
    c = make_client(AIGEN_LAN="1", AIGEN_TOKEN="tok-verify-123")
    assert c.get("/api/manifests").status_code == 401
    assert c.get("/api/manifests", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert c.get("/api/manifests", headers={"Authorization": "Bearer tok-verify-123"}).status_code == 200
    r = c.post("/api/estimate", json={})
    assert r.status_code == 401, "token must guard every /api route, not just GET"
    assert api_error_kind(c.get("/api/manifests")) in ("auth", None)


def test_lan_mode_protects_assets_and_providers(make_client):
    c = make_client(AIGEN_LAN="1", AIGEN_TOKEN="tok-verify-123")
    for path in ("/api/providers", "/api/assets/x", "/api/events", "/api/presets"):
        assert c.get(path).status_code == 401, path


def test_local_mode_needs_no_token(client):
    assert client.get("/api/manifests").status_code == 200


# ---- Never: no key material committed
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "tests", ".pytest_cache",
             "dist", ".mypy_cache", ".ruff_cache"}
PATTERNS = [re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
            re.compile(r'"private_key"\s*:\s*"-----BEGIN'),
            re.compile(r"AIza[0-9A-Za-z_\-]{35}")]


def repo_files():
    for d, dirs, files in os.walk(REPO):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            p = Path(d, f)
            if p.stat().st_size < 2_000_000:
                yield p


def test_no_key_material_committed():
    hits = []
    for p in repo_files():
        try:
            t = p.read_text(errors="ignore")
        except Exception:
            continue
        for pat in PATTERNS:
            if pat.search(t):
                hits.append(f"{p.relative_to(REPO)}: {pat.pattern}")
    assert not hits, hits


def test_providers_json_is_gitignored_and_not_present_in_repo_data():
    gi = REPO / ".gitignore"
    assert gi.exists(), ".gitignore missing"
    assert re.search(r"providers\.json", gi.read_text()), "providers.json must be gitignored"
    # a real providers.json next to committed seed files would be committed by accident
    seed = REPO / "data" / "providers.json"
    if seed.exists():
        assert stat.S_IMODE(seed.stat().st_mode) == 0o600
