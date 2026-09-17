"""A live shell on a node's host, opened from the console.

Off by default, unlike everything else the console turns on with a key or a
credential: this feature's entire purpose is letting an owner run arbitrary
commands as root on the machine it runs on. The owner-role gate already on
every endpoint is the real control; this column is the one-time choice of
whether the capability exists on this instance at all.

Revision ID: 0014
Revises: 0013
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("instance")}
    if "terminal_enabled" not in columns:
        op.add_column(
            "instance",
            sa.Column(
                "terminal_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )


def downgrade() -> None:
    op.drop_column("instance", "terminal_enabled")
