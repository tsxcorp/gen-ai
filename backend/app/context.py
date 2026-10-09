"""AppContext: wires config, manifests, storage, adapters and the job runner."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from pathlib import Path
from typing import Any

from app.adapters.base import ProviderAdapter
from app.adapters.factory import ArkClient, OpenAIClient, VertexClient, build_adapter, make_client
from app.core.config_files import ConfigFiles
from app.core.events import EventHub
from app.core.jobs import JobManager
from app.core.manifest import load_manifests
from app.core.storage import Storage
from app.errors import ApiError
from app.schemas import ModelManifest

REPO_ROOT = Path(__file__).resolve().parents[2]


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


class AppContext:
    def __init__(
        self,
        data_dir: Path | None = None,
        tmp_dir: Path | None = None,
        manifests_dir: Path | None = None,
        demo: bool | None = None,
        lan: bool | None = None,
        token: str | None = None,
    ) -> None:
        self.data_dir = Path(data_dir or os.environ.get("AIGEN_DATA_DIR") or REPO_ROOT / "data")
        self.tmp_dir = Path(tmp_dir or os.environ.get("AIGEN_TMP_DIR") or REPO_ROOT / "tmp")
        self.manifests_dir = Path(manifests_dir or os.environ.get("AIGEN_MANIFESTS_DIR") or REPO_ROOT / "manifests")
        self.demo = env_flag("AIGEN_DEMO") if demo is None else demo
        self.lan = env_flag("AIGEN_LAN") if lan is None else lan
        self.token = (token or os.environ.get("AIGEN_TOKEN") or secrets.token_urlsafe(24)) if self.lan else None

        # value of the HttpOnly session cookie: derived from the token (LAN) or random (local, unauthenticated)
        self.session_value = (hmac.new(self.token.encode(), b"aigen-session-v1", hashlib.sha256).hexdigest()
                              if self.token else secrets.token_urlsafe(24))

        self.config = ConfigFiles(self.data_dir, seed_dir=REPO_ROOT / "data")
        self.config.ensure_providers_perms()
        self.manifests: dict[str, ModelManifest] = load_manifests(self.manifests_dir)
        self.storage = Storage(self.tmp_dir)
        self.hub = EventHub()
        self._clients: dict[str, VertexClient | OpenAIClient | ArkClient] = {}
        self._shutting_down = False
        self.jobs = JobManager(
            self.manifests, self.storage, self.hub,
            adapter_for=self.adapter_for,
            settings=self._settings,
            prices=self.prices,
        )

    def _settings(self) -> dict[str, Any]:
        """settings.json + env override AIGEN_RETRY_BASE_S (demo defaults to a short backoff)."""
        s = self.config.settings()
        env = os.environ.get("AIGEN_RETRY_BASE_S")
        if env:
            s["retryBaseSeconds"] = float(env)
        elif self.demo:
            s["retryBaseSeconds"] = min(float(s["retryBaseSeconds"]), 0.3)
        return s

    def prices(self) -> dict[str, Any]:
        return self.config.read_seeded("prices.json", {"entries": {}})

    def manifest(self, model_id: str) -> ModelManifest:
        m = self.manifests.get(model_id)
        if m is None:
            raise ApiError("invalid", f"unknown modelId {model_id!r}", {"known": sorted(self.manifests)})
        return m

    def provider_configured(self, provider: str) -> bool:
        """Demo mode: every provider counts as configured (no credentials needed)."""
        from app.providers import is_configured

        return self.demo or is_configured(provider, self.config.providers().get(provider))

    def ensure_configured(self, m: ModelManifest) -> None:
        if not self.provider_configured(m.provider):
            raise ApiError("not_configured", f"provider {m.provider} is not configured; open Settings and add its key",
                           {"provider": m.provider, "modelId": m.id})

    def adapter_for(self, m: ModelManifest) -> ProviderAdapter:
        """Share job clients within the current provider configuration generation."""
        if self._shutting_down:
            raise ApiError("invalid", "application is shutting down")
        if self.demo:
            return build_adapter(m, {}, True)
        providers = self.config.providers()
        client = self._clients.get(m.provider)
        if client is None:
            client = make_client(m.provider, providers)
            if client is None:
                raise ApiError("not_configured", f"provider {m.provider} is not configured")
            self._clients[m.provider] = client
        return build_adapter(m, providers, False, client)

    def reset_adapters(self, provider: str | None = None) -> None:
        clients = [self._clients.pop(key) for key in list(self._clients) if provider is None or key == provider]
        self.jobs.reset_adapters(provider)
        for client in clients:
            self.jobs.retire_client(client)

    async def shutdown(self) -> None:
        self._shutting_down = True
        self.hub.close()
        self.reset_adapters()
        await self.jobs.shutdown()
        self.storage.cleanup()
