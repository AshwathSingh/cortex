"""T-10.3: the sync-state writes and the Postgres/Neo4j merge."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.graph.queries import SourceSummaryPayload
from app.services import data_sources
from app.models import GITHUB_KIND, DataSource, Role, SyncStatus
from app.services.data_sources import (
    MAX_ERROR_LENGTH,
    SyncedSource,
    build_source_inventory,
    list_synced_sources,
    record_sync_attempt,
    record_sync_failure,
    record_sync_success,
)
from tests.authz import grant, make_user, make_workspace
from tests.payloads import TEST_WORKSPACE_ID, TEST_WORKSPACE_ID_B

REPO = "cortex/app"


@pytest.fixture
def workspace(db_sessions):
    """A workspace with an OWNER, so the FKs on `data_sources` are satisfiable."""
    with db_sessions() as session:
        user = make_user(session, "owner@example.com")
        ws = make_workspace(session, "Primary", TEST_WORKSPACE_ID)
        make_workspace(session, "Secondary", TEST_WORKSPACE_ID_B)
        grant(session, ws, user, Role.OWNER)
        session.commit()
        return uuid.UUID(TEST_WORKSPACE_ID), user.id


def rows(db_sessions, workspace_id=uuid.UUID(TEST_WORKSPACE_ID)) -> list[DataSource]:
    with db_sessions() as session:
        return [entry.source for entry in list_synced_sources(session, workspace_id)]


def summary(repo=REPO, prs=8, issues=3) -> SourceSummaryPayload:
    return SourceSummaryPayload(
        repo=repo, pull_requests=prs, issues=issues, total_items=prs + issues
    )


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------


def test_attempt_creates_a_pending_source(db_sessions, workspace):
    workspace_id, _ = workspace
    with db_sessions() as session:
        record_sync_attempt(session, workspace_id=workspace_id, external_ref=REPO)
        session.commit()

    (source,) = rows(db_sessions)
    assert source.status is SyncStatus.PENDING
    assert source.kind == GITHUB_KIND
    assert source.external_ref == REPO
    assert source.last_attempted_at is not None
    # Nothing has landed yet, so there is no sync to report.
    assert source.last_synced_at is None
    assert source.last_synced_by is None


def test_success_records_who_synced_and_when(db_sessions, workspace):
    workspace_id, user_id = workspace
    with db_sessions() as session:
        record_sync_attempt(session, workspace_id=workspace_id, external_ref=REPO)
        record_sync_success(
            session, workspace_id=workspace_id, external_ref=REPO, user_id=user_id
        )
        session.commit()

    (source,) = rows(db_sessions)
    assert source.status is SyncStatus.SUCCESS
    assert source.last_synced_at is not None
    assert source.last_synced_by == user_id
    assert source.last_error is None


def test_failure_keeps_the_previous_sync_timestamp(db_sessions, workspace):
    """A source that succeeded and then failed has to show both: "Needs
    attention" and the real age of the data still on screen."""
    workspace_id, user_id = workspace
    with db_sessions() as session:
        record_sync_success(
            session, workspace_id=workspace_id, external_ref=REPO, user_id=user_id
        )
        session.commit()
        synced_at = rows(db_sessions)[0].last_synced_at

        record_sync_failure(
            session,
            workspace_id=workspace_id,
            external_ref=REPO,
            error="Repository cortex/app not found or not accessible",
        )
        session.commit()

    (source,) = rows(db_sessions)
    assert source.status is SyncStatus.FAILED
    assert source.last_error == "Repository cortex/app not found or not accessible"
    assert source.last_synced_at == synced_at
    assert source.last_synced_by == user_id


def test_success_clears_a_previous_error(db_sessions, workspace):
    workspace_id, user_id = workspace
    with db_sessions() as session:
        record_sync_failure(
            session, workspace_id=workspace_id, external_ref=REPO, error="boom"
        )
        session.commit()
        record_sync_success(
            session, workspace_id=workspace_id, external_ref=REPO, user_id=user_id
        )
        session.commit()

    (source,) = rows(db_sessions)
    assert source.status is SyncStatus.SUCCESS
    assert source.last_error is None


def test_re_syncing_updates_the_same_row(db_sessions, workspace):
    workspace_id, user_id = workspace
    with db_sessions() as session:
        record_sync_success(
            session, workspace_id=workspace_id, external_ref=REPO, user_id=user_id
        )
        session.commit()
    # Read both timestamps back out of the database: SQLite drops the timezone,
    # so a value still held in memory is not comparable with a reloaded one.
    first = rows(db_sessions)[0]
    first_id, first_attempt = first.id, first.last_attempted_at

    with db_sessions() as session:
        record_sync_attempt(session, workspace_id=workspace_id, external_ref=REPO)
        session.commit()

    (source,) = rows(db_sessions)
    assert source.id == first_id
    assert source.last_attempted_at >= first_attempt
    # The previous success is still on record while the new attempt runs.
    assert source.last_synced_at is not None


def test_a_losing_race_reuses_the_winners_row(db_sessions, workspace, monkeypatch):
    """Two people connecting the same repo at once: the loser has to recover the
    winner's row, not lose its whole transaction to the unique constraint. The
    lookup is stubbed to miss once, which is what the race looks like."""
    workspace_id, _ = workspace
    with db_sessions() as session:
        record_sync_attempt(session, workspace_id=workspace_id, external_ref=REPO)
        session.commit()
    winner_id = rows(db_sessions)[0].id

    real_find = data_sources._find
    misses = []

    def find_missing_once(*args, **kwargs):
        misses.append(1)
        return None if len(misses) == 1 else real_find(*args, **kwargs)

    monkeypatch.setattr(data_sources, "_find", find_missing_once)

    with db_sessions() as session:
        recovered = record_sync_attempt(
            session, workspace_id=workspace_id, external_ref=REPO
        )
        session.commit()

    assert recovered.id == winner_id
    assert len(rows(db_sessions)) == 1


def test_the_same_repo_in_two_workspaces_is_two_sources(db_sessions, workspace):
    workspace_id, _ = workspace
    other = uuid.UUID(TEST_WORKSPACE_ID_B)
    with db_sessions() as session:
        record_sync_attempt(session, workspace_id=workspace_id, external_ref=REPO)
        record_sync_failure(
            session, workspace_id=other, external_ref=REPO, error="not accessible"
        )
        session.commit()

    assert [s.status for s in rows(db_sessions)] == [SyncStatus.PENDING]
    assert [s.status for s in rows(db_sessions, other)] == [SyncStatus.FAILED]


def test_long_errors_are_truncated(db_sessions, workspace):
    workspace_id, _ = workspace
    with db_sessions() as session:
        record_sync_failure(
            session, workspace_id=workspace_id, external_ref=REPO, error="x" * 5_000
        )
        session.commit()

    assert len(rows(db_sessions)[0].last_error) == MAX_ERROR_LENGTH


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------


def test_sources_are_listed_case_insensitively_by_name(db_sessions, workspace):
    workspace_id, _ = workspace
    with db_sessions() as session:
        for repo in ("cortex/Zebra", "cortex/apple", "cortex/Banana"):
            record_sync_attempt(session, workspace_id=workspace_id, external_ref=repo)
        session.commit()

    assert [s.external_ref for s in rows(db_sessions)] == [
        "cortex/apple",
        "cortex/Banana",
        "cortex/Zebra",
    ]


def test_listing_names_whoever_last_synced(db_sessions, workspace):
    workspace_id, user_id = workspace
    with db_sessions() as session:
        record_sync_success(
            session, workspace_id=workspace_id, external_ref=REPO, user_id=user_id
        )
        session.commit()

    with db_sessions() as session:
        (entry,) = list_synced_sources(session, workspace_id)
    assert entry.last_synced_by_name == "owner"


def test_listing_leaves_the_name_unknown_when_nobody_is_recorded(
    db_sessions, workspace
):
    workspace_id, _ = workspace
    with db_sessions() as session:
        record_sync_attempt(session, workspace_id=workspace_id, external_ref=REPO)
        session.commit()

    with db_sessions() as session:
        (entry,) = list_synced_sources(session, workspace_id)
    assert entry.last_synced_by_name is None


def test_a_workspace_with_no_sources_lists_nothing(db_sessions, workspace):
    assert rows(db_sessions, uuid.UUID(TEST_WORKSPACE_ID_B)) == []


# --------------------------------------------------------------------------
# Merge
# --------------------------------------------------------------------------


def source(**over) -> SyncedSource:
    defaults = {
        "workspace_id": uuid.UUID(TEST_WORKSPACE_ID),
        "kind": GITHUB_KIND,
        "external_ref": REPO,
        "status": SyncStatus.SUCCESS,
        "last_attempted_at": datetime(2026, 10, 8, tzinfo=timezone.utc),
    }
    name = over.pop("name", None)
    return SyncedSource(
        source=DataSource(**{**defaults, **over}), last_synced_by_name=name
    )


def test_merge_takes_counts_from_the_graph():
    synced_at = datetime(2026, 10, 8, tzinfo=timezone.utc)
    (item,) = build_source_inventory(
        [source(last_synced_at=synced_at, name="Ashwath")], [summary()]
    )

    assert (item.repo, item.pull_requests, item.issues, item.total_items) == (
        REPO, 8, 3, 11,
    )
    assert item.status is SyncStatus.SUCCESS
    assert item.last_synced_at == synced_at
    assert item.last_synced_by_name == "Ashwath"


def test_merge_keeps_a_failed_source_with_no_graph_nodes():
    """AC1: a failed ingestion writes nothing to the graph, so the source would
    otherwise be indistinguishable from one nobody ever connected."""
    (item,) = build_source_inventory(
        [source(status=SyncStatus.FAILED, last_error="Repository not found")], []
    )

    assert item.status is SyncStatus.FAILED
    assert item.total_items == 0
    assert item.last_error == "Repository not found"
    assert item.last_synced_at is None


def test_merge_keeps_a_repo_ingested_before_the_table_existed():
    """No backfill: graph nodes with no row are reported as an indexed source
    with unknown timestamps, rather than dropped off the page."""
    (item,) = build_source_inventory([], [summary(repo="cortex/legacy")])

    assert item.repo == "cortex/legacy"
    assert item.status is SyncStatus.SUCCESS
    assert item.total_items == 11
    assert (item.last_attempted_at, item.last_synced_at) == (None, None)


def test_merge_does_not_duplicate_a_source_present_in_both_stores():
    items = build_source_inventory([source()], [summary()])
    assert len(items) == 1


def test_merge_orders_sources_case_insensitively():
    items = build_source_inventory(
        [source(external_ref="cortex/Zebra"), source(external_ref="cortex/apple")],
        [summary(repo="cortex/Mango")],
    )
    assert [item.repo for item in items] == [
        "cortex/apple",
        "cortex/Mango",
        "cortex/Zebra",
    ]


def test_merge_of_nothing_is_nothing():
    assert build_source_inventory([], []) == []


def test_merge_reports_a_pending_source_as_syncing():
    attempted = datetime.now(timezone.utc) - timedelta(seconds=30)
    (item,) = build_source_inventory(
        [source(status=SyncStatus.PENDING, last_attempted_at=attempted)], []
    )

    assert item.status is SyncStatus.PENDING
    assert item.last_attempted_at == attempted
    assert item.last_synced_at is None
