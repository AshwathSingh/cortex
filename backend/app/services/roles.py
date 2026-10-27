"""Custom roles and role assignment (US-21).

Authorisation rules live here, not in the route handlers, so every caller gets the
same guards:

* A member can only hand out what they hold. Creating or editing a role may not add
  a permission the actor lacks, and assigning a role requires holding all of its
  permissions -- otherwise ``members.manage`` or ``roles.manage`` alone would be a
  path to every other permission. OWNERs hold everything.
* Only an OWNER can grant OWNER, or change an OWNER's role.
* A workspace always keeps at least one OWNER.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.orm import Session

from app.models import Role, WorkspaceMembership, WorkspaceRole
from app.permissions import (
    GRANTABLE,
    SYSTEM_ROLE_PERMISSIONS,
    Permission,
    membership_permissions,
    parse_permissions,
    permission_values,
)


class RoleError(Exception):
    """A role operation was refused. ``status_code`` is the HTTP status to report."""

    status_code = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotPermitted(RoleError):
    status_code = 403


class NotFound(RoleError):
    status_code = 404


class Conflict(RoleError):
    status_code = 409


@dataclass(frozen=True)
class RoleChoice:
    """The role an assignment targets: exactly one of the two fields is set."""

    builtin: Role | None = None
    custom: WorkspaceRole | None = None

    @property
    def permissions(self) -> frozenset[Permission]:
        if self.custom is not None:
            return parse_permissions(self.custom.permissions) & GRANTABLE
        return SYSTEM_ROLE_PERMISSIONS[self.builtin]

    @property
    def is_owner(self) -> bool:
        return self.builtin is Role.OWNER


def ensure_can_grant(
    actor: WorkspaceMembership, wanted: frozenset[Permission]
) -> None:
    missing = wanted - membership_permissions(actor)
    if missing:
        names = ", ".join(sorted(p.value for p in missing))
        raise NotPermitted(f"You can only grant permissions you hold yourself: {names}")


def _clean_permissions(values: list[Permission]) -> list[str]:
    owner_only = [p for p in values if p not in GRANTABLE]
    if owner_only:
        names = ", ".join(sorted(p.value for p in owner_only))
        raise RoleError(f"These permissions can't be given to a custom role: {names}")
    return permission_values(frozenset(values))


def _name_taken(session: Session, workspace_id: uuid.UUID, name: str, *, excluding=None):
    stmt = select(WorkspaceRole.id).where(
        WorkspaceRole.workspace_id == workspace_id,
        func.lower(WorkspaceRole.name) == name.lower(),
    )
    if excluding is not None:
        stmt = stmt.where(WorkspaceRole.id != excluding)
    return session.scalar(stmt.limit(1)) is not None


def _reject_builtin_name(name: str) -> None:
    if name.upper() in {r.value for r in Role}:
        raise Conflict(f"'{name}' is a built-in role name")


def get_custom_role(
    session: Session, workspace_id: uuid.UUID, role_id: uuid.UUID
) -> WorkspaceRole:
    role = session.scalar(
        select(WorkspaceRole).where(
            WorkspaceRole.id == role_id, WorkspaceRole.workspace_id == workspace_id
        )
    )
    if role is None:
        raise NotFound("Role not found in this workspace")
    return role


def create_role(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    actor: WorkspaceMembership,
    name: str,
    description: str | None,
    permissions: list[Permission],
) -> WorkspaceRole:
    stored = _clean_permissions(permissions)
    ensure_can_grant(actor, frozenset(permissions))
    _reject_builtin_name(name)
    if _name_taken(session, workspace_id, name):
        raise Conflict(f"This workspace already has a role named '{name}'")
    role = WorkspaceRole(
        workspace_id=workspace_id,
        name=name,
        description=description,
        permissions=stored,
    )
    session.add(role)
    try:
        session.flush()
    except IntegrityError:  # lost a race with a concurrent create of the same name
        session.rollback()
        raise Conflict(f"This workspace already has a role named '{name}'")
    return role


def update_role(
    session: Session,
    *,
    role: WorkspaceRole,
    actor: WorkspaceMembership,
    name: str | None,
    description: str | None,
    description_set: bool,
    permissions: list[Permission] | None,
) -> WorkspaceRole:
    if permissions is not None:
        stored = _clean_permissions(permissions)
        # Only *newly added* permissions need to be ones the actor holds; taking
        # permissions away never escalates anyone.
        added = frozenset(permissions) - parse_permissions(role.permissions)
        ensure_can_grant(actor, added)
        role.permissions = stored
    if name is not None and name != role.name:
        _reject_builtin_name(name)
        if _name_taken(session, role.workspace_id, name, excluding=role.id):
            raise Conflict(f"This workspace already has a role named '{name}'")
        role.name = name
    if description_set:
        role.description = description
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise Conflict("This workspace already has a role with that name")
    return role


def delete_role(session: Session, *, role: WorkspaceRole) -> None:
    assigned = session.scalar(
        select(func.count())
        .select_from(WorkspaceMembership)
        .where(WorkspaceMembership.custom_role_id == role.id)
    )
    if assigned:
        raise Conflict(
            f"{assigned} member(s) still have this role; reassign them before deleting it"
        )
    session.delete(role)
    session.flush()


def assign_role(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    actor: WorkspaceMembership,
    target_user_id: uuid.UUID,
    choice: RoleChoice,
) -> WorkspaceMembership:
    """Set a member's role. Caller must already hold ``members.manage``."""
    # Lock every OWNER row of the workspace so two concurrent demotions cannot each
    # see "another owner remains" and leave the workspace with none. A no-op on SQLite.
    owners = session.scalars(
        select(WorkspaceMembership)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.role == Role.OWNER,
        )
        .with_for_update()
        # The session already holds the caller's membership from the request's
        # authorisation check; without this, a role change committed while we waited
        # for the lock would be hidden behind the stale cached row.
        .execution_options(populate_existing=True)
    ).all()

    # Re-check the caller against the now-locked, current state: a concurrent
    # request may have demoted or removed them since the route authorised them.
    try:
        session.refresh(actor)
    except InvalidRequestError:  # membership deleted while we waited
        raise NotPermitted("You no longer have access to this workspace")
    if Permission.MEMBERS_MANAGE not in membership_permissions(actor):
        raise NotPermitted("You no longer have permission to change member roles")

    target = session.scalar(
        select(WorkspaceMembership)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == target_user_id,
        )
        .execution_options(populate_existing=True)
    )
    if target is None:
        raise NotFound("That user is not a member of this workspace")

    actor_is_owner = actor.role is Role.OWNER
    target_is_owner = target.role is Role.OWNER

    if (choice.is_owner or target_is_owner) and not actor_is_owner:
        raise NotPermitted("Only an owner can grant or change the owner role")
    if target_is_owner and not choice.is_owner and len(owners) <= 1:
        raise Conflict("A workspace must keep at least one owner")
    ensure_can_grant(actor, choice.permissions)

    target.role = choice.builtin
    target.custom_role_id = choice.custom.id if choice.custom else None
    session.flush()
    session.refresh(target)  # reload the read-only custom_role relationship
    return target
