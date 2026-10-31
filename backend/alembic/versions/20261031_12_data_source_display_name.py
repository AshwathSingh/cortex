"""A display name for sources whose reference is not their name (T-9.1).

Revision ID: 20261031_12
Revises: 20261026_10
Create Date: 2026-10-31

Additive and nullable, so there is no backfill: a GitHub source's
``external_ref`` already *is* what the page shows, and leaving it NULL is the
honest way to say "nothing else to call this".

Numbered 12 rather than 11 because US-08 branched off the same head and took 11.
Both revise 20261026_10, so merging the two branches leaves Alembic with two
heads; the fix is to point whichever lands second at the other (change its
``down_revision``), not to add a merge revision.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261031_12"
down_revision: str | None = "20261026_10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "data_sources",
        sa.Column("display_name", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("data_sources", "display_name")
