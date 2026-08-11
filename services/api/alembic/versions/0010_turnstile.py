"""Cloudflare Turnstile on the sign-in form.

The sign-in form is the one place an anonymous visitor can spend the control
plane's CPU: every attempt costs an argon2 verification at 64 MB. Turnstile
moves that cost back to the caller before the password is ever checked.

The settings live on the instance rather than on a cluster because signing in
happens before a cluster has been chosen. The site key is stored in the clear
since it is rendered into the login page and is public by construction. The
secret key is envelope-encrypted, like the AI key beside it.

Revision ID: 0010
Revises: 0009
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A fresh database already has these: 0001 builds the schema from the live
    # models rather than by replaying the migrations that came after it.
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("instance")}

    if "turnstile_enabled" not in existing:
        op.add_column(
            "instance",
            sa.Column("turnstile_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "turnstile_site_key" not in existing:
        op.add_column(
            "instance",
            sa.Column(
                "turnstile_site_key", sa.String(length=120), nullable=False, server_default=""
            ),
        )
    if "turnstile_secret_ciphertext" not in existing:
        op.add_column("instance", sa.Column("turnstile_secret_ciphertext", sa.Text()))


def downgrade() -> None:
    op.drop_column("instance", "turnstile_secret_ciphertext")
    op.drop_column("instance", "turnstile_site_key")
    op.drop_column("instance", "turnstile_enabled")
