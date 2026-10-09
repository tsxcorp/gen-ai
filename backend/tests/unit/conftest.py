from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture()
def dirs(tmp_path, monkeypatch):
    data = tmp_path / "data"
    shutil.copytree(REPO / "data", data, ignore=shutil.ignore_patterns("providers.json"))
    monkeypatch.setenv("AIGEN_DEMO_DELAY_MS", "10")
    monkeypatch.setenv("AIGEN_RETRY_BASE_S", "0.01")
    return {"data_dir": data, "tmp_dir": tmp_path / "tmp", "manifests_dir": REPO / "manifests"}


@pytest.fixture()
def client(dirs):
    app = create_app(demo=True, lan=False, **dirs)
    with TestClient(app) as c:
        c.ctx = app.state.ctx
        yield c


@pytest.fixture()
def manifests(dirs):
    from app.core.manifest import load_manifests

    return load_manifests(dirs["manifests_dir"])
