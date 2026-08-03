"""A kill time per function: how long an instance may sit idle.

Idle instances were reclaimed on one instance-wide TTL, which has to suit both
a function invoked every few seconds and one invoked twice a day. The first
wants a long TTL so it never pays a cold start; the second wants a short one so
it is not holding memory all afternoon for nothing.

Zero means "use the instance-wide TTL", so every function that existed before
this keeps exactly the behaviour it had. The setting restrains the platform
rather than overruling it: it decides when an idle instance goes, not whether
the surplus rule may take one sooner.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A fresh database already has the column: 0001 builds the schema from the
    # live models rather than by replaying these.
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("functions"):
        return
    columns = {c["name"] for c in sa.inspect(bind).get_columns("functions")}
    if "idle_timeout_s" in columns:
        return

    op.add_column(
        "functions",
        sa.Column("idle_timeout_s", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("functions"):
        return
    columns = {c["name"] for c in sa.inspect(bind).get_columns("functions")}
    if "idle_timeout_s" in columns:
        op.drop_column("functions", "idle_timeout_s")
