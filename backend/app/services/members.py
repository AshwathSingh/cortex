"""Removing members from a workspace (US-04).

Rules:

* Removing someone else needs ``members.manage``; only an OWNER can remove an OWNER.
* Any member may remove themselves ("leave workspace") without that permission.
* A workspace always keeps at least one OWNER -- this holds for leaving too.
* Removal deletes the membership row only. Invites the person sent are left alone.

Nothing caches permissions (every request re-reads the membership), so removal
takes effect on the removed user's very next request.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session

from app.models import Role, WorkspaceMembership
from app.permissions import Permission, membership_permissions
from app.services.roles import Conflict, NotFound, NotPermitted


def remove_member(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    actor: WorkspaceMembership,
    target_user_id: uuid.UUID,
) -> None:
    # Lock every OWNER row so two concurrent removals can't each see "another owner
    # remains" and leave none. A no-op on SQLite.
    owners = session.scalars(
        select(WorkspaceMembership)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.role == Role.OWNER,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).all()

    # Re-check the caller against the locked, current state.
    try:
        session.refresh(actor)
    except InvalidRequestError:  # removed while we waited for the lock
        raise NotPermitted("You no longer have access to this workspace")

    leaving = target_user_id == actor.user_id
    if not leaving and Permission.MEMBERS_MANAGE not in membership_permissions(actor):
        raise NotPermitted("You no longer have permission to remove members")

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

    if target.role is Role.OWNER:
        if not leaving and actor.role is not Role.OWNER:
            raise NotPermitted("Only an owner can remove an owner")
        if len(owners) <= 1:
            raise Conflict("A workspace must keep at least one owner")

    session.delete(target)
    session.flush()
