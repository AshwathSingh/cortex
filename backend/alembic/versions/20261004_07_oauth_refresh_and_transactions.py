"""GitHub token refresh/expiry columns and single-use OAuth transactions (US-1).

Revision ID: 20261004_07
Revises: 20260929_06
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261004_07"
down_revision: str | None = "20260929_06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "github_credentials",
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Fernet ciphertext (app.db.types.EncryptedString), never the raw token.
    op.add_column("github_credentials", sa.Column("refresh_token", sa.Text(), nullable=True))
    op.add_column(
        "github_credentials",
        sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "oauth_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("code_verifier", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_hash"),
    )
    op.create_index(
        "ix_oauth_transactions_expires_at", "oauth_transactions", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_oauth_transactions_expires_at", table_name="oauth_transactions")
    op.drop_table("oauth_transactions")
    op.drop_column("github_credentials", "refresh_token_expires_at")
    op.drop_column("github_credentials", "refresh_token")
    op.drop_column("github_credentials", "access_token_expires_at")
