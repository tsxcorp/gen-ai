from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.api.deps import get_ctx
from app.context import AppContext
from app.core.events import EventHub

router = APIRouter(tags=["events"])


@router.get("/events")
async def events(request: Request, ctx: AppContext = Depends(get_ctx)):
    """SSE: job.updated / batch.updated.

    Live streaming is for clients that ask for it (`Accept: text/event-stream`, as EventSource does) and
    honours Last-Event-ID replay. Any other client gets the retained recent events as a finite snapshot,
    so plain HTTP clients and test clients never hang on an endless response.
    """
    live = "text/event-stream" in request.headers.get("accept", "")
    try:
        last_id = int(request.headers.get("last-event-id") or 0)
    except ValueError:
        last_id = 0
    backlog = ctx.hub.since(last_id) if (last_id or not live) else []
    q = ctx.hub.subscribe() if live else None

    async def gen():
        try:
            yield "retry: 1500\n: connected\n\n"
            for eid, name, data in backlog:
                yield EventHub.format(name, data, eid)
            if q is None:
                return
            while True:
                try:
                    eid, name, data = await asyncio.wait_for(q.get(), timeout=15)
                except TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": keepalive\n\n"
                    continue
                if name == "__close__":
                    break
                if eid > last_id or not last_id:
                    yield EventHub.format(name, data, eid)
        finally:
            if q is not None:
                ctx.hub.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
