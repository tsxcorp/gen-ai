import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

ENV_KEYS = ["AIGEN_DEMO", "AIGEN_DATA_DIR", "AIGEN_TMP_DIR", "AIGEN_MANIFESTS_DIR",
            "AIGEN_DEMO_DELAY_MS", "AIGEN_LAN", "AIGEN_TOKEN"]


class RecordingClient(TestClient):
    """TestClient that remembers every byte the server ever returned."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.seen: list[bytes] = []

    def request(self, *a, **kw):
        r = super().request(*a, **kw)
        self.seen.append(r.content)
        self.seen.append(str(dict(r.headers)).encode())
        return r


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    """Factory: make_client(delay_ms=0, data_dir=None, **extra_env) -> RecordingClient."""
    clients = []

    def _make(delay_ms=0, data_dir=None, tmp_dir=None, **extra_env):
        data = Path(data_dir) if data_dir else tmp_path / "data"
        tmpd = Path(tmp_dir) if tmp_dir else tmp_path / "tmp"
        data.mkdir(parents=True, exist_ok=True)
        tmpd.mkdir(parents=True, exist_ok=True)
        for k in ENV_KEYS:
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("AIGEN_DEMO", "1")
        monkeypatch.setenv("AIGEN_DATA_DIR", str(data))
        monkeypatch.setenv("AIGEN_TMP_DIR", str(tmpd))
        monkeypatch.setenv("AIGEN_DEMO_DELAY_MS", str(delay_ms))
        for k, v in extra_env.items():
            monkeypatch.setenv(k, str(v))
        from app.main import create_app  # imported lazily: absent until implemented

        c = RecordingClient(create_app())
        c.__enter__()
        c.data_dir, c.tmp_dir = data, tmpd
        clients.append(c)
        return c

    yield _make
    for c in clients:
        try:
            c.__exit__(None, None, None)
        except Exception:
            pass


@pytest.fixture
def client(make_client):
    return make_client(delay_ms=0)


@pytest.fixture
def slow_client(make_client):
    return make_client(delay_ms=400)


@pytest.fixture(scope="module")
def shared_client(tmp_path_factory):
    """Module-scoped client for hypothesis tests (function fixtures are not allowed there)."""
    mp = pytest.MonkeyPatch()
    base = tmp_path_factory.mktemp("shared")
    for k in ENV_KEYS:
        mp.delenv(k, raising=False)
    mp.setenv("AIGEN_DEMO", "1")
    mp.setenv("AIGEN_DATA_DIR", str(base / "data"))
    mp.setenv("AIGEN_TMP_DIR", str(base / "tmp"))
    mp.setenv("AIGEN_DEMO_DELAY_MS", "0")
    (base / "data").mkdir()
    (base / "tmp").mkdir()
    from app.main import create_app

    c = RecordingClient(create_app())
    c.__enter__()
    yield c
    c.__exit__(None, None, None)
    mp.undo()
