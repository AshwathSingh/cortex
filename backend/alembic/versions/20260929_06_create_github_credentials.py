"""Store GitHub OAuth access tokens, encrypted at rest (T-1.3).

Revision ID: 20260929_06
Revises: 20260924_05
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260929_06"
down_revision: str | None = "20260924_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "github_credentials",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Fernet ciphertext (app.db.types.EncryptedString), never the raw token.
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("scope", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )


def downgrade() -> None:
    op.drop_table("github_credentials")
