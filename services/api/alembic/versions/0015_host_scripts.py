"""Scripts that run on a node's host, triggered by a URL.

The opposite of a function in every mechanical way: no build, no image, no
container — a host process, started because a request arrived. So there are no
version rows here, because there is nothing to build and so nothing to roll
back to; the source column is the whole artifact.

Off until an owner turns it on, on its own switch rather than the terminal's.
The terminal is an owner at a keyboard; this is a URL that starts a root
process, which is the same authority reachable by anything that can reach the
URL. Neither implies the other.

Revision ID: 0015
Revises: 0014
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    columns = {c["name"] for c in inspector.get_columns("instance")}
    if "host_scripts_enabled" not in columns:
        op.add_column(
            "instance",
            sa.Column(
                "host_scripts_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )

    tables = set(inspector.get_table_names())

    if "host_scripts" not in tables:
        op.create_table(
            "host_scripts",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "cluster_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("clusters.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("name", sa.String(63), nullable=False, index=True),
            sa.Column("description", sa.String(200), nullable=False, server_default=""),
            sa.Column("interpreter", sa.String(120), nullable=False, server_default="python3"),
            sa.Column("source", sa.Text(), nullable=False, server_default=""),
            sa.Column("working_dir", sa.String(255), nullable=False, server_default=""),
            sa.Column("timeout_s", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("method", sa.String(10), nullable=False, server_default="POST"),
            sa.Column("output_mode", sa.String(10), nullable=False, server_default="auto"),
            sa.Column(
                "node_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("nodes.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column("env_ciphertext", sa.Text()),
            sa.Column("auth_required", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_run_at", sa.DateTime(timezone=True)),
            sa.Column("last_exit_code", sa.Integer()),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint("cluster_id", "name", name="uq_host_script_name"),
        )

    if "host_script_runs" not in tables:
        op.create_table(
            "host_script_runs",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "script_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("host_scripts.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "cluster_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("clusters.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "ts",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
                index=True,
            ),
            sa.Column("trigger", sa.String(12), nullable=False, server_default="url"),
            sa.Column("exit_code", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duration_ms", sa.Float(), nullable=False, server_default="0"),
            sa.Column("stdout", sa.Text(), nullable=False, server_default=""),
            sa.Column("stderr", sa.Text(), nullable=False, server_default=""),
            sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("status_code", sa.Integer(), nullable=False, server_default="200"),
            sa.Column("request_id", sa.String(40), nullable=False, server_default=""),
            sa.Column("node_name", sa.String(80), nullable=False, server_default=""),
        )
        op.create_index("ix_host_script_runs_script_ts", "host_script_runs", ["script_id", "ts"])


def downgrade() -> None:
    op.drop_table("host_script_runs")
    op.drop_table("host_scripts")
    op.drop_column("instance", "host_scripts_enabled")
