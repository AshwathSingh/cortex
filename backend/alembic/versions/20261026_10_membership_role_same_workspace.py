"""Require a membership's custom role to belong to the same workspace (review fix for T-21.1).

Revision ID: 20261026_10
Revises: 20261018_09
Create Date: 2026-10-26

Migration 09 referenced ``workspace_roles.id`` alone, so the database would accept a
membership in workspace A pointing at a role defined in workspace B. The API never
creates one, but nothing below it prevented it. This swaps the single-column key for
a composite one on (custom_role_id, workspace_id).

Fails, by design, if a database already holds such a cross-workspace membership; fix
or delete the offending rows and re-run. The old key was ON DELETE RESTRICT; the new
one has no action (NO ACTION), which still refuses to delete a role in use but does
not fire in the middle of a workspace's cascading delete.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261026_10"
down_revision: str | None = "20261018_09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "fk_membership_custom_role", "workspace_memberships", type_="foreignkey"
    )
    op.create_unique_constraint(
        "uq_workspace_roles_id_workspace", "workspace_roles", ["id", "workspace_id"]
    )
    op.create_foreign_key(
        "fk_membership_custom_role",
        "workspace_memberships",
        "workspace_roles",
        ["custom_role_id", "workspace_id"],
        ["id", "workspace_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_membership_custom_role", "workspace_memberships", type_="foreignkey"
    )
    op.drop_constraint(
        "uq_workspace_roles_id_workspace", "workspace_roles", type_="unique"
    )
    op.create_foreign_key(
        "fk_membership_custom_role",
        "workspace_memberships",
        "workspace_roles",
        ["custom_role_id"],
        ["id"],
        ondelete="RESTRICT",
    )
