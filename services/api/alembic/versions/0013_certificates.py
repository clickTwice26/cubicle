"""Certificates Cubicle obtains for instances behind another web server.

An install where Caddy owns 80 and 443 needs none of this — it issues its own,
on first request. An install behind nginx cannot: the certificate belongs to
the server that terminates TLS, and obtaining a wildcard needs DNS access
rather than a file served over HTTP.

So the control plane can hold a DNS token, ask for the certificate, and renew
it before it expires. The token is envelope-encrypted next to every other
secret; the certificate itself lands on disk where the front-end server reads
it.

Revision ID: 0013
Revises: 0012
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    columns = {c["name"] for c in inspector.get_columns("instance")}
    for name, column in {
        "acme_provider": sa.Column(
            "acme_provider", sa.String(length=20), nullable=False, server_default="cloudflare"
        ),
        "acme_token_ciphertext": sa.Column("acme_token_ciphertext", sa.Text(), nullable=True),
        "acme_email": sa.Column(
            "acme_email", sa.String(length=255), nullable=False, server_default=""
        ),
    }.items():
        if name not in columns:
            op.add_column("instance", column)

    if "certificates" not in set(inspector.get_table_names()):
        op.create_table(
            "certificates",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("name", sa.String(253), nullable=False, index=True),
            sa.Column("hostnames", postgresql.JSONB(), nullable=False, server_default="[]"),
            sa.Column("provider", sa.String(20), nullable=False, server_default="cloudflare"),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("expires_at", sa.DateTime(timezone=True)),
            sa.Column("issued_at", sa.DateTime(timezone=True)),
            sa.Column("last_error", sa.Text()),
            sa.Column("last_log", sa.Text(), nullable=False, server_default=""),
            sa.Column("renewals", sa.Integer(), nullable=False, server_default="0"),
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
            sa.UniqueConstraint("name", name="uq_certificate_name"),
        )


def downgrade() -> None:
    op.drop_table("certificates")
    for name in ("acme_email", "acme_token_ciphertext", "acme_provider"):
        op.drop_column("instance", name)
