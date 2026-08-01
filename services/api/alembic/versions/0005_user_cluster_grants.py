"""Per-user cluster access.

Until now every signed-in account could address every cluster: the header named
one and the control plane handed it over. Access is now explicit, and this
table is the record of it.

Existing accounts are granted every cluster that exists at upgrade time, so an
upgrade changes nothing for anyone already using the instance. New accounts
start with nothing and are granted clusters deliberately.

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("user_clusters"):
        # 0001 builds the schema from the live models on a fresh database.
        return

    op.create_table(
        "user_clusters",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "cluster_id",
            sa.Uuid(),
            sa.ForeignKey("clusters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "cluster_id", name="uq_user_cluster"),
    )
    op.create_index("ix_user_clusters_user_id", "user_clusters", ["user_id"])
    op.create_index("ix_user_clusters_cluster_id", "user_clusters", ["cluster_id"])

    # Everyone who already had access keeps it. Silently locking existing
    # accounts out of their own clusters would be a worse failure than the
    # permissiveness this migration is fixing.
    op.execute(
        sa.text(
            "INSERT INTO user_clusters (id, user_id, cluster_id) "
            "SELECT gen_random_uuid(), u.id, c.id FROM users u CROSS JOIN clusters c"
        )
    )


def downgrade() -> None:
    op.drop_table("user_clusters")
