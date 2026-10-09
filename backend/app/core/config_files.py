"""Read/write data/*.json. Atomic writes; providers.json is chmod 600 and never leaves the backend."""
from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger("aigen.config")

DEFAULT_SETTINGS: dict[str, Any] = {
    "confirmThresholdUsd": 5,
    "maxJobsPerBatch": 24,
    "staleDays": 30,
    "maxAttempts": 4,
    "retryBaseSeconds": 2.0,
    "retryMaxSeconds": 60.0,
    "pollIntervalSeconds": 10.0,  # sleep between polls of a long-running operation (Veo/Omni)
    "jobTimeoutSeconds": 900,  # a poll that yields no result after this long ends the job as failed(timeout)
    "enhancerModel": "gemini-3.1-flash-lite",  # [?] text model id for the enhancer; configurable
}

# Hard limits for PUT /api/settings (invariant 21): (type, min, max). Guardrail values cannot be weakened beyond these.
SETTING_LIMITS: dict[str, tuple[str, float, float]] = {
    "confirmThresholdUsd": ("number", 0, 1_000_000),
    "maxJobsPerBatch": ("int", 1, 64),
    "staleDays": ("int", 1, 3650),
    "maxAttempts": ("int", 1, 10),
    "retryBaseSeconds": ("number", 0.001, 3600),
    "retryMaxSeconds": ("number", 0.001, 86400),
    "pollIntervalSeconds": ("number", 0.05, 3600),
    "jobTimeoutSeconds": ("number", 1, 86400),
}

PROVIDERS_FILE = "providers.json"


class ConfigFiles:
    def __init__(self, data_dir: Path, seed_dir: Path | None = None):
        self.dir = Path(data_dir)
        self.seed_dir = Path(seed_dir) if seed_dir else None  # read-only fallback for non-secret defaults
        self._lock = threading.Lock()

    def path(self, name: str) -> Path:
        return self.dir / name

    def read(self, name: str, default: Any) -> Any:
        p = self.path(name)
        if not p.exists():
            return default
        with self._lock:
            return json.loads(p.read_text(encoding="utf-8"))

    def read_seeded(self, name: str, default: Any) -> Any:
        """Read from the data dir; if the file is absent fall back to the shipped seed (never written)."""
        if not self.path(name).exists() and self.seed_dir and (self.seed_dir / name).exists():
            return json.loads((self.seed_dir / name).read_text(encoding="utf-8"))
        return self.read(name, default)

    def write(self, name: str, data: Any, mode: int | None = None) -> None:
        """Atomic: write temp file in same dir, fsync, chmod, rename."""
        self.dir.mkdir(parents=True, exist_ok=True)
        if mode is None and name == PROVIDERS_FILE:
            mode = 0o600
        with self._lock:
            fd, tmp = tempfile.mkstemp(dir=self.dir, prefix=f".{name}.", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                if mode is not None:
                    os.chmod(tmp, mode)
                os.replace(tmp, self.path(name))
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise

    # ---- settings ----
    def settings(self) -> dict[str, Any]:
        """Defaults + settings.json. Unknown keys are ignored; a hand-edited file cannot exceed the hard limits."""
        raw = self.read("settings.json", {})
        out = {**DEFAULT_SETTINGS, **{k: v for k, v in (raw if isinstance(raw, dict) else {}).items()
                                      if k in DEFAULT_SETTINGS}}
        for k, (_, lo, hi) in SETTING_LIMITS.items():
            v = out[k]
            if isinstance(v, bool) or not isinstance(v, int | float) or v != v:
                out[k] = DEFAULT_SETTINGS[k]
            else:
                out[k] = min(max(v, lo), hi)
        return out

    # ---- providers ----
    def ensure_providers_perms(self) -> None:
        """Invariant 10: loosen perms -> fix and warn."""
        p = self.path(PROVIDERS_FILE)
        if not p.exists():
            return
        mode = stat.S_IMODE(p.stat().st_mode)
        if mode & 0o077:
            os.chmod(p, 0o600)
            log.warning("providers.json had permissions %o; fixed to 600", mode)

    def providers(self) -> dict[str, Any]:
        self.ensure_providers_perms()
        return self.read(PROVIDERS_FILE, {})

    def save_providers(self, data: dict[str, Any]) -> None:
        self.write(PROVIDERS_FILE, data, 0o600)


def mask_providers(data: dict[str, Any]) -> dict[str, Any]:
    """Public view of every provider (vertex, openai, byteplus): never includes keys, key paths or key JSON."""
    from app.providers import mask_all

    return mask_all(data)
