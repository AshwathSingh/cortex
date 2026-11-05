"""T-12.1: the workspace's unresolved ingestion failures.

    GET /api/workspaces/{workspace_id}/source-failures

Its own endpoint rather than a filter on ``/sources``, because the two answer
different questions. ``/sources`` is an inventory: every source, in name order,
for a page the reader navigates to deliberately. This is an alert: only what is
broken, newest first, and it is polled from the workspace shell on every page so
a failure is noticed without going looking for it (AC1).

Any member may read it. A VIEWER cannot fix a broken source, but telling them
the graph they are reading is stale is the whole point -- and ``needs_reauth``
is about the *workspace's* GitHub authorization, which is not a secret.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession, load_workspace_for_user
from app.services.source_failures import FailureCategory, list_unresolved_failures

router = APIRouter(prefix="/api/workspaces", tags=["sources"])


class SourceFailureResponse(BaseModel):
    repo: str
    kind: str
    category: FailureCategory
    label: str
    message: str | None = None
    advice: str
    #: The UI shows a "Reconnect GitHub" action for these (AC2).
    needs_reauth: bool
    can_retry: bool
    last_attempted_at: datetime | None = None
    #: Still reported for a failing source: the data on screen is this old (AC4).
    last_synced_at: datetime | None = None
    last_synced_by_name: str | None = None


@router.get(
    "/{workspace_id}/source-failures", response_model=list[SourceFailureResponse]
)
def read_source_failures(
    workspace_id: uuid.UUID,
    user: CurrentUser,
    session: DbSession,
) -> list[SourceFailureResponse]:
    """Every source whose last ingestion failed, with the fix for each.

    Postgres only -- no Neo4j call. A failed ingestion writes no graph nodes, so
    there is nothing in the graph to ask about, and keeping this endpoint off
    Neo4j means a graph outage still lets the page report the graph outage.
    """
    load_workspace_for_user(session, user, workspace_id)
    return [
        SourceFailureResponse(
            repo=failure.repo,
            kind=failure.kind,
            category=failure.category,
            label=failure.label,
            message=failure.message,
            advice=failure.advice,
            needs_reauth=failure.needs_reauth,
            can_retry=failure.can_retry,
            last_attempted_at=failure.last_attempted_at,
            last_synced_at=failure.last_synced_at,
            last_synced_by_name=failure.last_synced_by_name,
        )
        for failure in list_unresolved_failures(session, workspace_id)
    ]
