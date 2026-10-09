"""Story 4 + DoD 'estimate before run' + Never 'hardcode prices'."""
import json

import pytest
from vhelpers import *


def est(client, m, params=None, n=1):
    r = estimate(client, make_request(m, params=params), make_sweep(n))
    assert r.status_code == 200, r.text
    return r.json()


def test_estimate_shape_and_ordering(client):
    for s in summaries(client):
        m = full_manifest(client, s["id"])
        b = est(client, m, n=3)
        assert b["jobCount"] == 3
        assert 0 <= b["minUsd"] <= b["maxUsd"]
        assert isinstance(b["warnings"], list)


def test_estimate_total_scales_with_job_count(client):
    m = full_manifest(client, find_model(client, kind="image"))
    one, four = est(client, m, n=1), est(client, m, n=4)
    assert four["minUsd"] == pytest.approx(4 * one["minUsd"], rel=1e-6)
    assert four["maxUsd"] == pytest.approx(4 * one["maxUsd"], rel=1e-6)


def test_omni_price_rises_with_resolution(client):
    mid = need_model(client, kind="video", has=("omni",))
    m = full_manifest(client, mid)
    res = pkey(m, "resolution")
    vals = [v for v in values_of(m, res)]
    if len(vals) < 2:
        pytest.skip("omni manifest offers a single resolution (preview 720p only): nothing to compare")
    prices = {v: est(client, m, {res: v})["minUsd"] for v in vals}
    order = [v for v in ["360p", "720p", "1080p", "4k"] if v in prices]
    for a, b in zip(order, order[1:]):
        assert prices[a] <= prices[b], prices


def test_veo_price_scales_with_duration_and_audio(client):
    mid = need_model(client, kind="video", has=("veo",), lacks=("fast", "lite"))
    m = full_manifest(client, mid)
    dur, res = pkey(m, "duration"), pkey(m, "resolution")
    p4 = est(client, m, {res: "720p", dur: 4})
    p8 = est(client, m, {res: "720p", dur: 8})
    assert p8["minUsd"] > p4["minUsd"] and p8["maxUsd"] > p4["maxUsd"]
    audio = pkey(m, "audio")
    if audio:
        on = est(client, m, {res: "720p", dur: 8, audio: True})
        off = est(client, m, {res: "720p", dur: 8, audio: False})
        # requirements: $0.40/s with audio vs $0.20/s without
        assert on["maxUsd"] > off["maxUsd"]


def test_veo_doc_price_is_in_range(client):
    """Requirements: Veo 3.1 = $0.40/s with audio => 8s = $3.20 must lie inside [min,max]."""
    mid = need_model(client, kind="video", has=("veo",), lacks=("fast", "lite"))
    m = full_manifest(client, mid)
    dur, res, audio = pkey(m, "duration"), pkey(m, "resolution"), pkey(m, "audio")
    if not audio:
        pytest.skip("no audio param on veo manifest")
    b = est(client, m, {res: "720p", dur: 8, audio: True})
    assert b["minUsd"] - 1e-6 <= 3.2 <= b["maxUsd"] + 1e-6, b


def test_stale_prices_warning_is_not_raised_for_fresh_manifest(client):
    """Counterpart of the 30-day rule: manifests verified 2026-10-07 must not warn as stale
    when evaluated near that date. (The stale-positive side is untestable: prices.json format unspecified.)"""
    import datetime
    m = full_manifest(client, find_model(client, kind="image"))
    age = (datetime.date.today() - datetime.date.fromisoformat(m["lastVerified"][:10])).days
    b = est(client, m)
    stale = [w for w in b["warnings"] if "cũ" in str(w) or "stale" in str(w).lower() or "old" in str(w).lower()]
    if age <= 30:
        assert not stale
    else:
        assert stale, f"lastVerified is {age} days old but no stale-price warning"


def test_prices_come_from_data_not_code(make_client, tmp_path, client):
    """Never: hardcode prices. Doubling every 'usd' in a manifest copy must double the estimate."""
    mid = find_model(client, kind="video", has=("veo",), lacks=("fast", "lite")) or find_model(client, kind="image")
    base_m = full_manifest(client, mid)
    base = est(client, base_m)
    mdir = tmp_path / "manifests2"
    mdir.mkdir()
    doubled = walk_numbers_usd(json.loads(json.dumps(base_m)), 2)
    (mdir / f"{mid}.yaml").write_text(json.dumps(doubled))  # JSON is valid YAML
    c2 = make_client(data_dir=tmp_path / "d2", tmp_dir=tmp_path / "t2", AIGEN_MANIFESTS_DIR=mdir)
    assert [s["id"] for s in summaries(c2)] == [mid]
    got = est(c2, full_manifest(c2, mid))
    assert base["maxUsd"] > 0
    assert got["minUsd"] == pytest.approx(2 * base["minUsd"], rel=1e-6)
    assert got["maxUsd"] == pytest.approx(2 * base["maxUsd"], rel=1e-6)


def test_model_list_comes_from_manifest_dir(make_client, tmp_path, client):
    """Never: hardcode model list. A manifest dir with one model exposes exactly one model."""
    mid = find_model(client, kind="image")
    m = full_manifest(client, mid)
    mdir = tmp_path / "m3"
    mdir.mkdir()
    (mdir / f"{mid}.yaml").write_text(json.dumps(m))
    c2 = make_client(data_dir=tmp_path / "d3", tmp_dir=tmp_path / "t3", AIGEN_MANIFESTS_DIR=mdir)
    assert [s["id"] for s in summaries(c2)] == [mid]
