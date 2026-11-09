"""T-27.1/T-27.2: reading and writing comments on graph nodes and edges.

Targets
-------
A comment names its target by the key the client already uses: ``"Issue:42"``
for a node, ``"Author:7|AUTHORED|Issue:42"`` for an edge. ``parse_target``
checks that the key is the right *shape* for its kind, which is the one thing
worth checking here -- it keeps a typo or a hand-written request from creating a
comment on a target nothing can ever reach, without making the comment depend on
Neo4j being up (see the module docstring in ``app.models.graph_comment``).

Unseen counts
-------------
"This node has comments you have not seen" is one timestamp comparison per
target, against the reader's ``graph_comment_views`` row. Two deliberate rules:

* no row at all means *nothing* has been seen, so a node somebody commented on
  before you ever opened it is correctly marked
* your own comments never count as unseen -- you wrote them

The counts are computed with ``sum(case(...))`` rather than an aggregate
``FILTER`` so the same statement runs on the SQLite the tests use.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Integer, case, func, select
from sqlalchemy.orm import Session

from app.graph.queries import GRAPH_LABELS
from app.models import (
    MAX_COMMENT_LENGTH,
    MAX_TARGET_KEY_LENGTH,
    CommentTarget,
    GraphComment,
    GraphCommentView,
    User,
)


class InvalidTarget(ValueError):
    """The target kind and key do not describe something in the graph."""


class InvalidComment(ValueError):
    """The comment body is empty or too long."""


@dataclass(frozen=True)
class Target:
    kind: CommentTarget
    key: str


@dataclass(frozen=True)
class Comment:
    """One comment plus its author's display name, resolved at read time."""

    id: uuid.UUID
    target_kind: CommentTarget
    target_key: str
    body: str
    author_id: uuid.UUID | None
    author_name: str | None
    created_at: datetime


@dataclass(frozen=True)
class TargetActivity:
    """What the canvas needs to mark one target (T-27.4)."""

    target_kind: CommentTarget
    target_key: str
    total: int
    unseen: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_node_key(key: str) -> bool:
    label, separator, raw_id = key.partition(":")
    if not separator or label not in GRAPH_LABELS or not raw_id:
        return False
    # Matches app.graph.queries._parse_node_key: ids in this graph are GitHub
    # integers, and the node-details route will not resolve anything else.
    return raw_id.lstrip("-").isdigit()


def parse_target(kind: str, key: str) -> Target:
    """Validate a target kind and key, or raise ``InvalidTarget``."""
    try:
        target_kind = CommentTarget(kind)
    except ValueError as exc:
        raise InvalidTarget("Target kind must be 'node' or 'edge'") from exc

    key = key.strip()
    if not key or len(key) > MAX_TARGET_KEY_LENGTH:
        raise InvalidTarget("Target key is missing or too long")

    if target_kind is CommentTarget.NODE:
        if not _is_node_key(key):
            raise InvalidTarget(f"Not a graph node key: {key!r}")
        return Target(target_kind, key)

    source, separator, rest = key.partition("|")
    edge_type, separator_two, target = rest.partition("|")
    if not (separator and separator_two and edge_type):
        raise InvalidTarget(f"Not a graph edge key: {key!r}")
    if not (_is_node_key(source) and _is_node_key(target)):
        raise InvalidTarget(f"Not a graph edge key: {key!r}")
    return Target(target_kind, key)


def _clean_body(body: str) -> str:
    cleaned = body.strip()
    if not cleaned:
        raise InvalidComment("A comment cannot be empty")
    if len(cleaned) > MAX_COMMENT_LENGTH:
        raise InvalidComment(
            f"A comment cannot be longer than {MAX_COMMENT_LENGTH} characters"
        )
    return cleaned


def _display_name(user: User | None) -> str | None:
    if user is None:
        return None
    # display_name, then the GitHub login, then nothing. Never the email: a
    # workspace is shared and no other endpoint exposes a member's address.
    return user.display_name or user.github_login


def list_comments(
    session: Session, workspace_id: uuid.UUID, target: Target
) -> list[Comment]:
    """One target's thread, oldest first (AC1).

    Oldest first because it is a conversation, not a feed: the argument only
    makes sense read in the order it was made. ``id`` breaks ties so two
    comments posted in the same instant still have a stable order.
    """
    rows = session.execute(
        select(GraphComment, User)
        .outerjoin(User, User.id == GraphComment.author_id)
        .where(
            GraphComment.workspace_id == workspace_id,
            GraphComment.target_kind == target.kind.value,
            GraphComment.target_key == target.key,
        )
        .order_by(GraphComment.created_at, GraphComment.id)
    ).all()

    return [
        Comment(
            id=comment.id,
            target_kind=CommentTarget(comment.target_kind),
            target_key=comment.target_key,
            body=comment.body,
            author_id=comment.author_id,
            author_name=_display_name(author),
            created_at=comment.created_at,
        )
        for comment, author in rows
    ]


def post_comment(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    author: User,
    target: Target,
    body: str,
) -> Comment:
    """Add a comment and treat it as already read by its author.

    ``created_at`` is set here rather than left to the column default. SQLite's
    ``CURRENT_TIMESTAMP`` has one-second resolution, so a default-valued comment
    posted moments after a read marker could compare as older than it and be
    born already "seen".
    """
    comment = GraphComment(
        workspace_id=workspace_id,
        target_kind=target.kind.value,
        target_key=target.key,
        body=_clean_body(body),
        author_id=author.id,
        created_at=_now(),
    )
    session.add(comment)
    session.flush()
    return Comment(
        id=comment.id,
        target_kind=target.kind,
        target_key=target.key,
        body=comment.body,
        author_id=author.id,
        author_name=_display_name(author),
        created_at=comment.created_at,
    )


def find_comment(
    session: Session, workspace_id: uuid.UUID, comment_id: uuid.UUID
) -> GraphComment | None:
    """Scoped to the workspace, so a comment id from another one is simply absent."""
    return session.scalar(
        select(GraphComment).where(
            GraphComment.id == comment_id,
            GraphComment.workspace_id == workspace_id,
        )
    )


def delete_comment(session: Session, comment: GraphComment) -> None:
    session.delete(comment)


def comment_activity(
    session: Session, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> list[TargetActivity]:
    """Every commented-on target in the workspace, with this reader's unseen count."""
    views = (
        select(
            GraphCommentView.target_kind.label("target_kind"),
            GraphCommentView.target_key.label("target_key"),
            GraphCommentView.last_seen_at.label("last_seen_at"),
        )
        .where(
            GraphCommentView.workspace_id == workspace_id,
            GraphCommentView.user_id == user_id,
        )
        .subquery()
    )

    unseen = case(
        (
            # No marker means nothing has been seen, so a target somebody
            # commented on before this reader ever opened it still counts.
            (
                (views.c.last_seen_at.is_(None))
                | (GraphComment.created_at > views.c.last_seen_at)
            )
            # You have seen what you wrote.
            & (
                (GraphComment.author_id.is_(None))
                | (GraphComment.author_id != user_id)
            ),
            1,
        ),
        else_=0,
    )

    rows = session.execute(
        select(
            GraphComment.target_kind,
            GraphComment.target_key,
            func.count(GraphComment.id),
            func.coalesce(func.sum(unseen), 0).cast(Integer),
        )
        .outerjoin(
            views,
            (views.c.target_kind == GraphComment.target_kind)
            & (views.c.target_key == GraphComment.target_key),
        )
        .where(GraphComment.workspace_id == workspace_id)
        .group_by(GraphComment.target_kind, GraphComment.target_key)
        .order_by(GraphComment.target_kind, GraphComment.target_key)
    ).all()

    return [
        TargetActivity(
            target_kind=CommentTarget(kind),
            target_key=key,
            total=int(total),
            unseen=int(unseen_count),
        )
        for kind, key, total, unseen_count in rows
    ]


def mark_seen(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    target: Target,
) -> datetime:
    """Record that this reader has now seen this target's comments.

    Upsert by hand rather than with a dialect-specific ``ON CONFLICT``: the row
    is private to one reader, so two concurrent writes are the same person in
    two tabs, and the unique constraint is still there to catch it.
    """
    seen_at = _now()
    existing = session.scalar(
        select(GraphCommentView).where(
            GraphCommentView.workspace_id == workspace_id,
            GraphCommentView.user_id == user_id,
            GraphCommentView.target_kind == target.kind.value,
            GraphCommentView.target_key == target.key,
        )
    )
    if existing is None:
        session.add(
            GraphCommentView(
                workspace_id=workspace_id,
                user_id=user_id,
                target_kind=target.kind.value,
                target_key=target.key,
                last_seen_at=seen_at,
            )
        )
    else:
        existing.last_seen_at = seen_at
    return seen_at
