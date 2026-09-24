"""Portfolio exports as background jobs: CSV (data) and PDF (formatted report).

``POST /orgs/{id}/exports`` queues a job (202). A worker renders it into object
storage; the SPA polls the job, then follows ``GET .../download``, which checks
membership and redirects to a fresh signed URL valid for a few minutes. Any
member may export (read-only reporting). Every export carries the scope
disclaimer verbatim; see :mod:`app.services.export_service`.
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_session, session_scope
from ..deps import OrgContext, get_org_context
from ..schemas.export import ExportCreate, ExportJobOut
from ..services import audit_service, export_service, object_storage
from ..services.exceptions import UnavailableError
from ..services.object_storage import LocalStorage, ObjectStorage, content_disposition

router = APIRouter(prefix="/orgs/{org_id}/exports", tags=["export"])
files_router = APIRouter(prefix="/export-files", tags=["export"])

Dispatcher = Callable[[int], None]


def get_export_storage() -> ObjectStorage:
    return object_storage.get_storage()


def _enqueue(job_id: int) -> None:
    from ..workers.tasks import run_export  # lazy: keeps Celery off the import path

    run_export.apply_async(args=[job_id])


def get_export_dispatcher(storage: ObjectStorage = Depends(get_export_storage)) -> Dispatcher:
    """How a queued job gets run: a Celery task, or inline for worker-less dev."""
    if not get_settings().export_run_inline:
        return _enqueue

    def run_inline(job_id: int) -> None:
        with session_scope() as db:
            export_service.run_job(db, job_id, storage)

    return run_inline


def _out(view: export_service.ExportJobView) -> ExportJobOut:
    return ExportJobOut.model_validate(view, from_attributes=True)


@router.post("", response_model=ExportJobOut, status_code=status.HTTP_202_ACCEPTED)
def create_export(
    body: ExportCreate,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
    dispatch: Dispatcher = Depends(get_export_dispatcher),
) -> ExportJobOut:
    org_id = ctx.organization.id
    job = export_service.create_job(db, org_id, ctx.membership.user_id, body.format)
    audit_service.record(
        db, org_id=org_id, actor_user_id=ctx.membership.user_id,
        action="export.requested", target_type="export", target_id=job.id,
        extra={"format": body.format.value},
    )
    try:
        dispatch(job.id)
    except Exception as exc:  # broker unreachable: don't leave a job queued forever
        export_service.mark_failed(db, job.id, export_service.DISPATCH_FAILED)
        raise UnavailableError(export_service.DISPATCH_FAILED) from exc
    return _out(export_service.get_job(db, org_id, job.id))


@router.get("", response_model=list[ExportJobOut])
def list_exports(
    limit: int = Query(default=10, ge=1, le=50),
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
) -> list[ExportJobOut]:
    return [_out(v) for v in export_service.list_jobs(db, ctx.organization.id, limit=limit)]


@router.get("/{job_id}", response_model=ExportJobOut)
def get_export(
    job_id: int,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
) -> ExportJobOut:
    return _out(export_service.get_job(db, ctx.organization.id, job_id))


@router.get("/{job_id}/download")
def download_export(
    job_id: int,
    ctx: OrgContext = Depends(get_org_context),
    db: Session = Depends(get_session),
    storage: ObjectStorage = Depends(get_export_storage),
) -> RedirectResponse:
    url = export_service.signed_download_url(db, ctx.organization.id, job_id, storage)
    # 302 to the signed URL; never cached, so a stale link is never replayed.
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND,
                            headers={"Cache-Control": "no-store"})


# --------------------------------------------------------------------------- #
# Local-storage downloads (dev/tests). Stands in for the object store's own    #
# signed-URL endpoint, so it needs no session cookie — the HMAC is the auth.   #
# --------------------------------------------------------------------------- #
@files_router.get("/{key:path}")
def serve_local_export(
    key: str,
    exp: int = Query(...),
    name: str = Query(..., max_length=200),
    content_type: str = Query(..., alias="type", max_length=100),
    sig: str = Query(..., max_length=128),
    storage: ObjectStorage = Depends(get_export_storage),
) -> FileResponse:
    if not isinstance(storage, LocalStorage):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    try:
        valid = storage.verify(key, exp=exp, filename=name, content_type=content_type, sig=sig)
        path = storage.path_for(key) if valid else None
    except ValueError:  # malformed key
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found") from None
    if path is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This download link is invalid or has expired.")
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return FileResponse(
        path,
        media_type=content_type,  # signed, so it can't be switched to text/html
        headers={
            "Content-Disposition": content_disposition(name),
            "Cache-Control": "private, no-store",
        },
    )
