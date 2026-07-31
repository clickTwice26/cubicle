"""Per-function ceiling on concurrent isolates.

Before this the limit was a single instance-wide setting, so one busy function
could take every isolate slot on a node and starve the rest. The cap now lives
on the function, next to the memory and timeout it is scheduled against.

Existing functions get 4, which is the default for a new one: high enough that
ordinary bursts still fan out, low enough that a runaway loop cannot exhaust
the node before the operator notices.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "functions",
        sa.Column("max_instances", sa.Integer(), nullable=False, server_default="4"),
    )
    # The server default exists only to fill existing rows; the application
    # supplies the value from here on.
    op.alter_column("functions", "max_instances", server_default=None)


def downgrade() -> None:
    op.drop_column("functions", "max_instances")
