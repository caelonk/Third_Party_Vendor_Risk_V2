"""Org-scoped vendor CRUD. Every function takes ``org_id`` and filters by it."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Vendor
from .exceptions import ConflictError, NotFoundError

_BUSINESS_FIELDS = (
    "cpe_prefix",
    "annual_contract_value",
    "data_sensitivity",
    "business_criticality",
    "contract_renewal_date",
)


def list_vendors(db: Session, org_id: int) -> list[Vendor]:
    return list(
        db.scalars(
            select(Vendor).where(Vendor.org_id == org_id).order_by(Vendor.name)
        )
    )


def get_vendor(db: Session, org_id: int, vendor_id: int) -> Vendor:
    vendor = db.scalar(
        select(Vendor).where(Vendor.id == vendor_id, Vendor.org_id == org_id)
    )
    if vendor is None:
        raise NotFoundError("Vendor not found")
    return vendor


def create_vendor(db: Session, org_id: int, data: dict) -> Vendor:
    name = data["name"].strip()
    if db.scalar(
        select(Vendor.id).where(Vendor.org_id == org_id, Vendor.name == name)
    ) is not None:
        raise ConflictError(f"A vendor named {name!r} already exists")
    vendor = Vendor(
        org_id=org_id,
        name=name,
        is_mapped=False,
        **{k: data.get(k) for k in _BUSINESS_FIELDS},
    )
    db.add(vendor)
    db.commit()
    db.refresh(vendor)
    return vendor


def update_vendor(db: Session, org_id: int, vendor_id: int, data: dict) -> Vendor:
    vendor = get_vendor(db, org_id, vendor_id)
    if "name" in data and data["name"] is not None:
        new_name = data["name"].strip()
        if new_name != vendor.name and db.scalar(
            select(Vendor.id).where(Vendor.org_id == org_id, Vendor.name == new_name)
        ) is not None:
            raise ConflictError(f"A vendor named {new_name!r} already exists")
        vendor.name = new_name
    for field in _BUSINESS_FIELDS:
        if field in data:
            setattr(vendor, field, data[field])
    db.commit()
    db.refresh(vendor)
    return vendor


def delete_vendor(db: Session, org_id: int, vendor_id: int) -> None:
    vendor = get_vendor(db, org_id, vendor_id)
    db.delete(vendor)
    db.commit()
