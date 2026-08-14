"""FastAPI app factory: CORS, request-ID middleware, router mounting.

Error handling (the closed code set from contract §7.4) lives in
`app.errors.register_exception_handlers` — this file only wires it in.
"""

from __future__ import annotations

import logging
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.errors import REQUEST_ID_HEADER, register_exception_handlers
from app.logging_config import configure_logging
from app.observability import init_sentry
from app.redis_client import close_arq_pool
from app.routers import admin, alerts, auth, health, meta, monitors, orgs, scans, waitlist

logger = logging.getLogger("app")


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    yield
    await close_arq_pool()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    init_sentry(settings)

    app = FastAPI(
        title="SUN-DRAM Scanner API",
        version="1.0.0",
        docs_url="/api/docs" if settings.app_env != "production" else None,
        redoc_url=None,
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        # Phase 2 §7.6: the session cookie only crosses origins (dev: web on
        # :3000, api on :8000) if the browser is told it may — credentialed
        # CORS requires this on the server AND an explicit origin list, never
        # "*" (browsers refuse the combination), which cors_origins_list
        # (§4) already guarantees.
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )

    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = f"req_{secrets.token_hex(4)}"
        request.state.request_id = request_id
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - start) * 1000)
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response

    register_exception_handlers(app)

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(scans.router, prefix="/api/v1")
    app.include_router(meta.router, prefix="/api/v1")
    app.include_router(waitlist.router, prefix="/api/v1")
    app.include_router(admin.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(orgs.router, prefix="/api/v1")
    app.include_router(monitors.router, prefix="/api/v1")
    app.include_router(alerts.router, prefix="/api/v1")

    return app


app = create_app()
