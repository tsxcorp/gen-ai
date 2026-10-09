from __future__ import annotations

import base64
import copy

import pytest

from app.adapters.base import redact_payload, set_path
from app.adapters.demo import DemoAdapter, make_mp4, make_png
from app.adapters.vertex_common import normalize_error
from app.adapters.vertex_image import VertexImageAdapter, parse_generate_content
from app.adapters.vertex_omni import VertexOmniAdapter, parse_interaction
from app.adapters.vertex_text import build_enhance_payload, parse_text
from app.adapters.vertex_veo import VertexVeoAdapter, parse_operation
from app.core.expand import expand
from app.errors import AdapterError
from app.schemas import GenerationRequest, InputAsset, Sweep


def job_for(manifests, model, mode=None, params=None, inputs=None, variants=1):
    m = manifests[model]
    j = expand(m, GenerationRequest(model_id=model, mode=mode, prompt="a fox", params=params or {},
                                    assets={k: ["x"] for k in (inputs or {})} if inputs else {}),
               Sweep(variants=variants), 24)[0]
    j.inputs = inputs or {}
    return m, j


def test_veo_payload_pure_and_exact(manifests):
    m, j = job_for(manifests, "veo-3.1", params={"resolution": "1080p", "seed": 5, "negative_prompt": "blur"}, variants=3)
    ad = VertexVeoAdapter(m, None)
    before = copy.deepcopy(j.model_dump())
    p1, p2 = ad.build_payload(j), ad.build_payload(j)
    assert p1 == p2 and j.model_dump() == before
    assert p1["instances"] == [{"prompt": "a fox"}]
    assert p1["parameters"] == {"sampleCount": 3, "aspectRatio": "16:9", "resolution": "1080p", "durationSeconds": 8,
                                "generateAudio": True, "seed": 5, "negativePrompt": "blur", "personGeneration": "allow_adult"}


def test_veo_i2v_and_first_last_payload(manifests):
    img = InputAsset(id="a", mime="image/png", data=b"\x89PNG")
    m, j = job_for(manifests, "veo-3.1-fast", "first_last", inputs={"first_frame": [img], "last_frame": [img]})
    inst = VertexVeoAdapter(m, None).build_payload(j)["instances"][0]
    assert inst["image"]["bytesBase64Encoded"] == base64.b64encode(b"\x89PNG").decode() and "lastFrame" in inst


def test_image_payload_shape_and_no_unsupported(manifests):
    m, j = job_for(manifests, "nano-banana-2.1", params={"image_size": "2K", "aspect_ratio": "21:9", "google_search": True,
                                                         "thinking_level": "high", "safety_threshold": "BLOCK_ONLY_HIGH"})
    p = VertexImageAdapter(m, None).build_payload(j)
    cfg = p["generationConfig"]
    assert cfg["responseModalities"] == ["IMAGE"]
    assert cfg["imageConfig"] == {"aspectRatio": "21:9", "imageSize": "2K"}
    assert cfg["thinkingConfig"] == {"thinkingLevel": "high"}
    assert p["tools"] == [{"googleSearch": {}}] and len(p["safetySettings"]) == 4
    # no google search on lite
    m2 = manifests["gemini-3.1-flash-lite-image"]
    j2 = expand(m2, GenerationRequest(model_id=m2.id, prompt="x"), None, 24)[0]
    assert "tools" not in VertexImageAdapter(m2, None).build_payload(j2)


def test_omni_payload(manifests):
    m, j = job_for(manifests, "gemini-omni-1.1-flash", params={"duration": 7, "resolution": "1080p"})
    p = VertexOmniAdapter(m, None).build_payload(j)
    assert p["model"] == "gemini-omni-1.1-flash-preview"
    assert p["response_format"] == {"type": "video", "aspect_ratio": "16:9", "resolution": "1080p", "duration": "7s"}
    assert "seed" not in str(p) and "negative" not in str(p)


def test_set_path_and_redact():
    d: dict = {"a": [{}]}
    set_path(d, "a.0.b.c", 1)
    assert d == {"a": [{"b": {"c": 1}}]}
    assert redact_payload({"x": "A" * 500, "t": "short prompt"})["x"].startswith("<base64")


def test_error_normalisation():
    assert normalize_error(429, {}).kind == "quota"
    assert normalize_error(403, {}).kind == "auth"
    # invariant 17: free text never decides `blocked`
    assert normalize_error(400, {"error": {"message": "Request blocked by safety filters"}}).kind == "invalid"
    assert normalize_error(400, {"error": {"message": "Invalid constraint on resolution"}}).kind == "invalid"
    assert normalize_error(400, {"error": {"message": "bad value"}}).kind == "invalid"
    structured = {"error": {"message": "x", "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                                                         "reason": "PROHIBITED_CONTENT"}]}}
    assert normalize_error(400, structured).kind == "blocked"
    assert normalize_error(503, {}).kind == "network"
    assert normalize_error(504, {}).kind == "timeout"


def test_parse_generate_content():
    png = base64.b64encode(make_png(8, 8, "s")).decode()
    ok = {"candidates": [{"content": {"parts": [{"text": "hi"}, {"inlineData": {"mimeType": "image/png", "data": png}}]}}]}
    assert parse_generate_content(ok)[0].data.startswith(b"\x89PNG")
    with pytest.raises(AdapterError) as e:
        parse_generate_content({"promptFeedback": {"blockReason": "SAFETY"}})
    assert e.value.kind == "blocked"
    with pytest.raises(AdapterError) as e:
        parse_generate_content({"candidates": [{"finishReason": "IMAGE_SAFETY"}]})
    assert e.value.kind == "blocked"
    with pytest.raises(AdapterError) as e:
        parse_generate_content({"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "no"}]}}]})
    assert e.value.kind == "invalid"


def test_parse_operation():
    assert parse_operation({"done": False}).state == "running"
    r = parse_operation({"done": True, "response": {"videos": [{"gcsUri": "gs://b/o.mp4", "mimeType": "video/mp4"}]}})
    assert r.state == "done" and r.outputs[0].uri == "gs://b/o.mp4"
    r = parse_operation({"done": True, "response": {"raiMediaFilteredCount": 1, "raiMediaFilteredReasons": ["x"]}})
    assert r.state == "failed" and r.error.kind == "blocked"
    r = parse_operation({"done": True, "error": {"code": 8, "message": "quota"}})
    assert r.error.kind == "quota"


def test_parse_interaction_and_text():
    assert parse_interaction({"status": "in_progress"}).state == "running"
    vid = base64.b64encode(b"mp4").decode()
    r = parse_interaction({"status": "completed", "outputs": [{"type": "video", "data": vid}]})
    assert r.state == "done" and r.outputs[0].data == b"mp4"
    assert parse_interaction({"status": "failed", "error": {"message": "safety policy"}}).error.kind == "invalid"
    assert parse_interaction({"status": "failed", "error": {"code": "SAFETY", "message": "x"}}).error.kind == "blocked"
    assert parse_text({"candidates": [{"content": {"parts": [{"text": " hello "}]}}]}) == "hello"
    assert build_enhance_payload("sys", "p")["systemInstruction"]["parts"][0]["text"] == "sys"


def test_demo_media_valid():
    png = make_png(32, 16, "a")
    assert png.startswith(b"\x89PNG") and make_mp4("a") != make_mp4("b")
    assert b"ftyp" in make_mp4("a")[:16]


async def test_demo_keywords(manifests, monkeypatch):
    monkeypatch.setenv("AIGEN_DEMO_DELAY_MS", "1")
    m = manifests["nano-banana-2.1"]
    ad = DemoAdapter(m)
    for kw, kind in (("[blocked]", "blocked"), ("[fail]", "invalid")):
        j = expand(m, GenerationRequest(model_id=m.id, prompt=f"x {kw}"), None, 24)[0]
        with pytest.raises(AdapterError) as e:
            await ad.submit(j)
        assert e.value.kind == kind
    j = expand(m, GenerationRequest(model_id=m.id, prompt="x [quota]"), None, 24)[0]
    with pytest.raises(AdapterError):
        await ad.submit(j)
    assert (await ad.submit(j)).data["outputs"]
