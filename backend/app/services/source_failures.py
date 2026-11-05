"""T-12.1: the unresolved ingestion failures in a workspace, and what to do about them.

US-10 already records *that* an ingestion failed, in ``data_sources.last_error``.
That string is enough to show next to a source but not enough to act on: the
page cannot tell "your GitHub token was revoked" (fix it by signing in again)
from "GitHub is down" (fix it by waiting), and those need different buttons.

So every failure is recorded with a ``FailureCategory`` alongside its message,
and this module turns that category into the two decisions the UI has to make:
whether to offer re-authentication, and whether retrying now is worth anything.

The list is of *unresolved* failures only -- a source whose status is no longer
FAILED is not in it. That is what clears the notification when a source syncs
successfully (AC3): nothing has to remember to dismiss anything, because the
source row stopped being a failure.
"""

import enum
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import DataSource, SyncStatus, User


class FailureCategory(str, enum.Enum):
    """Why an ingestion failed, at the granularity the user can act on.

    Deliberately coarse. A category exists when it leads somewhere different:
    AUTH sends you to a sign-in, RATE_LIMIT tells you to wait, NOT_FOUND tells
    you the reference is wrong. Splitting UPSTREAM into every 5xx GitHub can
    return would give the reader more words and no new decision.
    """

    AUTH = "AUTH"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMIT = "RATE_LIMIT"
    UPSTREAM = "UPSTREAM"
    GRAPH = "GRAPH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class CategoryGuidance:
    #: Short noun phrase for the badge. Not a sentence -- it sits next to one.
    label: str
    #: What the reader should do, in one sentence addressed to them.
    advice: str
    #: Offer the GitHub sign-in flow (AC2).
    needs_reauth: bool
    #: Offer "Try again". False where an immediate retry is known to fail the
    #: same way, so the button would be a lie.
    can_retry: bool


GUIDANCE: dict[FailureCategory, CategoryGuidance] = {
    FailureCategory.AUTH: CategoryGuidance(
        label="Authorization expired",
        advice="Sign in to GitHub again to refresh this workspace's access.",
        needs_reauth=True,
        # Retrying with the same dead credentials fails identically.
        can_retry=False,
    ),
    FailureCategory.NOT_FOUND: CategoryGuidance(
        label="Source unreachable",
        advice=(
            "Check the repository still exists and that your GitHub account can "
            "see it. A repository that was made private needs re-authorization."
        ),
        # A 404 from GitHub is also what a private repo returns to a token that
        # cannot see it, so re-authorizing is a real fix for this one.
        needs_reauth=True,
        can_retry=True,
    ),
    FailureCategory.RATE_LIMIT: CategoryGuidance(
        label="Too many requests",
        advice="GitHub is rate limiting this workspace. Try again a little later.",
        needs_reauth=False,
        can_retry=True,
    ),
    FailureCategory.UPSTREAM: CategoryGuidance(
        label="GitHub error",
        advice="GitHub did not answer correctly. Try again; if it persists, GitHub is having trouble.",
        needs_reauth=False,
        can_retry=True,
    ),
    FailureCategory.GRAPH: CategoryGuidance(
        label="Cortex storage error",
        advice="Cortex could not write to its graph database. Try again shortly.",
        needs_reauth=False,
        can_retry=True,
    ),
    FailureCategory.UNKNOWN: CategoryGuidance(
        label="Ingestion failed",
        advice="Try again. If it keeps failing, the message above is what Cortex recorded.",
        needs_reauth=False,
        can_retry=True,
    ),
}


def parse_category(value: str | None) -> FailureCategory:
    """The stored code, or UNKNOWN.

    Unknown strings fall back rather than raising: the column is plain text so
    that adding a category needs no migration, which also means a row written by
    a newer deployment can arrive here naming a category this one has not heard
    of. A source showing "Ingestion failed" is a worse message than the truth,
    but it is still a usable page.
    """
    if value is None:
        return FailureCategory.UNKNOWN
    try:
        return FailureCategory(value)
    except ValueError:
        return FailureCategory.UNKNOWN


@dataclass(frozen=True)
class SourceFailure:
    """One unresolved failure, with everything the UI needs to offer a fix."""

    repo: str
    kind: str
    category: FailureCategory
    label: str
    #: What the server recorded when it failed. May be None for a row written
    #: before error text was kept.
    message: str | None
    advice: str
    needs_reauth: bool
    can_retry: bool
    last_attempted_at: datetime | None
    #: Kept even though this source is failing: the graph is still showing the
    #: data from this sync, and how stale it is matters (AC4).
    last_synced_at: datetime | None
    last_synced_by_name: str | None


def list_unresolved_failures(
    session: Session, workspace_id: uuid.UUID
) -> list[SourceFailure]:
    """Every source in this workspace whose last ingestion failed.

    Ordered by the attempt time, newest first: the thing that just broke is the
    thing the reader came to look at. Sources are ordered by name everywhere
    else, but a failure list is a queue, not an inventory.
    """
    rows = session.execute(
        select(DataSource, User.display_name, User.github_login)
        .outerjoin(User, User.id == DataSource.last_synced_by)
        .where(
            DataSource.workspace_id == workspace_id,
            DataSource.status == SyncStatus.FAILED,
        )
        .order_by(
            DataSource.last_attempted_at.desc(),
            func.lower(DataSource.external_ref),
        )
    ).all()

    failures: list[SourceFailure] = []
    for source, display_name, github_login in rows:
        category = parse_category(source.last_error_code)
        guidance = GUIDANCE[category]
        failures.append(
            SourceFailure(
                repo=source.external_ref,
                kind=source.kind,
                category=category,
                label=guidance.label,
                message=source.last_error,
                advice=guidance.advice,
                needs_reauth=guidance.needs_reauth,
                can_retry=guidance.can_retry,
                last_attempted_at=source.last_attempted_at,
                last_synced_at=source.last_synced_at,
                # Never the email: a workspace is shared and no other endpoint
                # exposes a member's address.
                last_synced_by_name=display_name or github_login,
            )
        )
    return failures
