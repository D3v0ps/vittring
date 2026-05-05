"""FastAPI application factory.

Wires the routers, middleware, static files, and lifecycle events. The
scheduler runs as a separate systemd unit (``vittring-scheduler``); this
process serves HTTP only.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import sentry_sdk
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sentry_sdk.integrations.fastapi import FastApiIntegration

from vittring.api import (
    account,
    admin,
    auth,
    billing,
    health,
    public,
    subscriptions,
)
from vittring.api import unsubscribe as unsubscribe_router
from vittring.api import webhooks
from vittring.config import get_settings
from vittring.db import dispose_engine
from vittring.logging import configure_logging, get_logger
from vittring.security.csrf import CSRFMiddleware
from vittring.security.headers import SecurityHeadersMiddleware
from vittring.utils.errors import VittringError

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn.get_secret_value(),
            environment=settings.sentry_environment,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            integrations=[FastApiIntegration()],
        )
    log = get_logger(__name__)
    log.info("api_started", env=settings.app_env)
    try:
        yield
    finally:
        await dispose_engine()
        log.info("api_stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Vittring",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CSRFMiddleware)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(health.router)
    app.include_router(public.router)
    app.include_router(auth.router)
    app.include_router(account.router)
    app.include_router(subscriptions.router)
    app.include_router(billing.router)
    app.include_router(webhooks.router)
    app.include_router(unsubscribe_router.router)
    app.include_router(admin.router)

    @app.exception_handler(VittringError)
    async def _vittring_handler(_: Request, exc: VittringError) -> JSONResponse:
        return JSONResponse(
            {"detail": exc.__class__.__name__.lower()},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    @app.exception_handler(HTTPException)
    async def _http_handler(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    return app


app = create_app()
