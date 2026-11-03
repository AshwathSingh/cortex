"""Workspace creation and deletion.

Deleting spans Postgres and Neo4j, which cannot share a transaction, so it runs
in an order that is safe to stop and resume (US-05):

1. mark the workspace ``deleting`` and commit -- from here every endpoint treats
   it as gone, so nothing new can be written to it;
2. delete its graph from Neo4j (idempotent, batched);
3. delete the Postgres row; ON DELETE CASCADE removes members, invites, custom
   roles and data sources with it.

If step 2 or 3 fails the workspace stays ``deleting`` (invisible, not half-alive)
and calling delete again resumes from step 2.
"""

import logging
import uuid

from neo4j import Driver
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session

from app.graph.queries import delete_workspace_graph
from app.models import (
    WORKSPACE_ACTIVE,
    WORKSPACE_DELETING,
    Role,
    User,
    Workspace,
    WorkspaceMembership,
)

from app.permissions import Permission, membership_permissions
from app.services.roles import NotPermitted

logger = logging.getLogger(__name__)


class WorkspaceNameTaken(Exception):
    """The owner already owns a workspace with this name."""


def create_workspace(
    session: Session, *, name: str, owner: User, description: str | None = None
) -> Workspace:
    """Create a workspace and its canonical owner membership.

    Names are unique per owner, case-insensitively. Other users may reuse a
    name, and workspaces merely shared with the owner do not count.
    """
    # Lock the owner row so two concurrent creates by the same user cannot both
    # pass the duplicate check. A no-op on SQLite, which serialises writes anyway.
    session.execute(select(User.id).where(User.id == owner.id).with_for_update())

    taken = session.scalar(
        select(Workspace.id)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .where(
            WorkspaceMembership.user_id == owner.id,
            WorkspaceMembership.role == Role.OWNER,
            func.lower(Workspace.name) == name.lower(),
        )
        .limit(1)
    )
    if taken is not None:
        raise WorkspaceNameTaken(name)

    workspace = Workspace(name=name, description=description)
    session.add(workspace)
    session.flush()
    session.add(
        WorkspaceMembership(
            user_id=owner.id,
            workspace_id=workspace.id,
            role=Role.OWNER,
        )
    )
    return workspace


def lock_active_workspace(session: Session, workspace_id: uuid.UUID) -> bool:
    """True if the workspace exists and is not being deleted; holds a shared lock
    on its row until the transaction ends.

    Anything that is about to add data to a workspace (a graph write, a new
    member) calls this and keeps its transaction open across the write. Deletion
    takes the exclusive lock to mark the workspace, so it waits for in-flight
    writers to finish and later writers see ``deleting`` -- a background sync can't
    recreate nodes after the graph has been cleared. A no-op lock on SQLite.
    """
    status = session.scalar(
        select(Workspace.status).where(Workspace.id == workspace_id).with_for_update(read=True)
    )
    return status == WORKSPACE_ACTIVE


def mark_deleting(
    session: Session, workspace_id: uuid.UUID, actor: WorkspaceMembership | None = None
) -> bool:
    """Step 1: flip the workspace to ``deleting`` and commit. False if it is gone.

    Idempotent: marking an already-``deleting`` workspace is a no-op, which is
    what lets a retry resume.

    With ``actor`` (the caller's membership, as authorised by the route), the
    caller is re-checked against the locked, current database state: deleting is
    irreversible, so an owner who was demoted or removed a moment after the route
    authorised them must not get to finish it. Raises ``NotPermitted``.
    """
    exists = session.scalar(
        select(Workspace.id).where(Workspace.id == workspace_id).with_for_update()
    )
    if exists is None:
        session.rollback()
        return False
    if actor is not None:
        try:  # lock the caller's own row: demotion/removal write it, so they serialise
            session.refresh(actor, with_for_update=True)
        except InvalidRequestError:
            session.rollback()
            raise NotPermitted("You no longer have access to this workspace")
        if Permission.WORKSPACE_DELETE not in membership_permissions(actor):
            session.rollback()
            raise NotPermitted("You no longer have permission to delete this workspace")
    session.execute(
        update(Workspace)
        .where(Workspace.id == workspace_id)
        .values(status=WORKSPACE_DELETING)
    )
    session.commit()
    return True


def delete_workspace(
    session: Session,
    driver: Driver,
    workspace_id: uuid.UUID,
    actor: WorkspaceMembership | None = None,
) -> None:
    """Run the full cascade. Raises whatever the failing store raises, leaving
    the workspace in ``deleting`` so a retry resumes (see module docstring)."""
    if not mark_deleting(session, workspace_id, actor):
        return  # already fully deleted by an earlier or concurrent call

    try:
        removed = delete_workspace_graph(driver, workspace_id)
    except Exception:
        logger.exception("Neo4j cleanup failed for workspace %s; left in 'deleting'", workspace_id)
        raise
    logger.info("Removed %d graph node(s) for workspace %s", removed, workspace_id)

    try:
        # Core delete, not session.delete(): the database cascade does the work,
        # in one statement, regardless of how the ORM would order the children.
        session.execute(delete(Workspace).where(Workspace.id == workspace_id))
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Postgres delete failed for workspace %s; left in 'deleting'", workspace_id)
        raise
