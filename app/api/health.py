"""Liveness and readiness probes."""
from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import text

router = APIRouter(tags=["ops"])


@router.get("/healthz")
def healthz() -> dict:
    """Liveness: the process is up. No dependency checks."""
    return {"status": "ok"}


@router.get("/readyz")
def readyz(response: Response) -> dict:
    """Readiness: can we reach Postgres? Returns 503 if not."""
    from ..db import get_engine

    checks: dict[str, str] = {}
    ok = True
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 — surface any connectivity failure
        checks["database"] = f"error: {type(exc).__name__}"
        ok = False

    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ok else "not ready", "checks": checks}
