from __future__ import annotations

import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from mangum import Mangum

from procurement_assistant.api import router
from procurement_assistant.auth import configure_auth
from procurement_assistant.database import build_engine, build_session_factory
from procurement_assistant.providers.observability import log_event
from procurement_assistant.settings import Settings, get_settings
from procurement_assistant.ui import router as ui_router


def create_app(
    *, settings: Settings | None = None, session_factory=None, identity_provider=None, token_verifier=None
) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="Procurement Assistant API",
        version="1.0.0",
        description="Tenant-safe restaurant procurement comparison and tracking API",
    )
    if session_factory is None:
        session_factory = build_session_factory(
            build_engine(
                settings.resolved_database_url,
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                use_null_pool=settings.db_use_null_pool,
            )
        )
    if identity_provider is None or token_verifier is None:
        configured_provider, configured_verifier = configure_auth(settings)
        identity_provider = identity_provider or configured_provider
        token_verifier = token_verifier or configured_verifier
    app.state.session_factory = session_factory
    app.state.identity_provider = identity_provider
    app.state.token_verifier = token_verifier

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        started = time.monotonic()
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        try:
            response = await call_next(request)
        except Exception as exc:
            log_event(
                "http_request_failed",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                duration_seconds=round(time.monotonic() - started, 3),
                error_type=type(exc).__name__,
            )
            raise
        log_event(
            "http_request_finished",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_seconds=round(time.monotonic() - started, 3),
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' https: data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if settings.cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    app.include_router(router)
    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent / "static"),
        name="static",
    )
    app.include_router(ui_router)
    return app


app = create_app()
handler = Mangum(app)
