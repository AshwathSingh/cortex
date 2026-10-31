"""Deleting a custom role deletes the invites that name it.

Revision ID: 20261029_12
Revises: 20261027_11
Create Date: 2026-10-29

Without this, deleting a role had to remove its invites in a separate step, which
left a window for a concurrent invite to be created in between. The database now
does it atomically. Memberships keep their protective NO ACTION key: a role in use
by members still can't be deleted.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261029_12"
down_revision: str | None = "20261027_11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _recreate(ondelete: str | None) -> None:
    op.drop_constraint("fk_invite_custom_role", "workspace_invites", type_="foreignkey")
    op.create_foreign_key(
        "fk_invite_custom_role",
        "workspace_invites",
        "workspace_roles",
        ["custom_role_id", "workspace_id"],
        ["id", "workspace_id"],
        ondelete=ondelete,
    )


def upgrade() -> None:
    _recreate("CASCADE")


def downgrade() -> None:
    _recreate(None)
