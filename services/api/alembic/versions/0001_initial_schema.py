"""Initial control-plane schema.

The first revision materialises the declarative metadata, so the tables can
never drift from ``cubicle.models`` on a fresh install. Every later revision is
an explicit, hand-written migration.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

from alembic import op
from cubicle.models import Base

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
