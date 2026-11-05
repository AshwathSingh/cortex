"""T-12.4: categorising ingestion failures and listing the unresolved ones.

Two halves. The first drives the real ingestion endpoint with a GitHub that
fails in a particular way, and checks the category that gets recorded -- because
the thing worth testing is not the taxonomy in isolation but whether the right
category reaches the database from the right exception. The second reads the
failures endpoint and checks the four acceptance criteria.

No Neo4j: a failed ingestion writes no graph nodes, so there is nothing to look
at there, and the failures endpoint deliberately never asks.
"""

import datetime as dt
import uuid

import httpx
import pytest
from neo4j.exceptions import ServiceUnavailable

from app.api.ingest import get_github_client, get_neo4j
from app.github.client import GitHubClient
from app.main import app
from app.models import DataSource, Role, SyncStatus
from app.services.source_failures import (
    GUIDANCE,
    FailureCategory,
    list_unresolved_failures,
    parse_category,
)
from tests.authz import make_user, make_workspace, sign_in_with_role
from tests.payloads import TEST_REPO, TEST_REPO_URL, TEST_WORKSPACE_ID

INGEST_URL = "/api/ingest/github"
FAILURES_URL = f"/api/workspaces/{TEST_WORKSPACE_ID}/source-failures"


class FakeTx:
    def __init__(self):
        self.calls = []

    def run(self, cypher, **params):
        self.calls.append((cypher, params))
        return None


class FakeSession:
    def __init__(self, tx):
        self.tx = tx

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute_write(self, fn):
        return fn(self.tx)


class FakeDriver:
    """A graph that accepts everything, so only the GitHub half can fail."""

    def __init__(self):
        self.tx = FakeTx()

    def session(self):
        return FakeSession(self.tx)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.pop(get_github_client, None)
    app.dependency_overrides.pop(get_neo4j, None)


def ingesting(api_db, handler, role: Role = Role.OWNER):
    """A signed-in OWNER, a fake graph, and a GitHub that answers ``handler``."""
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, role)
    app.dependency_overrides[get_github_client] = lambda: GitHubClient(
        transport=httpx.MockTransport(handler), sleep=lambda s: None
    )
    app.dependency_overrides[get_neo4j] = FakeDriver
    return client


def ingest(client):
    return client.post(
        INGEST_URL, json={"repo_url": TEST_REPO_URL, "workspace_id": TEST_WORKSPACE_ID}
    )


def ok_repo(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=[])


def responds(status: int, headers: dict[str, str] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": "no"}, headers=headers or {})

    return handler


def stored(api_db) -> DataSource:
    _, sessions = api_db
    with sessions() as session:
        return session.query(DataSource).one()


WS = uuid.UUID(TEST_WORKSPACE_ID)


def failed_source(
    workspace_id: uuid.UUID = WS,
    external_ref: str = TEST_REPO,
    category: FailureCategory = FailureCategory.AUTH,
    attempted_minutes_ago: int = 0,
) -> DataSource:
    """A FAILED row written straight to the database.

    Some cases cannot be produced by driving the endpoint -- a VIEWER is not
    allowed to trigger the ingestion that would break the source, and two
    failures minutes apart would need a clock to move.
    """
    return DataSource(
        workspace_id=workspace_id,
        kind="github",
        external_ref=external_ref,
        status=SyncStatus.FAILED,
        last_attempted_at=dt.datetime.now(dt.timezone.utc)
        - dt.timedelta(minutes=attempted_minutes_ago),
        last_error="recorded failure",
        last_error_code=category.value,
    )


# --- the taxonomy itself ----------------------------------------------------


def test_every_category_has_guidance():
    """A category with no entry would raise a KeyError while rendering an error
    page, which is the worst possible moment to find out."""
    assert set(GUIDANCE) == set(FailureCategory)


def test_an_unknown_stored_code_degrades_instead_of_raising():
    # A row written by a newer deployment naming a category this one has never
    # heard of still has to render.
    assert parse_category("SOMETHING_NEW") is FailureCategory.UNKNOWN
    assert parse_category(None) is FailureCategory.UNKNOWN


def test_only_the_fixable_categories_offer_a_sign_in():
    offered = {c for c in FailureCategory if GUIDANCE[c].needs_reauth}
    assert offered == {FailureCategory.AUTH, FailureCategory.NOT_FOUND}


def test_an_expired_authorization_does_not_offer_a_pointless_retry():
    """The same dead credentials fail identically, so a retry button would lie."""
    assert GUIDANCE[FailureCategory.AUTH].can_retry is False


# --- what each GitHub failure records ---------------------------------------


@pytest.mark.parametrize(
    ("status", "headers", "expected_status", "category"),
    [
        (401, None, 401, FailureCategory.AUTH),
        (403, None, 401, FailureCategory.AUTH),
        (404, None, 404, FailureCategory.NOT_FOUND),
        (500, None, 502, FailureCategory.UPSTREAM),
        (502, None, 502, FailureCategory.UPSTREAM),
    ],
)
def test_github_failures_record_their_category(
    api_db, status, headers, expected_status, category
):
    client = ingesting(api_db, responds(status, headers))

    assert ingest(client).status_code == expected_status

    source = stored(api_db)
    assert source.status is SyncStatus.FAILED
    assert source.last_error_code == category.value


def test_an_exhausted_rate_limit_is_not_reported_as_a_dead_token(api_db):
    """GitHub answers an exhausted limit with 403 as well. Sending the reader to
    a sign-in screen that fixes nothing is the mistake this guards."""
    client = ingesting(
        api_db,
        responds(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "99999999999"}),
    )

    assert ingest(client).status_code == 429

    assert stored(api_db).last_error_code == FailureCategory.RATE_LIMIT.value


def test_a_graph_outage_is_recorded_against_the_source(api_db):
    class BrokenDriver:
        def session(self):
            raise ServiceUnavailable("no graph")

    client = ingesting(api_db, ok_repo)
    app.dependency_overrides[get_neo4j] = BrokenDriver

    assert ingest(client).status_code == 503

    assert stored(api_db).last_error_code == FailureCategory.GRAPH.value


# --- the endpoint -----------------------------------------------------------


def test_a_failed_source_is_reported_to_the_workspace(api_db):
    """AC1: a connected source that failed to ingest produces a notice."""
    client = ingesting(api_db, responds(401))
    ingest(client)

    (failure,) = client.get(FAILURES_URL).json()

    assert failure["repo"] == TEST_REPO
    assert failure["category"] == "AUTH"
    assert failure["label"] == "Authorization expired"
    assert "Sign in to GitHub again" in failure["advice"]


def test_an_expired_authorization_offers_a_re_auth(api_db):
    """AC2: opening an authorization failure offers the sign-in flow."""
    client = ingesting(api_db, responds(401))
    ingest(client)

    (failure,) = client.get(FAILURES_URL).json()

    assert failure["needs_reauth"] is True
    assert failure["can_retry"] is False


def test_a_rate_limit_offers_a_retry_and_no_re_auth(api_db):
    client = ingesting(
        api_db,
        responds(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "99999999999"}),
    )
    ingest(client)

    (failure,) = client.get(FAILURES_URL).json()

    assert (failure["needs_reauth"], failure["can_retry"]) == (False, True)


def test_a_successful_sync_clears_the_notice(api_db):
    """AC3: nothing has to dismiss the notification -- the row stops failing."""
    client = ingesting(api_db, responds(401))
    ingest(client)
    assert len(client.get(FAILURES_URL).json()) == 1

    app.dependency_overrides[get_github_client] = lambda: GitHubClient(
        transport=httpx.MockTransport(ok_repo), sleep=lambda s: None
    )
    assert ingest(client).status_code == 200

    assert client.get(FAILURES_URL).json() == []
    source = stored(api_db)
    assert (source.last_error, source.last_error_code) == (None, None)


def test_a_failing_source_still_reports_its_last_successful_sync(api_db):
    """AC4: the graph is still showing that sync's data, and how old it is matters."""
    client = ingesting(api_db, ok_repo)
    assert ingest(client).status_code == 200

    app.dependency_overrides[get_github_client] = lambda: GitHubClient(
        transport=httpx.MockTransport(responds(500)), sleep=lambda s: None
    )
    ingest(client)

    (failure,) = client.get(FAILURES_URL).json()
    assert failure["last_synced_at"] is not None
    assert failure["last_synced_by_name"] == "member"


def test_a_source_that_never_succeeded_reports_no_sync_time(api_db):
    client = ingesting(api_db, responds(401))
    ingest(client)

    (failure,) = client.get(FAILURES_URL).json()

    assert failure["last_synced_at"] is None
    assert failure["last_attempted_at"] is not None


def test_a_healthy_workspace_has_nothing_to_report(api_db):
    client = ingesting(api_db, ok_repo)
    ingest(client)

    assert client.get(FAILURES_URL).json() == []


@pytest.mark.parametrize("role", [Role.OWNER, Role.EDITOR, Role.VIEWER])
def test_every_member_can_see_what_is_broken(api_db, role):
    """A VIEWER cannot fix a source, but being told the graph is stale is the point."""
    client = ingesting(api_db, responds(401), role=role)
    if role is Role.VIEWER:
        _, sessions = api_db
        with sessions() as session:
            session.add(failed_source())
            session.commit()
    else:
        ingest(client)

    response = client.get(FAILURES_URL)

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_a_non_member_is_refused(api_db):
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, None)

    assert client.get(FAILURES_URL).status_code == 403


def test_one_workspace_never_sees_another_workspaces_failures(api_db):
    client = ingesting(api_db, responds(401))
    ingest(client)

    _, sessions = api_db
    with sessions() as session:
        other = make_workspace(session, "Other", "ccccccc0-0000-4000-8000-00000000c0df")
        make_user(session, "outsider@example.com")
        session.add(
            failed_source(
                workspace_id=other.id,
                external_ref="other/repo",
                category=FailureCategory.GRAPH,
            )
        )
        session.commit()

    repos = [failure["repo"] for failure in client.get(FAILURES_URL).json()]
    assert repos == [TEST_REPO]


def test_the_newest_failure_is_listed_first(api_db):
    """A failure list is a queue, not an inventory: the thing that just broke is
    what the reader came for."""
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.OWNER)
    with sessions() as session:
        for ref, minutes in (("a/old", 30), ("b/new", 1)):
            session.add(
                failed_source(external_ref=ref, attempted_minutes_ago=minutes)
            )
        session.commit()

    assert [f["repo"] for f in client.get(FAILURES_URL).json()] == ["b/new", "a/old"]


def test_a_pending_source_is_not_a_failure(api_db):
    """An ingestion that is still running is not something to alert about."""
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.OWNER)
    with sessions() as session:
        session.add(
            DataSource(
                workspace_id=WS,
                kind="github",
                external_ref=TEST_REPO,
                status=SyncStatus.PENDING,
                last_attempted_at=dt.datetime.now(dt.timezone.utc),
            )
        )
        session.commit()
        assert list_unresolved_failures(session, WS) == []

    assert client.get(FAILURES_URL).json() == []
