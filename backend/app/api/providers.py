"""providers.json: key material goes in, never comes back out. One provider per request: a change to one entry
never reads, rewrites or drops another provider's entry (invariant 26)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.adapters.factory import make_client
from app.api.deps import get_ctx
from app.context import AppContext
from app.errors import ApiError
from app.providers import PROVIDER_IDS, apply_put, mask_all, mask_one

router = APIRouter(tags=["providers"])


def _known(provider_id: str) -> str:
    if provider_id not in PROVIDER_IDS:
        raise ApiError("not_found", f"unknown provider {provider_id!r}", {"known": list(PROVIDER_IDS)})
    return provider_id


@router.get("/providers")
def get_providers(ctx: AppContext = Depends(get_ctx)):
    return mask_all(ctx.config.providers())


@router.put("/providers/{provider_id}")
async def put_provider(provider_id: str, request: Request, ctx: AppContext = Depends(get_ctx)):
    _known(provider_id)
    try:
        body = await request.json()
    except ValueError:
        raise ApiError("invalid", "body is not valid JSON") from None
    providers = ctx.config.providers()
    providers[provider_id] = apply_put(provider_id, body, providers.get(provider_id))
    ctx.config.save_providers(providers)
    ctx.reset_adapters(provider_id)
    return mask_one(provider_id, providers[provider_id])


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: str, ctx: AppContext = Depends(get_ctx)):
    _known(provider_id)
    providers = ctx.config.providers()
    if provider_id in providers:
        del providers[provider_id]
        ctx.config.save_providers(providers)
        ctx.reset_adapters(provider_id)
    return mask_one(provider_id, None)


@router.post("/providers/{provider_id}/test")
async def test_provider(provider_id: str, ctx: AppContext = Depends(get_ctx)) -> dict[str, Any]:
    _known(provider_id)
    if ctx.demo:
        return {"ok": True, "message": "demo mode: no credentials needed", "demo": True}
    client = make_client(provider_id, ctx.config.providers())
    if client is None:
        raise ApiError("not_configured", f"provider {provider_id} is not configured")
    try:
        await client.test()
    finally:
        await client.aclose()
    return {"ok": True, "message": "credentials accepted"}
