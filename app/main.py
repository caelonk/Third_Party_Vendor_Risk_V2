"""FastAPI application factory.

Phase 0 wires the app shell: settings, CORS, health probes, and the /api/v1
mount point. Auth, orgs, vendors, dashboard, alerts, and export routers are added
in later phases.
"""
from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import health
from .config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Vendor Risk Platform",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Ops probes at the root.
    app.include_router(health.router)

    # Versioned API surface (routers added per phase).
    api_v1 = APIRouter(prefix="/api/v1")
    app.include_router(api_v1)

    @app.get("/", tags=["ops"])
    def root() -> dict:
        return {"name": "vendor-risk", "version": app.version, "env": settings.env}

    return app


app = create_app()
