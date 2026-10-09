"""Story 9 (presets/prompt library persistence) and 10 (prompt enhancer)."""
from vhelpers import *


def put_items(client, path, items, wrap_key):
    """Body shape for presets/prompts is unspecified: try list, then {wrap_key: list}."""
    last = None
    for body in (items, {wrap_key: items}):
        r = client.put(path, json=body)
        if r.status_code in (200, 201, 204):
            return r
        last = r
    raise AssertionError(f"PUT {path} rejected both body shapes: {last.status_code} {last.text}")


def test_preset_survives_restart(make_client):
    c1 = make_client()
    mid = find_model(c1, kind="video", has=("veo",)) or find_model(c1, kind="video")
    m = full_manifest(c1, mid)
    res, ar = pkey(m, "resolution"), pkey(m, "aspectratio")
    preset = {"name": "Reel 9:16 720p", "modelId": mid, "params": {ar: "9:16", res: "720p"}}
    put_items(c1, "/api/presets", [preset], "presets")
    assert "Reel 9:16 720p" in c1.get("/api/presets").text
    c2 = make_client(data_dir=c1.data_dir, tmp_dir=c1.tmp_dir)  # restart on same data dir
    body = c2.get("/api/presets").text
    assert "Reel 9:16 720p" in body and "9:16" in body and "720p" in body
    assert any(p.suffix == ".json" and "preset" in p.name for p in c1.data_dir.iterdir())


def test_prompt_library_survives_restart(make_client):
    c1 = make_client()
    put_items(c1, "/api/prompts", [{"name": "hero", "text": "a lone astronaut single continuous shot"}], "prompts")
    c2 = make_client(data_dir=c1.data_dir, tmp_dir=c1.tmp_dir)
    assert "single continuous shot" in c2.get("/api/prompts").text


def test_presets_garbage_is_invalid_and_does_not_corrupt(client):
    put_items(client, "/api/presets", [{"name": "keepme", "modelId": "x", "params": {}}], "presets")
    r = client.put("/api/presets", content=b"{not json", headers={"content-type": "application/json"})
    assert 400 <= r.status_code < 500
    assert "keepme" in client.get("/api/presets").text


def test_data_files_not_written_outside_data_dir(client, tmp_path):
    put_items(client, "/api/presets", [{"name": "p", "modelId": "x", "params": {}}], "presets")
    put_items(client, "/api/prompts", [{"name": "q", "text": "t"}], "prompts")
    stray = [p for p in tmp_path.rglob("*.json") if client.data_dir not in p.parents and client.tmp_dir not in p.parents]
    assert not stray


def test_enhance_returns_suggestion_without_overwriting(client):
    for kind_has in (dict(kind="image"), dict(kind="video", has=("veo",)), dict(kind="video", has=("omni",))):
        mid = find_model(client, **kind_has)
        if not mid:
            continue
        r = client.post("/api/enhance", json={"modelId": mid, "prompt": "a cat"})
        assert r.status_code == 200, (mid, r.text)
        b = r.json()
        assert set(b) == {"suggestion"} or "suggestion" in b
        assert isinstance(b["suggestion"], str) and b["suggestion"].strip()


def test_enhance_does_not_create_jobs(client):
    mid = find_model(client, kind="image")
    client.post("/api/enhance", json={"modelId": mid, "prompt": "a cat"})
    assert client.get("/api/batches/x").status_code == 404
