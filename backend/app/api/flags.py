"""T-28.1: the Pruning Agent's findings for a workspace.

    GET /api/workspaces/{workspace_id}/flags

The detection runs on the read rather than on a schedule into a table. Two
reasons: a stored flag goes stale the moment the thing it describes changes, so
a queue built from a table would keep showing findings that have already been
fixed; and the rules are a linear pass over one Cypher read, so there is nothing
to amortise.

The cost is that a flag cannot yet be dismissed or acknowledged -- that needs
somewhere to put the dismissal, which is the first thing to add if the queue
grows past the point where re-reading it is enough. Flag ids are derived from
the finding itself, so that table can reference them when it exists.

Any member may read it (AC3). Flags are made of the workspace's own data, every
member can already see that data on the canvas, and a review queue only half the
team can see is not a review queue.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from neo4j import Driver
from neo4j.exceptions import DriverError, Neo4jError
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession, load_workspace_for_user
from app.db.neo4j_driver import get_driver
from app.pruning.detect import FlagRule, Severity, detect_flags
from app.pruning.graph import DEFAULT_ITEM_LIMIT, fetch_items

router = APIRouter(prefix="/api/workspaces", tags=["flags"])


class FlagEvidence(BaseModel):
    label: str
    detail: str


class FlagTargetResponse(BaseModel):
    key: str
    type: str
    title: str
    url: str | None = None


class FlagResponse(BaseModel):
    #: Derived from the rule and its targets, so the same finding keeps the same
    #: id across runs even though nothing is stored.
    id: str
    rule: FlagRule
    label: str
    severity: Severity
    summary: str
    targets: list[FlagTargetResponse]
    #: Exactly what caused this flag, so the reader can judge it (AC4).
    evidence: list[FlagEvidence]


class FlagsResponse(BaseModel):
    workspace_id: uuid.UUID
    #: When the rules ran. They run on this request, so it is "now".
    generated_at: datetime
    flags: list[FlagResponse]
    #: The item ceiling was reached, so the rules saw a subset of the workspace.
    truncated: bool


def get_neo4j() -> Driver:
    """Injectable so tests can supply a fake driver (same shape as app.api.graph)."""
    return get_driver()


@router.get("/{workspace_id}/flags", response_model=FlagsResponse)
def read_workspace_flags(
    workspace_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
    item_limit: int = Query(DEFAULT_ITEM_LIMIT, ge=1, le=10_000),
    driver: Driver = Depends(get_neo4j),
) -> FlagsResponse:
    load_workspace_for_user(session, user, workspace_id)

    try:
        items, truncated = fetch_items(driver, workspace_id, limit=item_limit)
    except (Neo4jError, DriverError):
        # Not an empty queue: "nothing needs review" and "we could not look" are
        # different answers, and the first one is the dangerous thing to fake.
        raise HTTPException(status_code=503, detail="Graph database unavailable")

    flags = detect_flags(items)
    return FlagsResponse(
        workspace_id=workspace_id,
        generated_at=datetime.now(timezone.utc),
        flags=[
            FlagResponse(
                id=flag.id,
                rule=flag.rule,
                label=flag.label,
                severity=flag.severity,
                summary=flag.summary,
                targets=[
                    FlagTargetResponse(
                        key=target.key,
                        type=target.type,
                        title=target.title,
                        url=target.url,
                    )
                    for target in flag.targets
                ],
                evidence=[
                    FlagEvidence(label=item.label, detail=item.detail)
                    for item in flag.evidence
                ],
            )
            for flag in flags
        ],
        truncated=truncated,
    )
