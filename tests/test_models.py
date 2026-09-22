"""Model smoke tests: build the schema on in-memory SQLite and exercise the
core relationships and constraints. (Postgres-specific behavior is verified by
the migration running against the Postgres service in CI.)"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Base,
    Membership,
    Organization,
    Role,
    User,
    UserPreference,
    Vulnerability,
)


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    engine.dialect.supports_sane_rowcount = True
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_org_user_membership_roundtrip(session):
    org = Organization(name="Acme", slug="acme")
    user = User(email="a@example.com", name="A")
    session.add_all([org, user])
    session.flush()
    session.add(Membership(org_id=org.id, user_id=user.id, role=Role.owner))
    session.add(UserPreference(user_id=user.id))
    session.commit()

    loaded = session.get(Organization, org.id)
    assert loaded.memberships[0].role is Role.owner
    assert loaded.memberships[0].user.email == "a@example.com"
    assert session.get(User, user.id).preferences.dashboard_layout == []


def test_membership_is_unique_per_org_user(session):
    org = Organization(name="Acme", slug="acme")
    user = User(email="a@example.com")
    session.add_all([org, user])
    session.flush()
    session.add(Membership(org_id=org.id, user_id=user.id, role=Role.member))
    session.commit()
    session.add(Membership(org_id=org.id, user_id=user.id, role=Role.admin))
    with pytest.raises(IntegrityError):
        session.commit()


def test_vulnerability_cvss_score_is_nullable_not_zero(session):
    session.add(Vulnerability(cve_id="CVE-2024-0001", cvss_score=None, is_kev=False))
    session.commit()
    v = session.get(Vulnerability, "CVE-2024-0001")
    assert v.cvss_score is None  # unscored, never 0.0
