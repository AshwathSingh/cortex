"""Categorise ingestion failures so the UI can offer the right fix (T-12.1).

Revision ID: 20261105_14
Revises: 20261031_12
Create Date: 2026-11-05

``data_sources.last_error`` already holds the failure message. This adds the
*category* beside it, because the message cannot be branched on: "your token was
revoked" needs a sign-in button and "GitHub is down" needs a wait, and telling
them apart by parsing English is not something to build on.

Nullable with no backfill, deliberately. An existing FAILED row has no category
and the application reads a missing one as UNKNOWN, which produces a correct if
unhelpful "try again". Guessing a category from the recorded message would put
wrong advice in front of a user -- a sign-in prompt that fixes nothing is worse
than a generic retry.

Plain text, not an enum type: adding a category should be a code change, not a
migration plus an ``ALTER TYPE``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261105_14"
down_revision: str | None = "20261031_12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "data_sources",
        sa.Column("last_error_code", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("data_sources", "last_error_code")
