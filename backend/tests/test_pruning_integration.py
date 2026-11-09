"""US-28 integration: mock GitHub -> real ingestion -> real Neo4j -> /flags.

The rules are tested in isolation elsewhere. What only a real database can show
is whether the Cypher finds the right items, whether the author join is actually
optional, and whether the properties the mapper writes come back in a shape the
rules can read -- the dates in particular, which are ISO strings in Neo4j and
have to become real datetimes before any threshold means anything.

Skipped automatically when Neo4j isn't running. Only reserved-workspace data is
touched.
"""

import httpx
import pytest

from app.api.ingest import get_github_client
from app.github.client import GitHubClient
from app.main import app
from app.models import Role
from tests.authz import authenticate, grant, make_user, make_workspace
from tests.payloads import (
    TEST_REPO_URL,
    TEST_WORKSPACE_ID,
    TEST_WORKSPACE_ID_B,
    issue,
    pull_request,
    user,
)

pytestmark = pytest.mark.integration

ALICE = user(1, "alice")
INGEST_URL = "/api/ingest/github"
FLAGS_URL = f"/api/workspaces/{TEST_WORKSPACE_ID}/flags"
# The payload factories date everything to 2024, which is years before any
# plausible test run, so every open item they produce is stale by design.
LONG_AGO = "2024-02-01T00:00:00Z"
GOOD_BODY = "A description long enough to count as evidence of something."


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


def serve(prs, issues):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/pulls"):
            return httpx.Response(200, json=prs)
        if path.endswith("/issues"):
            return httpx.Response(200, json=issues)
        return httpx.Response(404)

    app.dependency_overrides[get_github_client] = lambda: GitHubClient(
        transport=httpx.MockTransport(handler), sleep=lambda s: None
    )


def ingest(client, workspace_id=TEST_WORKSPACE_ID):
    return client.post(
        INGEST_URL, json={"repo_url": TEST_REPO_URL, "workspace_id": workspace_id}
    )


def flags(client, url: str = FLAGS_URL):
    response = client.get(url)
    assert response.status_code == 200, response.text
    return response.json()["flags"]


def rules_for(client, key: str) -> set[str]:
    return {
        flag["rule"]
        for flag in flags(client)
        if any(target["key"] == key for target in flag["targets"])
    }


def test_an_ingested_open_issue_is_flagged_as_out_of_date(client, graph):
    """The whole path: ISO dates written by the mapper come back and get
    compared against a real clock."""
    stale = issue(1, ALICE, body=GOOD_BODY, updated_at=LONG_AGO)
    serve([], [stale])
    assert ingest(client).status_code == 200

    (flag,) = [f for f in flags(client) if f["rule"] == "STALE"]

    assert flag["targets"][0]["key"] == f"Issue:{stale['id']}"
    assert flag["severity"] == "HIGH"
    assert "years" in flag["summary"]


def test_an_issue_with_no_description_is_flagged_as_thin(client, graph):
    serve([], [issue(2, ALICE, body=None, updated_at=LONG_AGO)])
    ingest(client)

    rules = rules_for(client, f"Issue:{issue(2, ALICE)['id']}")

    assert "THIN" in rules


def test_an_item_whose_author_github_dropped_has_no_author_in_the_graph(client, graph):
    """GitHub returns no user for an item whose account is gone, so the mapper
    writes no AUTHORED edge -- and the OPTIONAL MATCH has to survive that."""
    orphan = issue(3, None, body=GOOD_BODY, updated_at=LONG_AGO)
    serve([], [orphan])
    ingest(client)

    (thin,) = [
        flag
        for flag in flags(client)
        if flag["rule"] == "THIN"
        and flag["targets"][0]["key"] == f"Issue:{orphan['id']}"
    ]

    assert "nobody to ask" in thin["summary"]
    evidence = {item["label"]: item["detail"] for item in thin["evidence"]}
    assert evidence["Author"] == "no author is recorded in the graph"


def test_an_authored_item_is_not_reported_as_unattributed(client, graph):
    serve([], [issue(4, ALICE, body=GOOD_BODY, updated_at=LONG_AGO)])
    ingest(client)

    (stale,) = [f for f in flags(client) if f["rule"] == "STALE"]

    evidence = {item["label"]: item["detail"] for item in stale["evidence"]}
    assert evidence["Author"] == "alice"
    assert [f for f in flags(client) if f["rule"] == "THIN"] == []


def test_a_merged_pull_request_and_an_open_issue_of_the_same_name_contradict(
    client, graph
):
    merged = pull_request(5, ALICE, title="Fix the login redirect", body=GOOD_BODY)
    open_issue = issue(6, ALICE, title="fix login redirect", body=GOOD_BODY,
                       updated_at=LONG_AGO)
    serve([merged], [open_issue])
    ingest(client)

    (flag,) = [f for f in flags(client) if f["rule"] == "CONTRADICTED"]

    assert {target["key"] for target in flag["targets"]} == {
        f"PullRequest:{merged['id']}",
        f"Issue:{open_issue['id']}",
    }
    assert flag["severity"] == "HIGH"
    assert "merged" in flag["summary"]


def test_a_closed_issue_raises_nothing(client, graph):
    """Finished work is not a review item."""
    serve([], [issue(7, ALICE, state="closed", closed_at=LONG_AGO, body=None,
                     updated_at=LONG_AGO)])
    ingest(client)

    assert flags(client) == []


def test_pull_requests_and_issues_are_both_considered(client, graph):
    serve(
        [pull_request(8, ALICE, title="Unique pull request work", state="open",
                      closed_at=None, merged_at=None, body=None,
                      updated_at=LONG_AGO)],
        [issue(9, ALICE, title="Unique issue work", body=None, updated_at=LONG_AGO)],
    )
    ingest(client)

    types = {
        target["type"]
        for flag in flags(client)
        for target in flag["targets"]
    }
    assert types == {"PullRequest", "Issue"}


def test_one_workspace_never_sees_another_workspaces_flags(client, graph):
    """AC3 is about every member of *this* workspace, not every workspace."""
    serve([], [issue(10, ALICE, body=None, updated_at=LONG_AGO)])
    ingest(client, TEST_WORKSPACE_ID)

    other = f"/api/workspaces/{TEST_WORKSPACE_ID_B}/flags"

    assert flags(client) != []
    assert flags(client, other) == []


def test_the_same_repo_in_two_workspaces_is_flagged_in_each(client, graph):
    serve([], [issue(11, ALICE, body=None, updated_at=LONG_AGO)])
    ingest(client, TEST_WORKSPACE_ID)
    ingest(client, TEST_WORKSPACE_ID_B)

    other = f"/api/workspaces/{TEST_WORKSPACE_ID_B}/flags"

    assert len(flags(client)) == len(flags(client, other)) == 2  # stale + thin


def test_a_re_ingestion_that_fixes_an_item_clears_its_flag(client, graph):
    """Nothing is stored, so a flag is only ever as old as the data it describes."""
    serve([], [issue(12, ALICE, body=None, updated_at=LONG_AGO)])
    ingest(client)
    assert "THIN" in rules_for(client, f"Issue:{issue(12, ALICE)['id']}")

    serve([], [issue(12, ALICE, body=GOOD_BODY, updated_at=LONG_AGO)])
    ingest(client)

    assert "THIN" not in rules_for(client, f"Issue:{issue(12, ALICE)['id']}")


def test_an_empty_workspace_has_an_empty_queue(client, graph):
    serve([], [])
    ingest(client)

    assert flags(client) == []
