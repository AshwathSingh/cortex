"""T-12.4: what a re-ingestion does to the nodes the previous one left behind.

US-12's story is "re-authenticate or fix the data source" -- which ends in a
re-sync, so the re-sync has to be clean. MERGE already stops a second copy of
anything the new run writes; these tests are about everything it does *not*
write, which is where the duplicates actually came from.

Real Neo4j, because every claim here is about MERGE semantics and DETACH DELETE
and a fake driver that records Cypher strings cannot tell you whether either
worked. Skipped automatically when Neo4j isn't running.
"""

import httpx
import pytest

from app.api.ingest import get_github_client
from app.github.client import GitHubClient
from app.main import app
from app.models import Role
from tests.authz import authenticate, grant, make_user, make_workspace
from tests.payloads import (
    TEST_REPO,
    TEST_REPO_URL,
    TEST_WORKSPACE_ID,
    TEST_WORKSPACE_ID_B,
    issue,
    pull_request,
    user,
)

pytestmark = pytest.mark.integration

ALICE, BOB = user(1, "alice"), user(2, "bob")
URL = "/api/ingest/github"
OTHER_REPO = "cortex-test/other"
OTHER_REPO_URL = "https://github.com/" + OTHER_REPO


@pytest.fixture
def client(api_db):
    """A caller holding OWNER on both reserved test workspaces."""
    test_client, sessions = api_db
    with sessions() as session:
        owner = make_user(session, "owner@example.com")
        for workspace_id, name in (
            (TEST_WORKSPACE_ID, "Primary"),
            (TEST_WORKSPACE_ID_B, "Secondary"),
        ):
            grant(session, make_workspace(session, name, workspace_id), owner, Role.OWNER)
        session.commit()
        session.refresh(owner)
    authenticate(test_client, sessions, owner)
    return test_client


@pytest.fixture(autouse=True)
def _reset_github_override():
    yield
    app.dependency_overrides.pop(get_github_client, None)


def serve(prs, issues, fail_pulls=False):
    """A GitHub whose repository holds exactly ``prs`` and ``issues``."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/pulls"):
            if fail_pulls:
                return httpx.Response(500, json={"message": "boom"})
            return httpx.Response(200, json=prs)
        if path.endswith("/issues"):
            return httpx.Response(200, json=issues)
        return httpx.Response(404)

    app.dependency_overrides[get_github_client] = lambda: GitHubClient(
        transport=httpx.MockTransport(handler), sleep=lambda s: None
    )


def ingest(client, workspace_id=TEST_WORKSPACE_ID, repo_url=TEST_REPO_URL):
    return client.post(URL, json={"repo_url": repo_url, "workspace_id": workspace_id})


def test_re_ingesting_an_unchanged_repo_creates_no_second_copy(graph, client):
    serve([pull_request(1, ALICE)], [issue(2, BOB)])
    ingest(client)
    first = graph.counts()

    ingest(client)

    assert graph.counts() == first == {
        "Author": 2,
        "PullRequest": 1,
        "Issue": 1,
        "AUTHORED": 2,
    }


def test_an_item_deleted_upstream_is_removed_on_re_ingest(graph, client):
    """Without this the graph keeps counting work that no longer exists, and the
    Sources page over-reports how much is indexed."""
    serve([pull_request(1, ALICE), pull_request(2, ALICE)], [])
    ingest(client)
    assert graph.counts()["PullRequest"] == 2

    serve([pull_request(1, ALICE)], [])
    ingest(client)

    assert graph.counts()["PullRequest"] == 1
    assert graph.node("PullRequest", pull_request(2, ALICE)["id"]) is None


def test_an_item_whose_author_changed_has_exactly_one_author(graph, client):
    """MERGE adds the new AUTHORED edge; nothing removed the old one, so the
    pull request showed two authors."""
    serve([pull_request(1, ALICE)], [])
    ingest(client)
    pr_id = pull_request(1, ALICE)["id"]
    assert graph.author_of("PullRequest", pr_id) == ALICE["id"]

    serve([pull_request(1, BOB)], [])
    ingest(client)

    assert graph.counts()["AUTHORED"] == 1
    assert graph.author_of("PullRequest", pr_id) == BOB["id"]


def test_an_item_that_loses_its_author_loses_the_edge(graph, client):
    """GitHub returns no user for an item whose account is gone. Nobody owns it
    any more, so no edge should claim otherwise."""
    serve([], [issue(3, ALICE)])
    ingest(client)
    assert graph.counts()["AUTHORED"] == 1

    serve([], [issue(3, None)])
    ingest(client)

    assert graph.counts()["AUTHORED"] == 0


def test_an_author_with_nothing_left_is_removed(graph, client):
    serve([pull_request(1, ALICE)], [issue(2, BOB)])
    ingest(client)
    assert graph.counts()["Author"] == 2

    serve([pull_request(1, ALICE)], [])
    ingest(client)

    assert graph.counts()["Author"] == 1
    assert graph.node("Author", BOB["id"]) is None


def test_an_author_still_working_elsewhere_survives(graph, client):
    """Authors are shared across a workspace's repositories, so they are only
    collected when they have no authorship left anywhere."""
    serve([pull_request(1, ALICE)], [])
    ingest(client)
    serve([pull_request(9, ALICE)], [])
    ingest(client, repo_url=OTHER_REPO_URL)

    # Alice's work in the first repo disappears; her other repo still has her.
    serve([], [])
    ingest(client)

    assert graph.node("Author", ALICE["id"]) is not None
    assert graph.counts()["PullRequest"] == 1


def test_pruning_does_not_reach_another_repo_in_the_same_workspace(graph, client):
    serve([pull_request(1, ALICE)], [])
    ingest(client)
    serve([pull_request(9, BOB)], [])
    ingest(client, repo_url=OTHER_REPO_URL)
    assert graph.counts()["PullRequest"] == 2

    serve([pull_request(1, ALICE)], [])
    ingest(client)

    assert graph.counts()["PullRequest"] == 2


def test_pruning_does_not_reach_another_workspace(graph, client):
    serve([pull_request(1, ALICE)], [])
    ingest(client)
    ingest(client, workspace_id=TEST_WORKSPACE_ID_B)

    serve([], [])
    ingest(client)

    assert graph.counts(TEST_WORKSPACE_ID)["PullRequest"] == 0
    assert graph.counts(TEST_WORKSPACE_ID_B)["PullRequest"] == 1


def test_a_repo_emptied_upstream_ends_up_empty(graph, client):
    serve([pull_request(1, ALICE)], [issue(2, BOB)])
    ingest(client)

    serve([], [])
    ingest(client)

    assert graph.counts() == {
        "Author": 0,
        "PullRequest": 0,
        "Issue": 0,
        "AUTHORED": 0,
    }


def test_a_failed_re_ingest_deletes_nothing(graph, client):
    """A partial or failed fetch is indistinguishable from items being removed
    upstream. Pruning on the strength of one would delete live data, so the
    whole run is a single transaction."""
    serve([pull_request(1, ALICE)], [issue(2, BOB)])
    ingest(client)
    before = graph.counts()

    serve([], [], fail_pulls=True)
    assert ingest(client).status_code == 502

    assert graph.counts() == before


def test_a_node_written_before_run_markers_existed_is_still_prunable(graph, client):
    """The comparison is coalesced for this: a null ``ingest_run`` compared to
    the current run is null, which is not true, and a pre-upgrade node could
    never be collected."""
    serve([pull_request(1, ALICE), pull_request(2, ALICE)], [])
    ingest(client)
    with graph.driver.session() as session:
        session.run(
            "MATCH (n:PullRequest {workspace_id: $ws}) REMOVE n.ingest_run",
            ws=TEST_WORKSPACE_ID,
        ).consume()

    serve([pull_request(1, ALICE)], [])
    ingest(client)

    assert graph.counts()["PullRequest"] == 1


def test_the_sources_page_reports_the_reduced_count(graph, client):
    serve([pull_request(1, ALICE), pull_request(2, ALICE)], [issue(3, BOB)])
    ingest(client)

    serve([pull_request(1, ALICE)], [])
    ingest(client)

    (source,) = client.get(f"/api/workspaces/{TEST_WORKSPACE_ID}/sources").json()
    assert (source["pull_requests"], source["issues"], source["total_items"]) == (1, 0, 1)
