"""tmp/ storage: assets (uploads + outputs), sha256, ZIP (original bytes + JSON sidecar), cleanup.

Files live in tmp/run-<uuid>/ and that sub-directory is removed at shutdown. Bytes are never re-encoded.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

from app.errors import ApiError
from app.schemas import Asset

EXT = {
    "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/heic": "heic",
    "image/heif": "heif", "video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov",
}


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def sweep_stale_runs(root: Path) -> int:
    """Remove tmp/run-* left by a killed process. Run dirs are named run-<pid>-<id>; a dir is kept only if that
    pid is a running process (so two app instances sharing tmp/ do not delete each other's files, and this
    process's own dirs are never touched). Dirs without a pid in the name are stale by definition."""
    n = 0
    for d in root.glob("run-*"):
        if not d.is_dir():
            continue
        m = re.match(r"run-(\d+)-", d.name)
        pid = int(m.group(1)) if m else 0
        if pid and (pid == os.getpid() or _pid_alive(pid)):
            continue
        shutil.rmtree(d, ignore_errors=True)
        n += 1
    return n


def file_sha256(path: Path) -> tuple[int, str]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
            size += len(chunk)
    return size, h.hexdigest()


MAX_UPLOAD = 20 * 1024 * 1024


class Storage:
    def __init__(self, tmp_root: Path):
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.root = tmp_root
        sweep_stale_runs(tmp_root)
        self.run_dir = tmp_root / f"run-{os.getpid()}-{uuid.uuid4().hex[:12]}"
        self.run_dir.mkdir()
        self._assets: dict[str, Asset] = {}
        self._sidecars: dict[str, dict[str, Any]] = {}

    # ---- write ----
    def new_asset_id(self) -> str:
        return uuid.uuid4().hex

    def save_bytes(self, data: bytes, mime: str, kind: str, meta: dict[str, Any] | None = None) -> Asset:
        aid = self.new_asset_id()
        path = self.run_dir / f"{aid}.{EXT.get(mime, 'bin')}"
        path.write_bytes(data)
        return self._register(aid, path, mime, hashlib.sha256(data).hexdigest(), len(data), kind, meta or {})

    def register_file(self, path: Path, mime: str, kind: str, meta: dict[str, Any] | None = None,
                      sha256: str | None = None, size_bytes: int | None = None) -> Asset:
        """Register a file already written inside run_dir (adapters download straight to disk). When the adapter
        hashed while writing, sha256/size are passed in; otherwise the file is hashed in chunks (never read whole)."""
        if sha256 is None or size_bytes is None:
            size_bytes, sha256 = file_sha256(path)
        return self._register(path.stem, path, mime, sha256, size_bytes, kind, meta or {})

    def _register(self, aid: str, path: Path, mime: str, sha: str, size: int, kind: str, meta: dict) -> Asset:
        asset = Asset(id=aid, path=str(path), mime=mime, sha256=sha, size_bytes=size, kind=kind, meta=meta)  # type: ignore[arg-type]
        self._assets[aid] = asset
        return asset

    def new_upload_path(self, mime: str) -> tuple[str, Path]:
        aid = self.new_asset_id()
        return aid, self.run_dir / f"{aid}.{EXT.get(mime, 'bin')}"

    def register_upload(self, aid: str, path: Path, mime: str, sha256: str, size: int,
                        meta: dict[str, Any]) -> Asset:
        return self._register(aid, path, mime, sha256, size, "upload", meta)

    def set_sidecar(self, asset_id: str, sidecar: dict[str, Any]) -> None:
        self._sidecars[asset_id] = sidecar

    # ---- read ----
    def get(self, asset_id: str) -> Asset:
        a = self._assets.get(asset_id)
        if a is None or not Path(a.path).exists():
            raise ApiError("not_found", f"asset {asset_id} not found")
        return a

    def read_bytes(self, asset_id: str) -> bytes:
        return Path(self.get(asset_id).path).read_bytes()

    # ---- zip ----
    def build_zip(self, asset_ids: list[str]) -> tempfile.SpooledTemporaryFile:
        if not asset_ids:
            raise ApiError("invalid", "assetIds is empty")
        assets = [self.get(i) for i in dict.fromkeys(asset_ids)]  # 404 before writing anything
        buf = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024)
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as z:
            for a in assets:
                p = Path(a.path)
                z.write(p, arcname=p.name)  # original bytes
                side = {
                    "assetId": a.id, "file": p.name, "mime": a.mime, "sha256": a.sha256,
                    "sizeBytes": a.size_bytes, "kind": a.kind, **self._sidecars.get(a.id, {}),
                }
                z.writestr(f"{a.id}.json", json.dumps(side, ensure_ascii=False, indent=2))
        buf.seek(0)
        return buf

    # ---- cleanup ----
    def cleanup(self) -> None:
        shutil.rmtree(self.run_dir, ignore_errors=True)
        self._assets.clear()
        self._sidecars.clear()
