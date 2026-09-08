"""A permanent instant link for every application.

An app has three addresses, and they arrive at different times. A custom domain
needs a DNS record and a certificate. A subdomain needs a wildcard. Both are
things the operator does elsewhere, and neither exists at the moment a first
deploy goes live — which is exactly when someone wants to look at it.

The instant link needs nothing: a random, permanent path on the instance's own
hostname, routed the moment the app is running. Existing apps are given one
here rather than at their next deploy, so the link is never missing.

Revision ID: 0012
Revises: 0011
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("apps")}
    if "path_token" in columns:
        return

    op.add_column(
        "apps", sa.Column("path_token", sa.String(length=32), nullable=False, server_default="")
    )
    op.create_index("ix_apps_path_token", "apps", ["path_token"])
    # Backfill from the row's own id so the value is stable and unguessable
    # without the application having to be running to hand one out.
    op.execute(
        "UPDATE apps SET path_token = substr(md5(random()::text || id::text), 1, 16) "
        "WHERE path_token = ''"
    )
    op.alter_column("apps", "path_token", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_apps_path_token", table_name="apps")
    op.drop_column("apps", "path_token")
