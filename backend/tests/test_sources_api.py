"""Authorisation and payload tests for the source inventory endpoint.

US-10 made ``data_sources`` the authoritative list of connected sources, so
these cover the merge: sync state comes from Postgres, counts from Neo4j.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.api.graph import get_neo4j
from app.main import app
from app.models import GITHUB_KIND, DataSource, Role, SyncStatus, User
from tests.authz import sign_in_with_role
from tests.payloads import TEST_WORKSPACE_ID
from tests.test_source_queries import SourceDriver

URL = f"/api/workspaces/{TEST_WORKSPACE_ID}/sources"
ATTEMPTED_AT = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
SYNCED_AT = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)


def graph_record(repo="cortex/app", prs=8, issues=3) -> dict:
    return {
        "repo": repo,
        "pull_requests": prs,
        "issues": issues,
        "total_items": prs + issues,
    }


def add_source(sessions, repo="cortex/app", *, synced_by=False, **over) -> None:
    """Record ``repo`` as a connected source of the signed-in workspace."""
    with sessions() as session:
        defaults = {
            "workspace_id": uuid.UUID(TEST_WORKSPACE_ID),
            "kind": GITHUB_KIND,
            "external_ref": repo,
            "status": SyncStatus.SUCCESS,
            "last_attempted_at": ATTEMPTED_AT,
        }
        if synced_by:
            defaults["last_synced_by"] = session.scalar(select(User.id))
        session.add(DataSource(**{**defaults, **over}))
        session.commit()


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.pop(get_neo4j, None)


def setup(api_db, records=(), role=Role.OWNER, driver=None):
    client, sessions = api_db
    driver = driver if driver is not None else SourceDriver(records)
    app.dependency_overrides[get_neo4j] = lambda: driver
    if role is not None:
        sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, role)
    return client, driver


def test_unauthenticated_request_does_not_read_neo4j(api_db):
    client, driver = setup(api_db, role=None)
    assert client.get(URL).status_code == 401
    assert driver.opened == 0


def test_non_member_request_does_not_read_neo4j(api_db):
    client, driver = setup(api_db, role=None)
    _, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, None)
    assert client.get(URL).status_code == 403
    assert driver.opened == 0


@pytest.mark.parametrize("role", [Role.OWNER, Role.EDITOR, Role.VIEWER])
def test_every_workspace_role_can_list_sources(api_db, role):
    client, _ = setup(api_db, role=role)
    assert client.get(URL).status_code == 200


def test_returns_source_counts(api_db):
    """A repository ingested before ``data_sources`` existed has graph nodes and
    no row. It stays on the page as an indexed source with unknown timestamps --
    the migration needs no backfill."""
    client, _ = setup(api_db, records=[graph_record()])

    assert client.get(URL).json() == [
        {
            "repo": "cortex/app",
            "kind": "github",
            "status": "SUCCESS",
            "pull_requests": 8,
            "issues": 3,
            "total_items": 11,
            "last_attempted_at": None,
            "last_synced_at": None,
            "last_error": None,
            "last_synced_by": None,
            "last_synced_by_name": None,
        }
    ]


def test_a_failed_source_appears_with_no_indexed_items(api_db):
    """AC1. A failed ingestion writes nothing to the graph, so without the
    relational row the source would look like one nobody ever connected."""
    client, _ = setup(api_db)
    _, sessions = api_db
    add_source(
        sessions,
        status=SyncStatus.FAILED,
        last_error="Repository cortex/app not found or not accessible",
    )

    (source,) = client.get(URL).json()
    assert source["status"] == "FAILED"
    assert source["total_items"] == 0
    assert source["last_error"] == "Repository cortex/app not found or not accessible"
    assert source["last_synced_at"] is None


def test_a_failed_source_still_reports_its_last_successful_sync(api_db):
    """Succeeded on the 5th, failed on the 8th: both facts have to reach the UI,
    because the data on screen really is three days old."""
    client, _ = setup(api_db, records=[graph_record()])
    _, sessions = api_db
    add_source(
        sessions,
        status=SyncStatus.FAILED,
        last_synced_at=SYNCED_AT,
        last_error="GitHub rate limit reached",
        synced_by=True,
    )

    (source,) = client.get(URL).json()
    assert source["status"] == "FAILED"
    assert source["last_synced_at"].startswith("2026-10-05T09:00")
    assert source["last_attempted_at"].startswith("2026-10-08T09:00")
    assert source["total_items"] == 11


def test_a_synced_source_reports_when_and_who(api_db):
    """AC2/AC3: a green indicator plus "Synced ... by <name>"."""
    client, _ = setup(api_db, records=[graph_record()])
    _, sessions = api_db
    add_source(sessions, last_synced_at=SYNCED_AT, synced_by=True)

    (source,) = client.get(URL).json()
    assert source["status"] == "SUCCESS"
    assert source["last_synced_at"].startswith("2026-10-05T09:00")
    assert source["last_synced_by_name"] == "member"
    assert source["last_synced_by"] is not None
    assert (source["pull_requests"], source["issues"]) == (8, 3)


def test_a_source_mid_ingestion_is_reported_as_pending(api_db):
    client, _ = setup(api_db)
    _, sessions = api_db
    add_source(sessions, status=SyncStatus.PENDING)

    (source,) = client.get(URL).json()
    assert source["status"] == "PENDING"
    assert source["last_synced_at"] is None
    assert source["total_items"] == 0


def test_a_recorded_source_is_not_duplicated_by_its_graph_counts(api_db):
    client, _ = setup(api_db, records=[graph_record()])
    _, sessions = api_db
    add_source(sessions, last_synced_at=SYNCED_AT)

    assert len(client.get(URL).json()) == 1


def test_sources_are_ordered_case_insensitively(api_db):
    client, _ = setup(api_db, records=[graph_record(repo="cortex/Mango")])
    _, sessions = api_db
    add_source(sessions, repo="cortex/Zebra")
    add_source(sessions, repo="cortex/apple")

    assert [s["repo"] for s in client.get(URL).json()] == [
        "cortex/apple",
        "cortex/Mango",
        "cortex/Zebra",
    ]


def test_empty_workspace_returns_an_empty_list(api_db):
    client, _ = setup(api_db)
    assert client.get(URL).json() == []


def test_neo4j_failure_returns_503(api_db):
    """Still a 503 rather than a list with zero counts: zero is exactly how a
    failed ingestion looks, and showing that silently would be a lie."""
    from neo4j.exceptions import ServiceUnavailable

    class DownDriver:
        opened = 0

        def session(self):
            self.opened += 1
            raise ServiceUnavailable("down")

    client, _ = setup(api_db, driver=DownDriver())
    _, sessions = api_db
    add_source(sessions, last_synced_at=SYNCED_AT)

    assert client.get(URL).status_code == 503
