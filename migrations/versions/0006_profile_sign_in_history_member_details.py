"""profile, sign-in history, member details

* ``users.avatar_key`` — the profile photo's object-storage key.
* ``login_events`` — recent successful sign-ins, shown on the profile page.
* ``memberships.employee_id`` / ``team`` — optional details an org's admins
  record about a member; an employee ID is unique within an org.
* ``org_integrations.nvd_key_verified_at`` — when NVD last accepted the key.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-12 10:10:24.593926
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: str | None = '0005'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('login_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('method', sa.String(length=32), nullable=False),
    sa.Column('ip', sa.String(length=45), nullable=True),
    sa.Column('user_agent', sa.String(length=300), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_login_events_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_login_events'))
    )
    with op.batch_alter_table('login_events', schema=None) as batch_op:
        batch_op.create_index('ix_login_events_user_id_created_at', ['user_id', 'created_at'], unique=False)

    with op.batch_alter_table('memberships', schema=None) as batch_op:
        batch_op.add_column(sa.Column('employee_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('team', sa.String(length=100), nullable=True))
        batch_op.create_unique_constraint('uq_memberships_org_id_employee_id', ['org_id', 'employee_id'])

    with op.batch_alter_table('org_integrations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('nvd_key_verified_at', sa.DateTime(timezone=True), nullable=True))

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('avatar_key', sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('avatar_key')

    with op.batch_alter_table('org_integrations', schema=None) as batch_op:
        batch_op.drop_column('nvd_key_verified_at')

    with op.batch_alter_table('memberships', schema=None) as batch_op:
        batch_op.drop_constraint('uq_memberships_org_id_employee_id', type_='unique')
        batch_op.drop_column('team')
        batch_op.drop_column('employee_id')

    with op.batch_alter_table('login_events', schema=None) as batch_op:
        batch_op.drop_index('ix_login_events_user_id_created_at')

    op.drop_table('login_events')
