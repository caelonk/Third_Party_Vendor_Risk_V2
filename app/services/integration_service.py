"""Per-org integration settings: the encrypted NVD API key and sync cadence.

The NVD key is envelope-encrypted at rest (Fernet) and write-only over the API —
only ciphertext is stored, and the plaintext is decrypted solely inside the sync
worker. ``sync_cadence_hours`` drives how often scheduled auto-sync revisits a
vendor. See [[scheduled_sync_service]] for how these are consumed.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import OrgIntegration
from ..security import decrypt_secret, encrypt_secret

# Sentinel so "field absent" is distinguishable from "set to null/clear".
_UNSET = object()

MIN_CADENCE_HOURS = 1
MAX_CADENCE_HOURS = 24 * 30  # a month; longer defeats the point of auto-sync


def get_integration(db: Session, org_id: int) -> OrgIntegration | None:
    return db.query(OrgIntegration).filter(OrgIntegration.org_id == org_id).one_or_none()


def get_or_create(db: Session, org_id: int) -> OrgIntegration:
    integ = get_integration(db, org_id)
    if integ is None:
        integ = OrgIntegration(org_id=org_id)
        db.add(integ)
        db.flush()
    return integ


def update_integration(
    db: Session,
    org_id: int,
    *,
    nvd_api_key: str | None | object = _UNSET,
    sync_cadence_hours: int | None | object = _UNSET,
) -> OrgIntegration:
    """Patch an org's integration. Absent fields are left untouched.

    ``nvd_api_key``: a non-empty string is encrypted and stored; ``None`` or an
    empty/blank string clears the stored key (falls back to the system key).
    """
    integ = get_or_create(db, org_id)

    if nvd_api_key is not _UNSET:
        key = nvd_api_key
        if key is None or (isinstance(key, str) and not key.strip()):
            integ.nvd_api_key_ct = None
        else:
            integ.nvd_api_key_ct = encrypt_secret(str(key).strip())

    if sync_cadence_hours is not _UNSET and isinstance(sync_cadence_hours, int):
        integ.sync_cadence_hours = max(
            MIN_CADENCE_HOURS, min(MAX_CADENCE_HOURS, sync_cadence_hours)
        )

    db.commit()
    db.refresh(integ)
    return integ


def apply_patch(db: Session, org_id: int, patch: dict) -> OrgIntegration:
    """Apply only the fields present in ``patch`` (from ``exclude_unset``)."""
    kwargs: dict = {}
    if "nvd_api_key" in patch:
        kwargs["nvd_api_key"] = patch["nvd_api_key"]
    if "sync_cadence_hours" in patch:
        kwargs["sync_cadence_hours"] = patch["sync_cadence_hours"]
    if not kwargs:
        return get_or_create(db, org_id)
    return update_integration(db, org_id, **kwargs)


def cadence_hours(db: Session, org_id: int) -> int:
    """The org's sync cadence, or the platform default when unconfigured."""
    integ = get_integration(db, org_id)
    if integ is not None:
        return integ.sync_cadence_hours
    return get_settings().default_sync_cadence_hours


def resolve_nvd_api_key(db: Session, org_id: int) -> str | None:
    """The org's own decrypted NVD key, or ``None`` to fall back to the system key."""
    integ = get_integration(db, org_id)
    if integ is None or not integ.nvd_api_key_ct:
        return None
    return decrypt_secret(integ.nvd_api_key_ct)
