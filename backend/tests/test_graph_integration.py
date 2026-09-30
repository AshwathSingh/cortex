"""US-14 integration tests: ingest -> real Neo4j -> graph endpoint.

Only GitHub is mocked. Proves the acceptance criterion that opening a workspace
shows *only* that workspace's nodes, against the real database rather than a fake.
Skipped automatically when Neo4j isn't running.
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

ALICE, BOB = user(1, "alice"), user(2, "bob")
INGEST = "/api/ingest/github"


def graph_url(workspace_id: str) -> str:
    return f"/api/workspaces/{workspace_id}/graph"


@pytest.fixture
def client(api_db):
    """A caller holding OWNER on both reserved test workspaces."""
    test_client, sessions = api_db
    with sessions() as session:
        owner = make_user(session, "graph-owner@example.com")
        for ws_id, name in (
            (TEST_WORKSPACE_ID, "Primary"),
            (TEST_WORKSPACE_ID_B, "Secondary"),
        ):
            grant(session, make_workspace(session, name, ws_id), owner, Role.OWNER)
        session.commit()
        session.refresh(owner)
    authenticate(test_client, sessions, owner)
    return test_client


@pytest.fixture(autouse=True)
def _reset_github_override():
    yield
    app.dependency_overrides.pop(get_github_client, None)


def use_github(prs, issues):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pulls"):
            return httpx.Response(200, json=prs)
        if request.url.path.endswith("/issues"):
            return httpx.Response(200, json=issues)
        return httpx.Response(404)

    github = GitHubClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)
    app.dependency_overrides[get_github_client] = lambda: github


def ingest_into(client, workspace_id: str):
    return client.post(
        INGEST, json={"repo_url": TEST_REPO_URL, "workspace_id": workspace_id}
    )


def test_ingested_data_renders_as_nodes_and_edges(graph, client):
    """AC: a workspace with ingested data returns distinct nodes and connected edges."""
    use_github([pull_request(1, ALICE)], [issue(2, BOB)])
    assert ingest_into(client, TEST_WORKSPACE_ID).status_code == 200

    body = client.get(graph_url(TEST_WORKSPACE_ID)).json()

    types = sorted(n["type"] for n in body["nodes"])
    assert types == ["Author", "Author", "Issue", "PullRequest"]
    assert len(body["edges"]) == 2
    assert all(e["type"] == "AUTHORED" for e in body["edges"])

    # Every edge endpoint must resolve to a returned node -- no dangling keys.
    keys = {n["key"] for n in body["nodes"]}
    for e in body["edges"]:
        assert e["source"] in keys and e["target"] in keys


def test_workspace_sees_only_its_own_nodes(graph, client):
    """AC: opening a workspace shows nodes only associated with that workspace."""
    use_github([pull_request(1, ALICE)], [issue(2, BOB)])
    assert ingest_into(client, TEST_WORKSPACE_ID).status_code == 200

    primary = client.get(graph_url(TEST_WORKSPACE_ID)).json()
    secondary = client.get(graph_url(TEST_WORKSPACE_ID_B)).json()

    assert len(primary["nodes"]) == 4
    assert secondary["nodes"] == [] and secondary["edges"] == []


def test_same_repo_in_two_workspaces_yields_two_independent_graphs(graph, client):
    """The same GitHub ids must not bleed between workspaces."""
    use_github([pull_request(1, ALICE)], [issue(2, ALICE)])
    assert ingest_into(client, TEST_WORKSPACE_ID).status_code == 200
    assert ingest_into(client, TEST_WORKSPACE_ID_B).status_code == 200

    primary = client.get(graph_url(TEST_WORKSPACE_ID)).json()
    secondary = client.get(graph_url(TEST_WORKSPACE_ID_B)).json()

    assert len(primary["nodes"]) == len(secondary["nodes"]) == 3
    assert len(primary["edges"]) == len(secondary["edges"]) == 2
    # Identical keys on both sides: same GitHub ids, separate nodes underneath.
    assert {n["key"] for n in primary["nodes"]} == {n["key"] for n in secondary["nodes"]}


def test_isolated_node_is_returned(graph, client):
    """An issue with a deleted author has no edge but still belongs on the canvas."""
    use_github([], [issue(1, None)])
    assert ingest_into(client, TEST_WORKSPACE_ID).status_code == 200

    body = client.get(graph_url(TEST_WORKSPACE_ID)).json()
    assert len(body["nodes"]) == 1 and body["nodes"][0]["type"] == "Issue"
    assert body["edges"] == []


def test_empty_workspace_returns_an_empty_graph(graph, client):
    body = client.get(graph_url(TEST_WORKSPACE_ID)).json()
    assert body == {
        "workspace_id": TEST_WORKSPACE_ID,
        "nodes": [],
        "edges": [],
        "truncated": False,
    }


def test_node_carries_provenance_and_display_fields(graph, client):
    pr = pull_request(1, ALICE)
    use_github([pr], [])
    assert ingest_into(client, TEST_WORKSPACE_ID).status_code == 200

    nodes = client.get(graph_url(TEST_WORKSPACE_ID)).json()["nodes"]
    pr_node = next(n for n in nodes if n["type"] == "PullRequest")
    assert pr_node["id"] == pr["id"]
    assert pr_node["number"] == 1
    assert pr_node["title"].startswith("#1 ")
    assert pr_node["url"] == pr["html_url"]  # link back to GitHub
    assert pr_node["state"] == "closed"

    author_node = next(n for n in nodes if n["type"] == "Author")
    assert author_node["title"] == "alice"
