"""Run with: uv run fastapi dev src/app/main.py"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api import api_router
from app.core import events
from app.core.config import settings
from app.core.database import engine
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.modules.webhooks.delivery import deliver_event


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    configure_logging()
    yield
    await events.drain()  # let in-flight webhook deliveries finish
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        if settings.is_production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    )
    if settings.allowed_hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    register_exception_handlers(app)
    events.subscribe(deliver_event)

    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": settings.app_version, "commit": settings.git_sha}

    return app


app = create_app()
