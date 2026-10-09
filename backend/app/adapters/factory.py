"""Adapter selection: AIGEN_DEMO=1 -> DemoAdapter for everything; else the real adapter of the model's provider."""
from __future__ import annotations

from typing import Any

from app.adapters.base import ProviderAdapter
from app.adapters.byteplus_seedance import ArkClient, ByteplusConfig, SeedanceAdapter
from app.adapters.demo import DemoAdapter
from app.adapters.openai_image import OpenAIClient, OpenAIConfig, OpenAIImageAdapter
from app.adapters.vertex_common import VertexClient, VertexConfig
from app.adapters.vertex_image import VertexImageAdapter
from app.adapters.vertex_omni import VertexOmniAdapter
from app.adapters.vertex_veo import VertexVeoAdapter
from app.errors import ApiError
from app.schemas import ModelManifest

_REAL = {
    "vertex_image": VertexImageAdapter, "vertex_omni": VertexOmniAdapter, "vertex_veo": VertexVeoAdapter,
    "openai_image": OpenAIImageAdapter, "byteplus_seedance": SeedanceAdapter,
}
SETTINGS_HINT = "PUT /api/providers/{id}"


def make_client(provider: str, providers: dict[str, Any]) -> VertexClient | OpenAIClient | ArkClient | None:
    """Client for one provider from ITS OWN config entry only; None when that provider is not configured."""
    cfg = providers.get(provider)
    if provider == "vertex":
        v = VertexConfig.from_providers(cfg)
        return VertexClient(v) if v else None
    if provider == "openai":
        o = OpenAIConfig.from_providers(cfg)
        return OpenAIClient(o) if o else None
    if provider == "byteplus":
        b = ByteplusConfig.from_providers(cfg)
        return ArkClient(b) if b else None
    return None


def build_adapter(
    m: ModelManifest,
    providers: dict[str, Any],
    demo: bool,
    client: VertexClient | OpenAIClient | ArkClient | None = None,
) -> ProviderAdapter:
    if demo:
        return DemoAdapter(m)  # type: ignore[return-value]
    if client is None:
        client = make_client(m.provider, providers)
    if client is None:
        raise ApiError("not_configured", f"provider {m.provider} is not configured ({SETTINGS_HINT.format(id=m.provider)})")
    return _REAL[m.adapter](m, client)  # type: ignore[arg-type,return-value]


def payload_builder(m: ModelManifest, providers: dict[str, Any], demo: bool) -> ProviderAdapter:
    """Adapter usable only for build_payload (no credentials needed)."""
    if demo:
        return DemoAdapter(m)  # type: ignore[return-value]
    return _REAL[m.adapter](m, None)  # type: ignore[arg-type,return-value]
