"""Alert rules, sync-time evaluation, and the in-app notification feed.

Alerts are opt-in: a notification is only written when the org has an active
rule of the matching type. Each notification has a unique ``dedup_key`` so a
re-sync never produces a duplicate. External dispatch (email / Slack via
``org_integrations``) is wired by the worker in a later slice; here notifications
are recorded for the in-app feed.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.constants import TIER_ORDER, WATCHLIST_TIERS

from ..models import (
    AlertChannel,
    AlertRule,
    AlertType,
    Notification,
    NotificationStatus,
    Vendor,
)
from .exceptions import NotFoundError


# --------------------------------------------------------------------------- #
# Alert rule CRUD                                                              #
# --------------------------------------------------------------------------- #
def list_rules(db: Session, org_id: int) -> list[AlertRule]:
    return list(
        db.scalars(
            select(AlertRule).where(AlertRule.org_id == org_id).order_by(AlertRule.id)
        )
    )


def create_rule(
    db: Session, org_id: int, *, type: AlertType, channel: AlertChannel, config: dict
) -> AlertRule:
    rule = AlertRule(org_id=org_id, type=type, channel=channel, config=config or {})
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def update_rule(
    db: Session, org_id: int, rule_id: int, *, is_active: bool | None, config: dict | None
) -> AlertRule:
    rule = db.scalar(
        select(AlertRule).where(AlertRule.id == rule_id, AlertRule.org_id == org_id)
    )
    if rule is None:
        raise NotFoundError("Alert rule not found")
    if is_active is not None:
        rule.is_active = is_active
    if config is not None:
        rule.config = config
    db.commit()
    db.refresh(rule)
    return rule


def delete_rule(db: Session, org_id: int, rule_id: int) -> None:
    rule = db.scalar(
        select(AlertRule).where(AlertRule.id == rule_id, AlertRule.org_id == org_id)
    )
    if rule is None:
        raise NotFoundError("Alert rule not found")
    db.delete(rule)
    db.commit()


# --------------------------------------------------------------------------- #
# Notification feed                                                           #
# --------------------------------------------------------------------------- #
def list_notifications(db: Session, org_id: int, *, limit: int = 50) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification)
            .where(Notification.org_id == org_id)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
    )


def unread_count(db: Session, org_id: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.org_id == org_id, Notification.read_at.is_(None))
        )
        or 0
    )


def mark_read(db: Session, org_id: int, notification_id: int) -> Notification:
    n = db.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.org_id == org_id
        )
    )
    if n is None:
        raise NotFoundError("Notification not found")
    if n.read_at is None:
        n.read_at = datetime.now(UTC)
        db.commit()
        db.refresh(n)
    return n


def mark_all_read(db: Session, org_id: int) -> int:
    rows = db.scalars(
        select(Notification).where(
            Notification.org_id == org_id, Notification.read_at.is_(None)
        )
    ).all()
    now = datetime.now(UTC)
    for n in rows:
        n.read_at = now
    db.commit()
    return len(rows)


# --------------------------------------------------------------------------- #
# Evaluation                                                                  #
# --------------------------------------------------------------------------- #
def _emit(db: Session, org_id: int, vendor_id: int, type_: AlertType, dedup_key: str,
          title: str, body: str | None) -> Notification | None:
    if db.scalar(select(Notification.id).where(Notification.dedup_key == dedup_key)):
        return None
    n = Notification(
        org_id=org_id, vendor_id=vendor_id, type=type_, dedup_key=dedup_key,
        title=title, body=body, status=NotificationStatus.pending,
    )
    db.add(n)
    db.flush()
    return n


def _active_types(db: Session, org_id: int) -> set[AlertType]:
    rows = db.scalars(
        select(AlertRule.type).where(AlertRule.org_id == org_id, AlertRule.is_active.is_(True))
    ).all()
    return set(rows)


def evaluate_on_sync(db: Session, org_id: int, vendor: Vendor, prev, new) -> list[Notification]:
    """Diff the prior vs new snapshot for a vendor and emit alerts for active
    rules (tier_change, new_kev). Commits. ``prev`` may be None (first sync)."""
    types = _active_types(db, org_id)
    today = date.today().isoformat()
    emitted: list[Notification] = []

    if AlertType.tier_change in types and prev is not None and prev.tier != new.tier:
        rose = TIER_ORDER.index(new.tier) > TIER_ORDER.index(prev.tier)
        verb = "rose to" if rose else "changed to"
        n = _emit(
            db, org_id, vendor.id, AlertType.tier_change,
            f"{org_id}:{vendor.id}:tier_change:{prev.tier}->{new.tier}:{today}",
            f"{vendor.name}: risk tier {verb} {new.tier}",
            f"Previous tier: {prev.tier}.",
        )
        if n:
            emitted.append(n)

    if AlertType.new_kev in types:
        prev_kev = prev.kev_count if prev is not None else 0
        if new.kev_count > prev_kev:
            delta = new.kev_count - prev_kev
            n = _emit(
                db, org_id, vendor.id, AlertType.new_kev,
                f"{org_id}:{vendor.id}:new_kev:{new.kev_count}:{today}",
                f"{vendor.name}: {delta} new known-exploited CVE(s)",
                f"Now {new.kev_count} known-exploited vulnerabilities.",
            )
            if n:
                emitted.append(n)

    if emitted:
        db.commit()
    return emitted


def evaluate_renewals(db: Session, org_id: int, *, reference: date | None = None) -> list[Notification]:
    """Emit renewal_due alerts for High/Critical vendors renewing within the
    rule's window. Intended to run on a daily scan."""
    rule = db.scalar(
        select(AlertRule).where(
            AlertRule.org_id == org_id,
            AlertRule.type == AlertType.renewal_due,
            AlertRule.is_active.is_(True),
        )
    )
    if rule is None:
        return []
    reference = reference or date.today()
    window = int(rule.config.get("days", 90))
    today = reference.isoformat()
    emitted: list[Notification] = []

    # Latest snapshot per vendor gives the current tier; join through vendors.
    from .scoring_service import assess_vendor  # local import avoids a cycle

    for vendor in db.scalars(select(Vendor).where(Vendor.org_id == org_id)):
        if vendor.contract_renewal_date is None:
            continue
        days = (vendor.contract_renewal_date - reference).days
        if not (0 <= days <= window):
            continue
        tier = assess_vendor(db, vendor)["tier"]
        if tier not in WATCHLIST_TIERS:
            continue
        n = _emit(
            db, org_id, vendor.id, AlertType.renewal_due,
            f"{org_id}:{vendor.id}:renewal_due:{vendor.contract_renewal_date.isoformat()}:{today}",
            f"{vendor.name}: {tier} vendor renews in {days} day(s)",
            f"Contract renewal on {vendor.contract_renewal_date.isoformat()}.",
        )
        if n:
            emitted.append(n)

    if emitted:
        db.commit()
    return emitted
