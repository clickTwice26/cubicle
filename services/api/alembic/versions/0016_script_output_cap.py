"""How much a host script may return, per script.

There was one number, 256 KiB, shared by every script and mentioned nowhere.
A script proxying somebody else's API hit it, had its JSON cut mid-value, and
was handed back as 200 with exit code 0 — the platform reporting success for a
body it had truncated itself. That is the worst shape a limit can have: silent,
invisible and indistinguishable from the upstream being wrong.

So the limit moves onto the script, where an operator can see it and raise it,
and going past it becomes a failed run rather than a short one. Existing scripts
get 1 MB, four times what they had.

Revision ID: 0016
Revises: 0015
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("host_scripts")}
    if "max_output_kb" not in columns:
        op.add_column(
            "host_scripts",
            sa.Column("max_output_kb", sa.Integer(), nullable=False, server_default="1024"),
        )


def downgrade() -> None:
    op.drop_column("host_scripts", "max_output_kb")
