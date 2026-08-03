"""Run a function on a schedule.

Until now a function only ran when something called it. A trigger is the other
way in: a cron expression, a timezone, and the instant it is next owed a run.

`next_run_at` is both the queue and the lock. The scheduler claims a due
trigger by updating that column with the value it read in the WHERE clause, so
two control planes cannot both take the same run, and nothing is held while the
function executes. The index is on (enabled, next_run_at) because that is the
only question the loop ever asks.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A fresh database already has the table: 0001 builds the schema from the
    # live models rather than by replaying these.
    bind = op.get_bind()
    if sa.inspect(bind).has_table("triggers"):
        return

    op.create_table(
        "triggers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "function_id",
            sa.Uuid(),
            sa.ForeignKey("functions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "cluster_id",
            sa.Uuid(),
            sa.ForeignKey("clusters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="schedule"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("cron", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("timezone", sa.String(length=64), nullable=False, server_default="UTC"),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_status", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("last_error", sa.Text()),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_triggers_function_id", "triggers", ["function_id"])
    op.create_index("ix_triggers_cluster_id", "triggers", ["cluster_id"])
    op.create_index("ix_triggers_next_run_at", "triggers", ["next_run_at"])
    op.create_index("ix_triggers_due", "triggers", ["enabled", "next_run_at"])


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("triggers"):
        op.drop_table("triggers")
