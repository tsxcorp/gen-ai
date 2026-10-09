"""FastAPI app factory. `uvicorn app.main:app` from backend/; `python -m app --lan` for LAN mode."""
from __future__ import annotations

import hmac
import ipaddress
import logging
import os
import socket
from contextlib import asynccontextmanager
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import assets, batches, enhance, estimate, events, library, manifests, providers
from app.context import REPO_ROOT, AppContext
from app.core.storage import MAX_UPLOAD
from app.errors import ApiError

log = logging.getLogger("aigen")
UPLOAD_OVERHEAD = 1024 * 1024  # multipart framing + form fields on top of the 20 MB file


SESSION_COOKIE = "aigen_session"
DOC_PATHS = ("/docs", "/openapi.json", "/redoc", "/docs/oauth2-redirect")
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
DEMO_EXTRA_HOSTS = {"testserver"}  # Starlette TestClient default Host; only honoured in demo mode


def _hostname(host_header: str) -> str:
    h = host_header.strip().lower()
    if h.startswith("["):
        return h[1:].split("]", 1)[0]
    return h.rsplit(":", 1)[0] if h.count(":") == 1 else h


def _is_ip(h: str) -> bool:
    try:
        ipaddress.ip_address(h)
    except ValueError:
        return False
    return True


class _BodyTooLarge(Exception):
    pass


class GuardMiddleware:
    """Pure ASGI (SSE-safe) request guard, in this order:

    1. Host allow-list (DNS rebinding), 2. Origin of write requests must equal the app's own origin,
    3. JSON/multipart Content-Type for requests with a body (kills cross-site "simple requests"),
    4. upload body cap enforced while streaming, 5. LAN access token (header) or, for GET of assets/events/docs,
    the HttpOnly session cookie set by POST /api/session. The token is never accepted from the URL.
    """

    def __init__(self, app: Any, token: str | None, lan: bool, session_value: str,
                 extra_hosts: set[str] | None = None, demo: bool = False) -> None:
        self.app = app
        self.token = token
        self.lan = lan
        self.session_value = session_value
        self.hosts = set(LOCAL_HOSTS) | {h.lower() for h in (extra_hosts or set())}
        if demo:
            self.hosts |= DEMO_EXTRA_HOSTS
        if lan:
            name = socket.gethostname().lower()
            self.hosts |= {name, f"{name}.local"}

    # -- helpers --
    def _host_ok(self, host_header: str) -> bool:
        h = _hostname(host_header)
        return bool(h) and (h in self.hosts or (self.lan and _is_ip(h)))  # an IP literal cannot be DNS-rebound

    def _token_ok(self, headers: dict[str, str]) -> bool:
        if not self.token:
            return True
        cand = headers.get("x-access-token", "")
        auth = headers.get("authorization", "")
        if not cand and auth.lower().startswith("bearer "):
            cand = auth[7:].strip()
        return bool(cand) and hmac.compare_digest(cand.encode(), self.token.encode())

    def _cookie_ok(self, headers: dict[str, str]) -> bool:
        raw = headers.get("cookie", "")
        if not raw:
            return False
        jar: SimpleCookie = SimpleCookie()
        try:
            jar.load(raw)
        except Exception:  # noqa: BLE001 - malformed cookie header
            return False
        morsel = jar.get(SESSION_COOKIE)
        return morsel is not None and hmac.compare_digest(morsel.value.encode(), self.session_value.encode())

    @staticmethod
    async def _reject(scope: dict, receive: Any, send: Any, err: ApiError) -> None:
        await JSONResponse(err.body(), status_code=err.status)(scope, receive, send)

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers: dict[str, str] = {}
        for k, v in scope["headers"]:
            headers.setdefault(k.decode("latin-1").lower(), v.decode("latin-1"))
        method = scope["method"].upper()
        path: str = scope["path"]

        if not self._host_ok(headers.get("host", "")):
            await self._reject(scope, receive, send, ApiError("forbidden", "host not allowed"))
            return
        if method in WRITE_METHODS:
            origin = headers.get("origin")
            # Origin must be one of OUR hosts (any port: the Vite dev server is another port of localhost)
            if origin is not None and (origin.lower() == "null" or not self._host_ok(urlsplit(origin).netloc)):
                await self._reject(scope, receive, send, ApiError("forbidden", "cross-origin request rejected"))
                return
            if headers.get("sec-fetch-site", "").lower() == "cross-site":
                await self._reject(scope, receive, send, ApiError("forbidden", "cross-site request rejected"))
                return
            has_body = headers.get("transfer-encoding") is not None or headers.get("content-length", "0").strip() not in ("", "0")
            if has_body:
                ctype = headers.get("content-type", "").split(";")[0].strip().lower()
                want = "multipart/form-data" if path == "/api/uploads" else "application/json"
                if ctype != want:
                    await self._reject(scope, receive, send,
                                       ApiError("invalid", f"Content-Type must be {want}", status=415))
                    return

        if self.lan and self.token:
            protected = (path.startswith("/api/") and path != "/api/health") or path in DOC_PATHS
            if protected and method != "OPTIONS" and not self._token_ok(headers):
                cookie_route = method in ("GET", "HEAD") and (
                    path.startswith("/api/assets/") or path == "/api/events" or path in DOC_PATHS)
                if not (cookie_route and self._cookie_ok(headers)):
                    await self._reject(scope, receive, send, ApiError("auth", "access token required (LAN mode)"))
                    return

        if path == "/api/uploads" and method == "POST":
            try:
                if int(headers.get("content-length", "0") or 0) > MAX_UPLOAD + UPLOAD_OVERHEAD:
                    raise _BodyTooLarge
            except (ValueError, _BodyTooLarge):
                await self._reject(scope, receive, send, ApiError("invalid", "upload too large (max 20 MB)", status=413))
                return
            seen = 0
            started = False

            async def capped_receive() -> Any:
                nonlocal seen
                msg = await receive()
                if msg["type"] == "http.request":
                    seen += len(msg.get("body", b""))
                    if seen > MAX_UPLOAD + UPLOAD_OVERHEAD:
                        raise _BodyTooLarge
                return msg

            async def tracking_send(msg: Any) -> None:
                nonlocal started
                started = True
                await send(msg)

            try:
                await self.app(scope, capped_receive, tracking_send)
            except _BodyTooLarge:
                if not started:
                    await self._reject(scope, receive, send,
                                       ApiError("invalid", "upload too large (max 20 MB)", status=413))
            return
        await self.app(scope, receive, send)


class _StripQuery(logging.Filter):
    """uvicorn's access log prints the full request line; never let a query string (any secret) reach logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        a = record.args
        if isinstance(a, tuple) and len(a) >= 3 and isinstance(a[2], str) and "?" in a[2]:
            record.args = (*a[:2], a[2].split("?", 1)[0], *a[3:])
        return True


def create_app(**kwargs: Any) -> FastAPI:
    ctx = AppContext(**kwargs)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await ctx.shutdown()  # dispose runner + clean tmp/run-*

    app = FastAPI(title="AI Gen Studio", version="0.1.0", lifespan=lifespan)
    app.state.ctx = ctx
    logging.getLogger("uvicorn.access").addFilter(_StripQuery())

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError):
        return JSONResponse(e.body(), status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        # never echo `input`: it could contain key material
        details = [{"loc": [str(x) for x in err["loc"]], "msg": err["msg"]} for err in e.errors()]
        return JSONResponse(ApiError("invalid", "request validation failed", details).body(), status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        kind = "not_found" if e.status_code == 404 else "invalid"
        return JSONResponse(ApiError(kind, str(e.detail), status=e.status_code).body(), status_code=e.status_code)

    @app.get("/api/health")
    def health():
        return {"ok": True, "demo": ctx.demo, "lan": ctx.lan, "tokenRequired": ctx.lan, "models": len(ctx.manifests)}

    @app.post("/api/session")
    def session():
        """Header-authenticated (LAN token) -> HttpOnly SameSite=Strict cookie that <img>/<video>/<a> can use for
        /api/assets, /api/events and the docs, so the token never has to appear in a URL (invariant 20)."""
        resp = JSONResponse({"ok": True})
        resp.set_cookie(SESSION_COOKIE, ctx.session_value, httponly=True, samesite="strict", path="/")
        return resp

    for r in (manifests, estimate, batches, events, assets, library, providers, enhance):
        app.include_router(r.router, prefix="/api")

    dist = REPO_ROOT / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")

    extra = {h.strip() for h in os.environ.get("AIGEN_ALLOWED_HOSTS", "").split(",") if h.strip()}
    app.add_middleware(GuardMiddleware, token=ctx.token, lan=ctx.lan, session_value=ctx.session_value,
                       extra_hosts=extra, demo=ctx.demo)
    if ctx.lan and ctx.token:
        if os.environ.get("AIGEN_TOKEN"):
            print("[ai-gen-studio] LAN mode: access token configured via environment", flush=True)
        else:
            print(f"[ai-gen-studio] LAN mode: access token = {ctx.token}", flush=True)
        print("[ai-gen-studio] send it as `Authorization: Bearer <token>` or `X-Access-Token`, then "
              "POST /api/session to get the cookie used by images/videos (never put it in a URL)", flush=True)
    if ctx.demo:
        print("[ai-gen-studio] DEMO mode: no network calls, no credentials needed", flush=True)
    return app


_app: FastAPI | None = None


def __getattr__(name: str) -> Any:
    """Lazy `app` so importing app.main has no side effects (tests call create_app)."""
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)

