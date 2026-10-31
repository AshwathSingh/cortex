"""US-04: remove a member from a workspace.

    DELETE /api/workspaces/{id}/members/{user_id}   -> 204

Needs ``members.manage``, except that anyone may remove themselves (leave). Only
an owner can remove an owner, and the last owner can't be removed or leave.
"""

import uuid

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import CurrentUser, DbSession, load_workspace_for_user
from app.services import members as member_service
from app.services.roles import RoleError

router = APIRouter(prefix="/api/workspaces", tags=["members"])


@router.delete(
    "/{workspace_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
def remove_workspace_member(
    workspace_id: uuid.UUID, user_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> Response:
    # Membership only here: the permission depends on whether this is a self-leave,
    # so the service decides (after locking).
    _, actor = load_workspace_for_user(session, user, workspace_id)
    try:
        member_service.remove_member(
            session, workspace_id=workspace_id, actor=actor, target_user_id=user_id
        )
        session.commit()
    except RoleError as e:
        session.rollback()
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
