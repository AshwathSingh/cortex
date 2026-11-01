"""Workspace permissions: the fixed catalogue and what each built-in role holds.

Roles come in two kinds. The built-in OWNER, EDITOR and VIEWER (``Role``) have
permissions fixed here in code. Custom roles are defined per workspace by users
with ``roles.manage``; each holds a subset of ``GRANTABLE`` permissions chosen by
the user. Reading a workspace needs membership only, so there is no "read"
permission to withhold.

Every authorisation check resolves to a ``Permission``; nothing else in the
codebase should compare role names.
"""

import enum

from app.models.workspace import Role, WorkspaceMembership


class Permission(str, enum.Enum):
    SOURCES_WRITE = "sources.write"
    MEMBERS_MANAGE = "members.manage"
    ROLES_MANAGE = "roles.manage"
    WORKSPACE_DELETE = "workspace.delete"


PERMISSION_DESCRIPTIONS: dict[Permission, str] = {
    Permission.SOURCES_WRITE: "Connect data sources and run ingestion",
    Permission.MEMBERS_MANAGE: "Invite and remove members and change their roles",
    Permission.ROLES_MANAGE: "Create, edit and delete custom roles",
    Permission.WORKSPACE_DELETE: "Delete the workspace (owners only)",
}

# Owner-only: a custom role can never carry these, so the workspace can always be
# deleted by (and only by) someone holding the built-in OWNER role.
OWNER_ONLY: frozenset[Permission] = frozenset({Permission.WORKSPACE_DELETE})

GRANTABLE: frozenset[Permission] = frozenset(Permission) - OWNER_ONLY

SYSTEM_ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: frozenset(Permission),
    Role.EDITOR: frozenset({Permission.SOURCES_WRITE}),
    Role.VIEWER: frozenset(),
}


def permission_values(permissions: frozenset[Permission]) -> list[str]:
    """Stable, catalogue-ordered strings for storage and API responses."""
    return [p.value for p in Permission if p in permissions]


def parse_permissions(values: list[str]) -> frozenset[Permission]:
    """Permissions stored on a custom role. Unknown strings are dropped, so a
    permission removed from the catalogue silently stops granting anything."""
    known = {p.value: p for p in Permission}
    return frozenset(known[v] for v in values if v in known)


def membership_permissions(membership: WorkspaceMembership) -> frozenset[Permission]:
    """What a membership entitles its holder to, resolved from the database row
    on every call -- nothing is cached, so a role change or removal applies on the
    holder's very next request."""
    if membership.custom_role is not None:
        return parse_permissions(membership.custom_role.permissions) & GRANTABLE
    return SYSTEM_ROLE_PERMISSIONS[membership.role]


def role_label(membership: WorkspaceMembership) -> str:
    """The role's display name: OWNER/EDITOR/VIEWER, or the custom role's name."""
    if membership.custom_role is not None:
        return membership.custom_role.name
    return membership.role.value
