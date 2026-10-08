"""T-7.5 endpoint behaviour, including the workspace authorisation gate.

GitHub and Neo4j are faked; the relational half is real (in-memory), so
`get_current_user` and `load_workspace_for_user` genuinely run.
"""

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.api.ingest import get_github_client, get_neo4j
from app.github.client import GitHubClient
from app.main import app
from app.models import DataSource, Role, SyncStatus, User
from tests.authz import sign_in_with_role
from tests.payloads import TEST_WORKSPACE_ID

USER = {"id": 7, "login": "octocat"}
PR = {"id": 100, "number": 1, "title": "Add", "state": "open", "html_url": "u",
      "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-01T00:00:00Z", "user": USER}
ISSUE = {**PR, "id": 200, "number": 2}
URL = "/api/ingest/github"


class FakeTx:
    def __init__(self):
        self.calls = []

    def run(self, cypher, **params):
        self.calls.append(cypher)


class FakeSession:
    def __init__(self, driver):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute_write(self, fn):
        if self.driver.error:
            raise self.driver.error
        fn(self.driver.tx)


class FakeDriver:
    def __init__(self, error=None):
        self.tx = FakeTx()
        self.error = error
        self.sessions = 0

    def session(self):
        self.sessions += 1
        return FakeSession(self)


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.pop(get_github_client, None)
    app.dependency_overrides.pop(get_neo4j, None)


def setup(api_db, handler, driver=None, role=Role.OWNER):
    """Wire fake GitHub + Neo4j, and sign a caller in with ``role``."""
    client, sessions = api_db
    driver = driver or FakeDriver()
    github = GitHubClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)
    app.dependency_overrides[get_github_client] = lambda: github
    app.dependency_overrides[get_neo4j] = lambda: driver
    if role is not None:
        sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, role)
    return client, driver


def body(**over) -> dict:
    return {"repo_url": "https://github.com/o/r", "workspace_id": TEST_WORKSPACE_ID, **over}


def ok_handler(request):
    if request.url.path.endswith("/pulls"):
        return httpx.Response(200, json=[PR])
    return httpx.Response(200, json=[ISSUE, {**ISSUE, "id": 300, "pull_request": {}}])


def never_called(request):
    raise AssertionError("GitHub must not be called")


def test_health():
    from fastapi.testclient import TestClient

    assert TestClient(app).get("/health").json() == {"status": "ok"}


# --------------------------------------------------------------------------
# Authorisation gate
# --------------------------------------------------------------------------


def test_unauthenticated_caller_401_and_no_github_call(api_db):
    c, driver = setup(api_db, never_called, role=None)
    r = c.post(URL, json=body())
    assert r.status_code == 401
    assert driver.sessions == 0


def test_non_member_403_and_no_github_call(api_db):
    """Authorisation runs before any network call, so it cannot be used to probe GitHub."""
    c, driver = setup(api_db, never_called, role=None)
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, None)  # workspace exists, no membership
    r = c.post(URL, json=body())
    assert r.status_code == 403
    assert driver.sessions == 0


def test_viewer_cannot_ingest(api_db):
    """Ingestion writes nodes, so a read-only role must be refused."""
    c, driver = setup(api_db, never_called, role=Role.VIEWER)
    r = c.post(URL, json=body())
    assert r.status_code == 403
    assert "OWNER or EDITOR" in r.json()["detail"]
    assert driver.sessions == 0


@pytest.mark.parametrize("role", [Role.OWNER, Role.EDITOR])
def test_writer_roles_can_ingest(api_db, role):
    c, _ = setup(api_db, ok_handler, role=role)
    assert c.post(URL, json=body()).status_code == 200


def test_unknown_workspace_403_like_a_forbidden_one(api_db):
    """Same 403 either way, so nobody can discover which workspaces exist."""
    c, driver = setup(api_db, never_called, role=Role.OWNER)
    r = c.post(URL, json=body(workspace_id="ccccccc0-0000-4000-8000-0000deadbeef"))
    assert r.status_code == 403
    assert r.json()["detail"] == "You do not have access to this workspace"
    assert driver.sessions == 0


# --------------------------------------------------------------------------
# Request validation
# --------------------------------------------------------------------------


def test_missing_workspace_id_422(api_db):
    c, driver = setup(api_db, never_called)
    r = c.post(URL, json={"repo_url": "https://github.com/o/r"})
    assert r.status_code == 422
    assert driver.sessions == 0


@pytest.mark.parametrize("bad", [None, "", "not-a-uuid", "o/r", 7])
def test_malformed_workspace_id_422(api_db, bad):
    c, driver = setup(api_db, never_called)
    r = c.post(URL, json=body(workspace_id=bad))
    assert r.status_code == 422
    assert driver.sessions == 0


# --------------------------------------------------------------------------
# Pipeline behaviour
# --------------------------------------------------------------------------


def test_valid_repo_ingests(api_db):
    c, driver = setup(api_db, ok_handler)
    r = c.post(URL, json=body())
    assert r.status_code == 200
    assert r.json() == {"repo": "o/r", "pull_requests": 1, "issues": 1}
    assert len(driver.tx.calls) == 4


def test_empty_repo_is_still_recorded(api_db):
    c, driver = setup(api_db, lambda request: httpx.Response(200, json=[]))

    r = c.post(URL, json=body())

    assert r.status_code == 200
    assert r.json() == {"repo": "o/r", "pull_requests": 0, "issues": 0}
    assert len(driver.tx.calls) == 1


@pytest.mark.parametrize("url", ["", "not a url", "https://gitlab.com/a/b", "https://github.com/only"])
def test_invalid_url_422_and_nothing_touched(api_db, url):
    c, driver = setup(api_db, never_called)
    r = c.post(URL, json=body(repo_url=url))
    assert r.status_code == 422
    assert driver.sessions == 0


def test_missing_body_field_422(api_db):
    c, _ = setup(api_db, ok_handler)
    assert c.post(URL, json={}).status_code == 422


def test_repo_not_found_404_no_writes(api_db):
    c, driver = setup(api_db, lambda r: httpx.Response(404))
    assert c.post(URL, json=body()).status_code == 404
    assert driver.sessions == 0


def test_rate_limit_429_with_retry_after(api_db):
    c, driver = setup(api_db, lambda r: httpx.Response(429, headers={"Retry-After": "5000"}))
    r = c.post(URL, json=body())
    assert r.status_code == 429 and r.headers["Retry-After"] == "5000"
    assert driver.sessions == 0


def test_github_server_error_502(api_db):
    c, driver = setup(api_db, lambda r: httpx.Response(500))
    assert c.post(URL, json=body()).status_code == 502
    assert driver.sessions == 0


def test_malformed_payload_502_no_writes(api_db):
    c, driver = setup(api_db, lambda r: httpx.Response(200, json=[{"id": "bad"}]))
    assert c.post(URL, json=body()).status_code == 502
    assert driver.sessions == 0


def test_neo4j_down_503(api_db):
    from neo4j.exceptions import ServiceUnavailable

    c, _ = setup(api_db, ok_handler, FakeDriver(error=ServiceUnavailable("down")))
    assert c.post(URL, json=body()).status_code == 503


# --------------------------------------------------------------------------
# Sync state (US-10, T-10.1)
#
# A failed ingestion writes nothing to the graph -- every failure path raises
# before write_graph, and write_graph is all-or-nothing -- so these rows are the
# only record that a source was ever connected, and the only thing that can
# render a red "Needs attention" against it.
# --------------------------------------------------------------------------


def recorded(sessions, workspace_id=TEST_WORKSPACE_ID) -> list[DataSource]:
    with sessions() as session:
        return list(
            session.scalars(
                select(DataSource)
                .where(DataSource.workspace_id == uuid.UUID(workspace_id))
                .order_by(DataSource.external_ref)
            )
        )


def test_successful_ingest_records_who_synced_the_source(api_db):
    c, _ = setup(api_db, ok_handler)
    _, sessions = api_db

    assert c.post(URL, json=body()).status_code == 200

    (source,) = recorded(sessions)
    assert (source.kind, source.external_ref) == ("github", "o/r")
    assert source.status is SyncStatus.SUCCESS
    assert source.last_synced_at is not None
    assert source.last_error is None
    with sessions() as session:
        assert source.last_synced_by == session.scalar(select(User.id))


def test_source_is_pending_while_github_is_being_read(api_db):
    """The attempt is committed before the fetch starts: ingestion is
    synchronous and a large repository takes minutes, so the Sources page has to
    be able to show "Syncing…" meanwhile."""
    _, sessions = api_db
    during: list[list[SyncStatus]] = []

    def handler(request):
        during.append([s.status for s in recorded(sessions)])
        return httpx.Response(200, json=[])

    c, _ = setup(api_db, handler)

    assert c.post(URL, json=body()).status_code == 200
    assert during[0] == [SyncStatus.PENDING]
    assert [s.status for s in recorded(sessions)] == [SyncStatus.SUCCESS]


@pytest.mark.parametrize(
    "handler, status_code, detail",
    [
        (lambda r: httpx.Response(404), 404, "not found or not accessible"),
        (
            lambda r: httpx.Response(429, headers={"Retry-After": "5000"}),
            429,
            "rate limit",
        ),
        (lambda r: httpx.Response(500), 502, ""),
        (lambda r: httpx.Response(200, json=[{"id": "bad"}]), 502, "payload shape"),
    ],
)
def test_a_failed_ingest_records_the_source_as_failed(
    api_db, handler, status_code, detail
):
    c, _ = setup(api_db, handler)
    _, sessions = api_db

    assert c.post(URL, json=body()).status_code == status_code

    (source,) = recorded(sessions)
    assert source.status is SyncStatus.FAILED
    assert detail in (source.last_error or "")
    assert source.last_attempted_at is not None
    # Never synced, so there is no timestamp to claim.
    assert source.last_synced_at is None


def test_an_unavailable_graph_records_the_source_as_failed(api_db):
    from neo4j.exceptions import ServiceUnavailable

    c, _ = setup(api_db, ok_handler, FakeDriver(error=ServiceUnavailable("down")))
    _, sessions = api_db

    assert c.post(URL, json=body()).status_code == 503

    (source,) = recorded(sessions)
    assert source.status is SyncStatus.FAILED
    assert source.last_error == "Graph database unavailable"


def test_a_later_failure_keeps_the_earlier_success(api_db):
    """Succeeded, then failed: the source must show both the failure and the
    real age of the data still in the graph."""
    c, _ = setup(api_db, ok_handler)
    _, sessions = api_db
    assert c.post(URL, json=body()).status_code == 200
    synced_at = recorded(sessions)[0].last_synced_at

    app.dependency_overrides[get_github_client] = lambda: GitHubClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(404)),
        sleep=lambda s: None,
    )
    assert c.post(URL, json=body()).status_code == 404

    (source,) = recorded(sessions)
    assert source.status is SyncStatus.FAILED
    assert source.last_synced_at == synced_at


def test_re_ingesting_the_same_repo_updates_one_row(api_db):
    c, _ = setup(api_db, ok_handler)
    _, sessions = api_db

    c.post(URL, json=body())
    c.post(URL, json=body())

    assert len(recorded(sessions)) == 1


@pytest.mark.parametrize("url", ["", "not a url", "https://gitlab.com/a/b"])
def test_an_unparseable_url_records_nothing(api_db, url):
    """A 422 means no real source was identified, so there is nothing to record."""
    c, _ = setup(api_db, never_called)
    _, sessions = api_db

    assert c.post(URL, json=body(repo_url=url)).status_code == 422
    assert recorded(sessions) == []


def test_an_unauthorised_caller_records_nothing(api_db):
    c, _ = setup(api_db, never_called, role=Role.VIEWER)
    _, sessions = api_db

    assert c.post(URL, json=body()).status_code == 403
    assert recorded(sessions) == []
