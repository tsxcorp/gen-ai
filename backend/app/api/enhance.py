from __future__ import annotations

from fastapi import APIRouter, Depends

from app.adapters.demo import demo_enhance
from app.adapters.vertex_common import VertexClient, VertexConfig
from app.adapters.vertex_text import VertexTextAdapter
from app.api.deps import get_ctx
from app.context import AppContext
from app.errors import ApiError
from app.schemas import CamelModel

router = APIRouter(tags=["enhance"])


class EnhanceBody(CamelModel):
    model_id: str
    prompt: str


@router.post("/enhance")
async def enhance(body: EnhanceBody, ctx: AppContext = Depends(get_ctx)):
    m = ctx.manifest(body.model_id)
    if not body.prompt.strip():
        raise ApiError("invalid", "prompt is empty")
    if ctx.demo:
        return {"suggestion": demo_enhance(m, body.prompt), "demo": True}
    if m.enhancer is None:
        raise ApiError("invalid", f"{m.id} has no enhancer.systemPrompt in its manifest")
    cfg = VertexConfig.from_providers(ctx.config.providers().get("vertex"))
    if cfg is None:
        raise ApiError("auth", "Vertex provider is not configured")
    s = ctx.config.settings()
    adapter = VertexTextAdapter(VertexClient(cfg), s["enhancerModel"], location="global")
    try:
        text = await adapter.enhance(m.enhancer.system_prompt, body.prompt)
    finally:
        await adapter.client.aclose()
    return {"suggestion": text}
