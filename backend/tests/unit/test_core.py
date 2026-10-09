from __future__ import annotations

from datetime import date

import pytest
import yaml

from app.core import constraints
from app.core.cost import estimate_job
from app.core.expand import expand
from app.core.manifest import ManifestError, load_manifests, manifest_warnings, validate_manifest
from app.errors import ApiError
from app.schemas import GenerationRequest, Sweep

EXPECTED = {
    "nano-banana-2.1", "gemini-3.1-flash-image", "gemini-3.1-flash-lite-image", "gemini-3-pro-image",
    "gemini-omni-1.1-flash", "veo-3.1", "veo-3.1-fast", "veo-3.1-lite",
    "gpt-image-2.5-sunburst", "gpt-image-2.5-flare",
    "seedance-2.5", "seedance-2.0", "seedance-2.0-fast", "seedance-2.0-mini",
}


def test_all_manifests_load(manifests):
    assert set(manifests) == EXPECTED
    assert all(m.last_verified == "2026-10-07" for m in manifests.values())


def test_manifest_cross_validation(dirs, tmp_path):
    raw = yaml.safe_load((dirs["manifests_dir"] / "veo-3.1.yaml").read_text())
    raw["constraints"][0]["then"]["duration"] = 5  # not in values
    (tmp_path / "bad.yaml").write_text(yaml.safe_dump(raw))
    with pytest.raises(ManifestError, match="not in values"):
        load_manifests(tmp_path)


def test_manifest_price_row_must_reference_params(manifests):
    m = manifests["veo-3.1"].model_copy(deep=True)
    m.pricing.table[0].when["nope"] = 1
    with pytest.raises(ManifestError, match="not a param"):
        validate_manifest(m)


def test_veo_1080p_forces_duration_8(manifests):
    r = constraints.resolve(manifests["veo-3.1"], "t2v", {"resolution": "1080p", "duration": 4})
    assert r.ok and r.effective["duration"] == 8
    assert r.locked and r.locked[0]["key"] == "duration" and r.locked[0]["reason"]


def test_veo_4k_forces_8_and_lite_has_no_4k(manifests):
    assert constraints.resolve(manifests["veo-3.1"], "t2v", {"resolution": "4k", "duration": 6}).effective["duration"] == 8
    assert not constraints.resolve(manifests["veo-3.1-lite"], "t2v", {"resolution": "4k"}).ok


def test_flash_lite_1k_only_and_uppercase_k(manifests):
    m = manifests["gemini-3.1-flash-lite-image"]
    assert constraints.resolve(m, None, {"image_size": "1K"}).ok
    assert not constraints.resolve(m, None, {"image_size": "2K"}).ok
    assert not constraints.resolve(manifests["nano-banana-2.1"], None, {"image_size": "2k"}).ok


def test_512_only_on_flash(manifests):
    assert constraints.resolve(manifests["gemini-3.1-flash-image"], None, {"image_size": "512"}).ok
    assert not constraints.resolve(manifests["nano-banana-2.1"], None, {"image_size": "512"}).ok


def test_extreme_ratios_only_nb21(manifests):
    assert constraints.resolve(manifests["nano-banana-2.1"], None, {"aspect_ratio": "8:1"}).ok
    assert not constraints.resolve(manifests["gemini-3-pro-image"], None, {"aspect_ratio": "8:1"}).ok


def test_omni_has_no_negative_or_seed_and_preview_720p(manifests):
    m = manifests["gemini-omni-1.1-flash"]
    for k in ("negative_prompt", "seed"):
        r = constraints.resolve(m, None, {k: "x" if k == "negative_prompt" else 1})
        assert not r.ok
    r = constraints.resolve(m, None, {"model_variant": "gemini-omni-flash-preview", "resolution": "1080p"})
    assert r.ok and r.effective["resolution"] == "720p" and r.locked


def test_unknown_param_and_bad_types(manifests):
    m = manifests["veo-3.1"]
    assert not constraints.resolve(m, None, {"nope": 1}).ok
    assert not constraints.resolve(m, None, {"duration": "8"}).ok
    assert not constraints.resolve(m, None, {"generate_audio": 1}).ok
    assert not constraints.resolve(m, None, {"seed": -1}).ok
    assert not constraints.resolve(m, "bogus", {}).ok


def test_asset_requirements(manifests):
    m = manifests["veo-3.1"]
    assert constraints.resolve(m, "i2v", {}, {}, check_assets=True).errors  # first_frame required
    assert constraints.resolve(m, "i2v", {}, {"first_frame": "a"}, check_assets=True).ok
    assert constraints.resolve(m, "first_last", {}, {"first_frame": "a"}, check_assets=True).errors  # lastFrame needs image + last


def test_inapplicable_param_dropped_for_mode(manifests):
    r = constraints.resolve(manifests["veo-3.1"], "t2v", {"resize_mode": "crop"})
    assert r.ok and "resize_mode" not in r.effective


def _req(model, **kw):
    return GenerationRequest(model_id=model, prompt=kw.pop("prompt", "p"), **kw)


def test_expand_n_prompts_axes(manifests):
    m = manifests["nano-banana-2.1"]
    jobs = expand(m, _req(m.id), Sweep(variants=2, prompts=["a", "b", "c"], axes=[
        {"param": "aspect_ratio", "values": ["1:1", "16:9"]}, {"param": "image_size", "values": ["1K"]}]), 24)
    assert len(jobs) == 12 and len({j.id for j in jobs}) == 12
    assert {j.effective_params["aspect_ratio"] for j in jobs} == {"1:1", "16:9"}


def test_expand_limits(manifests):
    m = manifests["nano-banana-2.1"]
    with pytest.raises(ApiError, match="over the limit"):
        expand(m, _req(m.id), Sweep(variants=25), 24)
    with pytest.raises(ApiError, match="at most 2"):
        expand(m, _req(m.id), Sweep(axes=[{"param": "aspect_ratio", "values": ["1:1"]}, {"param": "image_size", "values": ["1K"]},
                                          {"param": "seed", "values": [1]}]), 24)
    with pytest.raises(ApiError):
        expand(m, _req(m.id, prompt=" "), None, 24)


def test_expand_invalid_combo_reports(manifests):
    m = manifests["gemini-3.1-flash-lite-image"]
    with pytest.raises(ApiError) as e:
        expand(m, _req(m.id), Sweep(axes=[{"param": "image_size", "values": ["1K", "4K"]}]), 24)
    assert e.value.kind == "invalid"


def test_veo_native_grouping(manifests):
    m = manifests["veo-3.1"]
    jobs = expand(m, _req(m.id), Sweep(variants=6), 24)
    assert [j.variant_count for j in jobs] == [4, 2]
    jobs = expand(manifests["nano-banana-2.1"], _req("nano-banana-2.1"), Sweep(variants=3), 24)
    assert [j.variant_count for j in jobs] == [1, 1, 1]


def test_seed_modes(manifests):
    m = manifests["veo-3.1"]
    j = expand(m, _req(m.id), Sweep(variants=1, seed_mode="fixed", seed=7), 24)[0]
    assert j.effective_params["seed"] == 7
    assert "seed" not in expand(m, _req(m.id), Sweep(), 24)[0].effective_params
    assert "seed" not in expand(manifests["gemini-omni-1.1-flash"], _req("gemini-omni-1.1-flash"),
                                Sweep(seed_mode="random"), 24)[0].effective_params


PRICES = {"entries": {
    "veo-3.1": {"lastVerified": "2026-10-07", "table": [
        {"when": {"generate_audio": True, "resolution": ["720p", "1080p"]}, "usd": 0.40},
        {"when": {"generate_audio": False, "resolution": ["720p", "1080p"]}, "usd": 0.20}]},
    "nano-banana-2.1": {"lastVerified": "2026-01-01", "table": []},
}}


def test_cost_per_second_times_variants(manifests):
    m = manifests["veo-3.1"]
    j = expand(m, _req(m.id), Sweep(variants=3), 24)[0]
    lo, hi, w = estimate_job(m, j, PRICES, today=date(2026, 10, 8))
    assert lo == hi == pytest.approx(0.40 * 8 * 3) and not w


def test_cost_range_when_param_unspecified(manifests):
    m = manifests["veo-3.1"]
    j = expand(m, _req(m.id), Sweep(), 24)[0]
    del j.effective_params["generate_audio"]
    lo, hi, _ = estimate_job(m, j, PRICES, today=date(2026, 10, 8))
    assert lo == pytest.approx(0.20 * 8) and hi == pytest.approx(0.40 * 8)


def test_cost_stale_and_unknown_warn(manifests):
    m = manifests["nano-banana-2.1"]
    j = expand(m, _req(m.id), Sweep(), 24)[0]
    lo, hi, w = estimate_job(m, j, PRICES, stale_days=30, today=date(2026, 10, 7))
    assert (lo, hi) == (0.0, 0.0) and any("stale" in x for x in w) and any("unknown" in x for x in w)


def test_real_prices_cover_every_manifest(manifests, dirs):
    import json

    prices = json.loads((dirs["data_dir"] / "prices.json").read_text())
    for m in manifests.values():
        assert prices["entries"][m.id]["lastVerified"]
        assert m.pricing.table or prices["entries"][m.id].get("unknown")


def test_manifest_table_is_the_price_source_and_prices_json_can_override(manifests):
    m = manifests["nano-banana-2.1"]
    j = expand(m, _req(m.id), Sweep(), 24)[0]
    meta = {"entries": {m.id: {"lastVerified": "2026-10-07"}}}
    assert estimate_job(m, j, meta, today=date(2026, 10, 8))[:2] == (0.034, 0.034)
    over = {"entries": {m.id: {"lastVerified": "2026-10-07", "table": [{"when": {"image_size": "1K"}, "usd": 1.0}]}}}
    assert estimate_job(m, j, over, today=date(2026, 10, 8))[:2] == (1.0, 1.0)


def test_manifest_warnings(manifests):
    w = manifest_warnings(manifests["veo-3.1"], 30, today=date(2026, 11, 1))
    assert any("sunsets" in x for x in w)
    assert any("last verified" in x for x in manifest_warnings(manifests["veo-3.1"], 30, today=date(2027, 1, 1)))
