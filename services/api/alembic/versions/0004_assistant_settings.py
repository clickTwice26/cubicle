"""Cubicle AI configuration, held on the instance row.

The assistant needs a provider key, and a key belongs where every other secret
in Cubicle already lives: envelope-encrypted in the database, set from the
console rather than baked into the environment. Base URL and model sit next to
it so an operator can point the assistant at a different provider — or at a
model running on their own hardware — without touching a file or restarting the
control plane.

Empty strings mean "fall back to whatever the environment says", which keeps
existing .env-configured installs working untouched.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

COLUMNS = {
    "ai_key_ciphertext": sa.Column("ai_key_ciphertext", sa.Text(), nullable=True),
    "ai_base_url": sa.Column(
        "ai_base_url", sa.String(length=200), nullable=False, server_default=""
    ),
    "ai_model": sa.Column("ai_model", sa.String(length=80), nullable=False, server_default=""),
}


def upgrade() -> None:
    # Same reasoning as 0002 and 0003: a fresh database already has these,
    # because 0001 builds the schema from the live models.
    existing = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("instance")}
    for name, column in COLUMNS.items():
        if name not in existing:
            op.add_column("instance", column)

    # The server defaults exist only to fill the singleton row; the application
    # supplies the values from here on.
    for name in ("ai_base_url", "ai_model"):
        if name not in existing:
            op.alter_column("instance", name, server_default=None)


def downgrade() -> None:
    for name in COLUMNS:
        op.drop_column("instance", name)
