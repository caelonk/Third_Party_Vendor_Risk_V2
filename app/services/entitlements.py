"""Plans and what each allows, enforced in the service layer (never only in the UI).

``organizations.plan`` is the org's *effective* plan: billing webhooks write it
(see :mod:`app.services.billing_service`), and everything here reads it.

Downgrades never delete or hide data. An org over a limit simply can't add
more until it's back under; its sync interval is raised to the plan's minimum
when the next sync is scheduled; PDF reports ask for an upgrade.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Invitation, Membership, Organization, Vendor
from .exceptions import PlanLimitError


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    # Monthly price in US cents. Demo pricing (billing runs in Stripe test mode
    # only), and it must equal the Stripe price: scripts/stripe_setup.py checks.
    price_cents: int
    max_vendors: int | None  # None = unlimited
    max_members: int | None  # members + pending invitations; None = unlimited
    min_sync_hours: int  # the most frequent auto-sync allowed
    pdf_reports: bool


PLANS: dict[str, Plan] = {
    "free": Plan("free", "Free", 0, max_vendors=10, max_members=3, min_sync_hours=24,
                 pdf_reports=False),
    "team": Plan("team", "Team", 4999, max_vendors=100, max_members=10, min_sync_hours=6,
                 pdf_reports=True),
    "business": Plan("business", "Business", 19999, max_vendors=1000, max_members=None,
                     min_sync_hours=1, pdf_reports=True),
}
PLAN_ORDER = ("free", "team", "business")
PAID_PLANS = ("team", "business")


def format_price(plan: Plan) -> str:
    """"$49.99" (or "$49" for whole dollars, "$0" for Free)."""
    dollars, cents = divmod(plan.price_cents, 100)
    return f"${dollars:,}.{cents:02d}" if cents else f"${dollars:,}"


def plan_for(org: Organization) -> Plan:
    # An unknown stored value is treated as Free rather than trusted.
    return PLANS.get(org.plan, PLANS["free"])


def _next_plan(plan: Plan) -> Plan | None:
    idx = PLAN_ORDER.index(plan.id)
    return PLANS[PLAN_ORDER[idx + 1]] if idx + 1 < len(PLAN_ORDER) else None


def _upgrade_hint(plan: Plan, offer: Callable[[Plan], str]) -> str:
    nxt = _next_plan(plan)
    return f" Upgrade to {nxt.name} {offer(nxt)}." if nxt else ""


# --------------------------------------------------------------------------- #
# Usage                                                                        #
# --------------------------------------------------------------------------- #
def vendor_count(db: Session, org_id: int) -> int:
    return db.scalar(
        select(func.count()).select_from(Vendor).where(Vendor.org_id == org_id)
    ) or 0


def member_count(db: Session, org_id: int) -> int:
    return db.scalar(
        select(func.count()).select_from(Membership).where(Membership.org_id == org_id)
    ) or 0


def pending_invite_count(db: Session, org_id: int, *, now: datetime | None = None) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Invitation)
        .where(
            Invitation.org_id == org_id,
            Invitation.accepted_at.is_(None),
            Invitation.expires_at > (now or datetime.now(UTC)),
        )
    ) or 0


# --------------------------------------------------------------------------- #
# Checks (raise PlanLimitError -> HTTP 402)                                    #
# --------------------------------------------------------------------------- #
def require_vendor_capacity(db: Session, org: Organization, adding: int = 1) -> None:
    plan = plan_for(org)
    if plan.max_vendors is None or adding <= 0:
        return
    used = vendor_count(db, org.id)
    if used + adding <= plan.max_vendors:
        return
    hint = _upgrade_hint(
        plan, lambda p: "for unlimited vendors" if p.max_vendors is None
        else f"for up to {p.max_vendors:,} vendors"
    )
    if adding == 1:
        raise PlanLimitError(
            f"The {plan.name} plan includes {plan.max_vendors:,} vendors, and this "
            f"organization has {used:,}.{hint}"
        )
    room = max(plan.max_vendors - used, 0)
    raise PlanLimitError(
        f"This would add {adding:,} vendors, but the {plan.name} plan has room for "
        f"{room:,} more ({used:,} of {plan.max_vendors:,} used).{hint}"
    )


def require_member_capacity(db: Session, org: Organization, *, accepting: bool = False) -> None:
    """Inviting counts members + pending invitations; accepting counts members
    only (the invitation being accepted already holds a seat)."""
    plan = plan_for(org)
    if plan.max_members is None:
        return
    members = member_count(db, org.id)
    if accepting:
        if members < plan.max_members:
            return
        raise PlanLimitError(
            f"This organization has reached its {plan.name} plan limit of "
            f"{plan.max_members} members. Ask an owner to upgrade, then accept again."
        )
    if members + pending_invite_count(db, org.id) < plan.max_members:
        return
    hint = _upgrade_hint(
        plan, lambda p: "for unlimited seats" if p.max_members is None
        else f"for {p.max_members} seats"
    )
    raise PlanLimitError(
        f"The {plan.name} plan includes {plan.max_members} seats, counting pending "
        f"invitations, and all are in use.{hint}"
    )


def require_sync_interval(org: Organization, hours: int) -> None:
    plan = plan_for(org)
    if hours >= plan.min_sync_hours:
        return
    hint = _upgrade_hint(plan, lambda p: f"to sync as often as every {p.min_sync_hours}h")
    raise PlanLimitError(
        f"The {plan.name} plan syncs at most every {plan.min_sync_hours} hours.{hint}"
    )


def require_pdf_reports(org: Organization) -> None:
    plan = plan_for(org)
    if plan.pdf_reports:
        return
    raise PlanLimitError(
        f"PDF reports aren't included in the {plan.name} plan (CSV export is). "
        "Upgrade to Team for PDF reports."
    )
