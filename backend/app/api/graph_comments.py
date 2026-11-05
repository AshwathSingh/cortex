"""T-27.2: reading, posting and deleting comments on graph nodes and edges.

    GET    /api/workspaces/{id}/graph/comments?target_kind=node&target_key=Issue:42
    POST   /api/workspaces/{id}/graph/comments
    DELETE /api/workspaces/{id}/graph/comments/{comment_id}
    GET    /api/workspaces/{id}/graph/comments/activity
    POST   /api/workspaces/{id}/graph/comments/seen

Who may do what
---------------
Membership is the gate for reading *and* posting. The story is about discussing
a suggestion "before approving them", and a VIEWER who can see the graph but not
say anything about it cannot take part in that -- while posting a comment changes
no graph data, so ``sources.write`` would be the wrong permission to borrow.

Deleting is narrower: your own comment, or anyone holding ``members.manage``,
which is the permission that already means "responsible for who is in this
workspace and what they are doing in it". A comment nobody can remove would make
the inspector a place to leave something permanent by accident.

Every query is filtered by ``workspace_id`` on top of
``load_workspace_for_user``, so a comment is invisible from any other workspace
(AC3) -- including by id, which returns the same 404 as one that never existed.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession, load_workspace_for_user
from app.models import MAX_COMMENT_LENGTH, CommentTarget
from app.permissions import Permission, membership_permissions
from app.services.graph_comments import (
    InvalidComment,
    InvalidTarget,
    comment_activity,
    delete_comment,
    find_comment,
    list_comments,
    mark_seen,
    parse_target,
    post_comment,
)

router = APIRouter(prefix="/api/workspaces", tags=["graph-comments"])


class GraphCommentResponse(BaseModel):
    id: uuid.UUID
    target_kind: CommentTarget
    target_key: str
    body: str
    #: Null for a comment whose author has left or been deleted. The comment
    #: stays: a discussion others took decisions from must not be rewritten.
    author_id: uuid.UUID | None = None
    author_name: str | None = None
    created_at: datetime


class NewGraphComment(BaseModel):
    target_kind: CommentTarget
    target_key: str = Field(min_length=1, max_length=512)
    body: str = Field(min_length=1, max_length=MAX_COMMENT_LENGTH)


class TargetRef(BaseModel):
    target_kind: CommentTarget
    target_key: str = Field(min_length=1, max_length=512)


class TargetActivityResponse(BaseModel):
    target_kind: CommentTarget
    target_key: str
    total: int
    #: Comments this caller has not seen, which is what marks the canvas (AC2).
    unseen: int


class SeenResponse(BaseModel):
    target_kind: CommentTarget
    target_key: str
    last_seen_at: datetime


def _target(kind: CommentTarget | str, key: str):
    try:
        return parse_target(
            kind.value if isinstance(kind, CommentTarget) else kind, key
        )
    except InvalidTarget as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{workspace_id}/graph/comments/activity", response_model=list[TargetActivityResponse])
def read_comment_activity(
    workspace_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> list[TargetActivityResponse]:
    """Every commented-on target in the workspace, with this caller's unseen count.

    One request for the whole canvas rather than one per node: the canvas has to
    mark everything before the reader clicks anything (AC2), and a graph can
    carry thousands of nodes.
    """
    load_workspace_for_user(session, user, workspace_id)
    return [
        TargetActivityResponse(
            target_kind=item.target_kind,
            target_key=item.target_key,
            total=item.total,
            unseen=item.unseen,
        )
        for item in comment_activity(session, workspace_id, user.id)
    ]


@router.get("/{workspace_id}/graph/comments", response_model=list[GraphCommentResponse])
def read_graph_comments(
    workspace_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    target_kind: CommentTarget = Query(),
    target_key: str = Query(min_length=1, max_length=512),
) -> list[GraphCommentResponse]:
    """One target's thread, oldest first (AC1)."""
    load_workspace_for_user(session, user, workspace_id)
    target = _target(target_kind, target_key)
    return [
        GraphCommentResponse(
            id=comment.id,
            target_kind=comment.target_kind,
            target_key=comment.target_key,
            body=comment.body,
            author_id=comment.author_id,
            author_name=comment.author_name,
            created_at=comment.created_at,
        )
        for comment in list_comments(session, workspace_id, target)
    ]


@router.post(
    "/{workspace_id}/graph/comments",
    response_model=GraphCommentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_graph_comment(
    workspace_id: uuid.UUID,
    body: NewGraphComment,
    user: CurrentUser,
    session: DbSession,
) -> GraphCommentResponse:
    load_workspace_for_user(session, user, workspace_id)
    target = _target(body.target_kind, body.target_key)
    try:
        comment = post_comment(
            session,
            workspace_id=workspace_id,
            author=user,
            target=target,
            body=body.body,
        )
    except InvalidComment as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # Posting is also reading: the author has seen their own comment and
    # everything above it, so the thread they just replied in is not left
    # marked unread to them.
    mark_seen(session, workspace_id=workspace_id, user_id=user.id, target=target)
    session.commit()
    return GraphCommentResponse(
        id=comment.id,
        target_kind=comment.target_kind,
        target_key=comment.target_key,
        body=comment.body,
        author_id=comment.author_id,
        author_name=comment.author_name,
        created_at=comment.created_at,
    )


@router.delete(
    "/{workspace_id}/graph/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_graph_comment(
    workspace_id: uuid.UUID,
    comment_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> None:
    _, membership = load_workspace_for_user(session, user, workspace_id)
    comment = find_comment(session, workspace_id, comment_id)
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")

    may_moderate = Permission.MEMBERS_MANAGE in membership_permissions(membership)
    if comment.author_id != user.id and not may_moderate:
        raise HTTPException(
            status_code=403,
            detail="You can only delete your own comments",
        )
    delete_comment(session, comment)
    session.commit()


@router.post("/{workspace_id}/graph/comments/seen", response_model=SeenResponse)
def mark_comments_seen(
    workspace_id: uuid.UUID,
    body: TargetRef,
    user: CurrentUser,
    session: DbSession,
) -> SeenResponse:
    """Record that this caller has read this target's comments (T-27.4)."""
    load_workspace_for_user(session, user, workspace_id)
    target = _target(body.target_kind, body.target_key)
    seen_at = mark_seen(
        session, workspace_id=workspace_id, user_id=user.id, target=target
    )
    session.commit()
    return SeenResponse(
        target_kind=target.kind, target_key=target.key, last_seen_at=seen_at
    )
