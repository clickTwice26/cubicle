"""Per-cluster resource ceilings.

A cluster could allocate as much of the machine as its functions asked for.
These three columns are the super admin's answer to that: memory, CPU and
storage caps that bound every per-function setting underneath them.

Zero means unlimited, which is what every existing cluster gets — an upgrade
must not start refusing work that was running fine a minute earlier.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

COLUMNS = (
    ("max_memory_mb", sa.Integer(), "0"),
    ("max_cpu_cores", sa.Float(), "0"),
    ("max_storage_gb", sa.Integer(), "0"),
)


def upgrade() -> None:
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("clusters")}
    for name, kind, default in COLUMNS:
        # 0001 builds the schema from the live models, so a fresh database
        # already has these.
        if name in existing:
            continue
        op.add_column("clusters", sa.Column(name, kind, nullable=False, server_default=default))
        op.alter_column("clusters", name, server_default=None)


def downgrade() -> None:
    for name, _, _ in COLUMNS:
        op.drop_column("clusters", name)
