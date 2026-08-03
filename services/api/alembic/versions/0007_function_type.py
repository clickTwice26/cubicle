"""Label a function by whether anything is sent to it.

Two kinds turn up in every namespace and nothing distinguished them: functions
invoked with a body, and functions that just run — a nightly rebuild, a health
probe, a cache warm. Reading a list you could not tell which was which without
opening each one.

This is a label and only a label. Nothing in the runtime reads it, and an
`independent` function sent a body still receives it. Refusing the body would
make this a contract, and a classifier that silently starts rejecting requests
is a worse thing than no classifier.

Existing functions become `dependent`, the permissive one: it says a body may
arrive, which is true of everything already deployed.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # As with 0002 and 0003: a fresh database already has the column, because
    # 0001 builds the schema from the live models rather than from migrations.
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("functions"):
        return
    columns = {c["name"] for c in sa.inspect(bind).get_columns("functions")}
    if "function_type" in columns:
        return

    op.add_column(
        "functions",
        sa.Column(
            "function_type",
            sa.String(length=12),
            nullable=False,
            server_default="dependent",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("functions"):
        return
    columns = {c["name"] for c in sa.inspect(bind).get_columns("functions")}
    if "function_type" in columns:
        op.drop_column("functions", "function_type")
