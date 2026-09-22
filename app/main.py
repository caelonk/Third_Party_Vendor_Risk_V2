"""FastAPI application factory.

Phase 0 wires the app shell: settings, CORS, health probes, and the /api/v1
mount point. Auth, orgs, vendors, dashboard, alerts, and export routers are added
in later phases.
"""
from __future__ import annotations

from fastapi import APIRouter, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import auth, health, invitations, me, orgs
from .config import get_settings
from .services.exceptions import (
    AuthError,
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)

# Domain error -> HTTP status.
_ERROR_STATUS = {
    AuthError: 401,
    PermissionDeniedError: 403,
    NotFoundError: 404,
    ConflictError: 409,
    ValidationError: 422,
}


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

    @app.exception_handler(DomainError)
    def _handle_domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        status_code = next(
            (code for typ, code in _ERROR_STATUS.items() if isinstance(exc, typ)), 400
        )
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    # Ops probes at the root.
    app.include_router(health.router)

    # Versioned API surface.
    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(auth.router)
    api_v1.include_router(orgs.router)
    api_v1.include_router(invitations.router)
    api_v1.include_router(me.router)
    app.include_router(api_v1)

    @app.get("/", tags=["ops"])
    def root() -> dict:
        return {"name": "vendor-risk", "version": app.version, "env": settings.env}

    return app


app = create_app()
