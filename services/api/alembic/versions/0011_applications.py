"""Applications: long-running containers built from a repository.

The platform's second half. Functions answer one request and go away; an app
stays up, holds a hostname and is reachable by name from everything else on the
cluster. The four tables here are the whole feature: the token used to clone
private repositories, the app itself, one row per build, and the hostnames the
edge routes to it.

Revision ID: 0011
Revises: 0010
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # As with every migration here, a fresh database already has these because
    # 0001 builds the schema from the live models.
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if "git_credentials" not in existing:
        op.create_table(
            "git_credentials",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "cluster_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("clusters.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("name", sa.String(80), nullable=False),
            sa.Column("provider", sa.String(20), nullable=False, server_default="github"),
            sa.Column("username", sa.String(120), nullable=False, server_default="x-access-token"),
            sa.Column("token_ciphertext", sa.Text(), nullable=False),
            sa.Column("last_used_at", sa.DateTime(timezone=True)),
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
            sa.UniqueConstraint("cluster_id", "name", name="uq_git_credential_name"),
        )

    if "apps" not in existing:
        op.create_table(
            "apps",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "cluster_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("clusters.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("name", sa.String(63), nullable=False, index=True),
            sa.Column("source_kind", sa.String(10), nullable=False, server_default="git"),
            sa.Column("repo_url", sa.String(500), nullable=False, server_default=""),
            sa.Column("branch", sa.String(120), nullable=False, server_default="main"),
            sa.Column(
                "credential_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("git_credentials.id", ondelete="SET NULL"),
            ),
            sa.Column("image_ref", sa.String(400), nullable=False, server_default=""),
            sa.Column("definition", postgresql.JSONB(), nullable=False, server_default="{}"),
            sa.Column("env_ciphertext", sa.Text(), nullable=False, server_default=""),
            sa.Column("port", sa.Integer(), nullable=False, server_default="3000"),
            sa.Column("replicas", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("memory_mb", sa.Integer(), nullable=False, server_default="512"),
            sa.Column("cpus", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("health_path", sa.String(200), nullable=False, server_default=""),
            sa.Column("node_pool", sa.String(40), nullable=False, server_default="general"),
            sa.Column("links", postgresql.JSONB(), nullable=False, server_default="[]"),
            sa.Column("volumes", postgresql.JSONB(), nullable=False, server_default="[]"),
            sa.Column("status", sa.String(20), nullable=False, server_default="created"),
            sa.Column("last_error", sa.Text()),
            sa.Column("auto_deploy", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("webhook_secret", sa.String(64), nullable=False, server_default=""),
            sa.Column("current_deployment_id", postgresql.UUID(as_uuid=True)),
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
            sa.UniqueConstraint("cluster_id", "name", name="uq_app_name_per_cluster"),
        )

    if "app_deployments" not in existing:
        op.create_table(
            "app_deployments",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "app_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("apps.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("trigger", sa.String(20), nullable=False, server_default="manual"),
            sa.Column("triggered_by", sa.String(200), nullable=False, server_default=""),
            sa.Column("commit_sha", sa.String(80), nullable=False, server_default=""),
            sa.Column("commit_message", sa.String(500), nullable=False, server_default=""),
            sa.Column("image_tag", sa.String(300), nullable=False, server_default=""),
            sa.Column("build_log", sa.Text(), nullable=False, server_default=""),
            sa.Column("build_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error", sa.Text()),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("finished_at", sa.DateTime(timezone=True)),
            sa.UniqueConstraint("app_id", "number", name="uq_app_deployment_number"),
        )
        # Added after both tables exist, because they point at each other.
        op.create_foreign_key(
            "fk_apps_current_deployment",
            "apps",
            "app_deployments",
            ["current_deployment_id"],
            ["id"],
            ondelete="SET NULL",
        )

    if "app_domains" not in existing:
        op.create_table(
            "app_domains",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "app_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("apps.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("hostname", sa.String(253), nullable=False),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="false"),
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
            sa.UniqueConstraint("hostname", name="uq_app_domain_hostname"),
        )


def downgrade() -> None:
    op.drop_table("app_domains")
    op.drop_constraint("fk_apps_current_deployment", "apps", type_="foreignkey")
    op.drop_table("app_deployments")
    op.drop_table("apps")
    op.drop_table("git_credentials")
