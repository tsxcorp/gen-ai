from __future__ import annotations

import stat
import zipfile

import pytest

from app.core.config_files import ConfigFiles, mask_providers
from app.core.storage import Storage
from app.errors import ApiError


def test_atomic_write_and_providers_mode(tmp_path):
    c = ConfigFiles(tmp_path)
    c.save_providers({"vertex": {"projectId": "p", "serviceAccountJson": {"private_key": "SECRET-K"}}})
    assert stat.S_IMODE((tmp_path / "providers.json").stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".providers.json.*"))  # no temp leftovers
    assert "SECRET-K" not in str(mask_providers(c.providers()))


def test_failed_write_keeps_old_file(tmp_path):
    c = ConfigFiles(tmp_path)
    c.write("a.json", {"x": 1})
    with pytest.raises(TypeError):
        c.write("a.json", {"x": object()})
    assert c.read("a.json", None) == {"x": 1} and not list(tmp_path.glob(".a.json.*"))


def test_storage_sha_zip_cleanup(tmp_path):
    s = Storage(tmp_path)
    a = s.save_bytes(b"hello", "image/png", "output")
    s.set_sidecar(a.id, {"job": {"id": "j"}})
    assert a.sha256 == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    z = zipfile.ZipFile(s.build_zip([a.id, a.id]))
    assert len(z.namelist()) == 2 and z.read(f"{a.id}.png") == b"hello"
    with pytest.raises(ApiError):
        s.build_zip(["missing"])
    s.cleanup()
    assert not s.run_dir.exists()
