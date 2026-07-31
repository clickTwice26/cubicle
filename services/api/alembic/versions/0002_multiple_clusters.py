"""Turn the single implicit cluster into first-class, multiple clusters.

Everything that used to be instance-wide — the name, the ingress domain, the
nodes, the namespaces, the env store, the data services — now belongs to a
cluster. An existing install is migrated into one default cluster carrying its
current configuration, so no URL changes and nothing is lost.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

SCOPED = ("nodes", "groups", "env_vars", "managed_services", "invocations", "log_entries")

# The unique indexes 0001 created for values that are now unique per cluster.
OLD_UNIQUE_INDEXES = {
    "nodes": "ix_nodes_name",
    "groups": "ix_groups_ns",
    "env_vars": "ix_env_vars_key",
    "managed_services": "ix_managed_services_kind",
}

NEW_UNIQUE = (
    ("uq_node_name_per_cluster", "nodes", ["cluster_id", "name"]),
    ("uq_namespace_per_cluster", "groups", ["cluster_id", "ns"]),
    ("uq_env_key_per_cluster", "env_vars", ["cluster_id", "key"]),
    ("uq_service_per_cluster", "managed_services", ["cluster_id", "kind"]),
)


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "clusters",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("slug", sa.String(63), nullable=False),
        sa.Column("ingress_domain", sa.String(255), nullable=False, server_default=""),
        sa.Column("data_dir", sa.String(255), nullable=False, server_default="/var/lib/cubicle"),
        sa.Column("kms_backend", sa.String(20), nullable=False, server_default="file"),
        sa.Column("default_node_pool", sa.String(40), nullable=False, server_default="general"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("description", sa.String(255), nullable=False, server_default=""),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_clusters_slug", "clusters", ["slug"], unique=True)
    op.create_index("ix_clusters_is_default", "clusters", ["is_default"])

    # Carry the existing instance configuration into the default cluster.
    existing = bind.execute(
        sa.text(
            "SELECT cluster_name, ingress_domain, data_dir, kms_backend, default_node_pool "
            "FROM instance WHERE id = 1"
        )
    ).first()

    name, domain, data_dir, kms, node_pool = existing or (
        "prod-cluster",
        "",
        "/var/lib/cubicle",
        "file",
        "general",
    )
    # "localhost" was the placeholder for "no domain configured".
    if domain in ("localhost", None):
        domain = ""

    default_id = bind.execute(
        sa.text(
            "INSERT INTO clusters (id, name, slug, ingress_domain, data_dir, kms_backend, "
            "default_node_pool, is_default, status, description) "
            "VALUES (gen_random_uuid(), :name, :slug, :domain, :data_dir, :kms, :pool, "
            "true, 'active', :description) RETURNING id"
        ),
        {
            "name": name,
            "slug": name,
            "domain": domain or "",
            "data_dir": data_dir or "/var/lib/cubicle",
            "kms": kms or "file",
            "pool": node_pool or "general",
            "description": "Migrated from the single-cluster layout.",
        },
    ).scalar_one()

    for table in SCOPED:
        op.add_column(table, sa.Column("cluster_id", sa.Uuid(), nullable=True))
        bind.execute(
            sa.text(f"UPDATE {table} SET cluster_id = :cid"),  # noqa: S608 - table is a literal
            {"cid": default_id},
        )
        op.alter_column(table, "cluster_id", nullable=False)
        op.create_index(f"ix_{table}_cluster_id", table, ["cluster_id"])
        op.create_foreign_key(
            f"fk_{table}_cluster", table, "clusters", ["cluster_id"], ["id"], ondelete="CASCADE"
        )

    # API keys may be scoped to one cluster, or left null for every cluster.
    op.add_column("api_keys", sa.Column("cluster_id", sa.Uuid(), nullable=True))
    op.create_index("ix_api_keys_cluster_id", "api_keys", ["cluster_id"])
    op.create_foreign_key(
        "fk_api_keys_cluster", "api_keys", "clusters", ["cluster_id"], ["id"], ondelete="CASCADE"
    )

    # Values that were globally unique are now unique within a cluster.
    for table, index in OLD_UNIQUE_INDEXES.items():
        op.execute(f"DROP INDEX IF EXISTS {index}")
        column = {"nodes": "name", "groups": "ns", "env_vars": "key", "managed_services": "kind"}[
            table
        ]
        op.create_index(index, table, [column])
    for name_, table, columns in NEW_UNIQUE:
        op.create_unique_constraint(name_, table, columns)

    op.create_index("ix_invocations_cluster_ts", "invocations", ["cluster_id", "ts"])
    op.create_index("ix_logs_cluster_ts", "log_entries", ["cluster_id", "ts"])

    # Instance keeps only what genuinely spans clusters.
    for column in (
        "cluster_name",
        "ingress_domain",
        "data_dir",
        "kms_backend",
        "default_node_pool",
    ):
        op.drop_column("instance", column)


def downgrade() -> None:
    op.add_column(
        "instance", sa.Column("cluster_name", sa.String(80), server_default="prod-cluster")
    )
    op.add_column(
        "instance", sa.Column("ingress_domain", sa.String(255), server_default="localhost")
    )
    op.add_column(
        "instance", sa.Column("data_dir", sa.String(255), server_default="/var/lib/cubicle")
    )
    op.add_column("instance", sa.Column("kms_backend", sa.String(20), server_default="file"))
    op.add_column(
        "instance", sa.Column("default_node_pool", sa.String(40), server_default="general")
    )

    for name_, table, _columns in NEW_UNIQUE:
        op.drop_constraint(name_, table, type_="unique")
    for table, index in OLD_UNIQUE_INDEXES.items():
        column = {"nodes": "name", "groups": "ns", "env_vars": "key", "managed_services": "kind"}[
            table
        ]
        op.execute(f"DROP INDEX IF EXISTS {index}")
        op.create_index(index, table, [column], unique=True)

    op.drop_index("ix_logs_cluster_ts", table_name="log_entries")
    op.drop_index("ix_invocations_cluster_ts", table_name="invocations")

    op.drop_constraint("fk_api_keys_cluster", "api_keys", type_="foreignkey")
    op.drop_index("ix_api_keys_cluster_id", table_name="api_keys")
    op.drop_column("api_keys", "cluster_id")

    for table in SCOPED:
        op.drop_constraint(f"fk_{table}_cluster", table, type_="foreignkey")
        op.drop_index(f"ix_{table}_cluster_id", table_name=table)
        op.drop_column(table, "cluster_id")

    op.drop_index("ix_clusters_is_default", table_name="clusters")
    op.drop_index("ix_clusters_slug", table_name="clusters")
    op.drop_table("clusters")
