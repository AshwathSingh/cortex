"""T-14.5: unit tests for the bulk graph fetch endpoint.

Neo4j is faked; the relational half is real (in-memory), so `get_current_user`
and `load_workspace_for_user` genuinely run and the 401/403 cases are real.
"""

import pytest

from app.api.graph import get_neo4j
from app.main import app
from app.models import Role
from tests.authz import sign_in_with_role
from tests.payloads import TEST_WORKSPACE_ID
from tests.test_graph_queries import FakeDriver, author, edge, issue, pull_request

URL = f"/api/workspaces/{TEST_WORKSPACE_ID}/graph"


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.pop(get_neo4j, None)


def setup(api_db, nodes=(), edges=(), role=Role.OWNER, driver=None):
    client, sessions = api_db
    driver = driver if driver is not None else FakeDriver(nodes, edges)
    app.dependency_overrides[get_neo4j] = lambda: driver
    if role is not None:
        sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, role)
    return client, driver


# --------------------------------------------------------------------------
# Authorisation
# --------------------------------------------------------------------------


def test_unauthenticated_401_and_no_graph_read(api_db):
    c, driver = setup(api_db, nodes=[author(1)], role=None)
    assert c.get(URL).status_code == 401
    assert driver.opened == 0


def test_non_member_403_and_no_graph_read(api_db):
    c, driver = setup(api_db, nodes=[author(1)], role=None)
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, None)
    r = c.get(URL)
    assert r.status_code == 403
    assert driver.opened == 0


def test_unknown_workspace_403_not_404(api_db):
    """Same 403 as a forbidden one, so workspace existence stays hidden."""
    c, driver = setup(api_db, nodes=[author(1)])
    r = c.get("/api/workspaces/ccccccc0-0000-4000-8000-0000deadbeef/graph")
    assert r.status_code == 403
    assert r.json()["detail"] == "You do not have access to this workspace"
    assert driver.opened == 0


@pytest.mark.parametrize("role", [Role.OWNER, Role.EDITOR, Role.VIEWER])
def test_every_role_including_viewer_can_read_the_graph(api_db, role):
    """Reading is not a write -- a VIEWER is meant to see the graph."""
    c, _ = setup(api_db, nodes=[author(1)], role=role)
    assert c.get(URL).status_code == 200


def test_malformed_workspace_id_422(api_db):
    c, driver = setup(api_db, nodes=[author(1)])
    assert c.get("/api/workspaces/not-a-uuid/graph").status_code == 422
    assert driver.opened == 0


# --------------------------------------------------------------------------
# Payload
# --------------------------------------------------------------------------


def test_returns_nodes_and_edges(api_db):
    a, pr, iss = author(1), pull_request(100), issue(200)
    c, _ = setup(api_db, nodes=[a, pr, iss], edges=[edge(a, pr), edge(a, iss)])
    body = c.get(URL).json()

    assert body["workspace_id"] == TEST_WORKSPACE_ID
    assert [n["key"] for n in body["nodes"]] == ["Author:1", "PullRequest:100", "Issue:200"]
    assert body["edges"] == [
        {"source": "Author:1", "target": "PullRequest:100", "type": "AUTHORED"},
        {"source": "Author:1", "target": "Issue:200", "type": "AUTHORED"},
    ]
    assert body["truncated"] is False


def test_type_filters_are_forwarded_to_the_workspace_scoped_graph_query(api_db):
    a, pr, iss = author(1), pull_request(100), issue(200)
    c, driver = setup(
        api_db,
        nodes=[a, pr, iss],
        edges=[edge(a, pr), edge(pr, iss)],
    )

    body = c.get(URL, params=[("types", "PullRequest"), ("types", "Issue")]).json()

    assert [node["type"] for node in body["nodes"]] == ["PullRequest", "Issue"]
    assert body["edges"] == [
        {"source": "PullRequest:100", "target": "Issue:200", "type": "AUTHORED"}
    ]
    assert all(
        call[1]["node_types"] == ["PullRequest", "Issue"]
        for call in driver.tx.calls
    )


def test_keyword_search_is_forwarded_and_returns_matching_artifacts(api_db):
    pr = pull_request(100)
    pr["props"]["title"] = "Graph Search endpoint"
    unrelated = issue(200)
    c, driver = setup(api_db, nodes=[pr, unrelated])

    response = c.get(URL, params={"q": "search"})

    assert response.status_code == 200
    assert [node["key"] for node in response.json()["nodes"]] == ["PullRequest:100"]
    assert all(call[1]["search_term"] == "search" for call in driver.tx.calls)


def test_keyword_search_with_no_matches_returns_an_empty_graph(api_db):
    c, _ = setup(api_db, nodes=[author(1)])

    response = c.get(URL, params={"q": "nothing-matches"})

    assert response.status_code == 200
    assert response.json()["nodes"] == []
    assert response.json()["edges"] == []


def test_search_query_is_length_limited(api_db):
    c, driver = setup(api_db, nodes=[author(1)])

    assert c.get(URL, params={"q": "x" * 201}).status_code == 422
    assert driver.opened == 0


def test_unknown_type_filter_is_rejected(api_db):
    c, driver = setup(api_db, nodes=[author(1)])
    assert c.get(URL, params={"types": "Requirement"}).status_code == 422
    assert driver.opened == 0


def test_empty_type_filter_returns_no_graph_items(api_db):
    c, driver = setup(api_db, nodes=[author(1)])

    response = c.get(URL, params={"types": ""})

    assert response.status_code == 200
    assert response.json()["nodes"] == []
    assert response.json()["edges"] == []
    assert all(call[1]["node_types"] == [] for call in driver.tx.calls)


def test_node_types_are_exposed_for_colouring(api_db):
    """The canvas colours by type; only the three ingested labels exist today."""
    c, _ = setup(api_db, nodes=[author(1), pull_request(100), issue(200)])
    types = {n["type"] for n in c.get(URL).json()["nodes"]}
    assert types == {"Author", "PullRequest", "Issue"}


def test_empty_workspace_returns_empty_graph_not_404(api_db):
    c, _ = setup(api_db)
    body = c.get(URL).json()
    assert body["nodes"] == [] and body["edges"] == []


def test_limits_are_accepted_and_reported(api_db):
    c, _ = setup(api_db, nodes=[author(1), author(2)])
    body = c.get(URL, params={"node_limit": 2}).json()
    assert body["truncated"] is True


@pytest.mark.parametrize("params", [{"node_limit": 0}, {"edge_limit": 0}, {"node_limit": 99999}])
def test_out_of_range_limits_422(api_db, params):
    c, _ = setup(api_db, nodes=[author(1)])
    assert c.get(URL, params=params).status_code == 422


def test_neo4j_down_503(api_db):
    from neo4j.exceptions import ServiceUnavailable

    class DownDriver:
        opened = 0

        def session(self):
            raise ServiceUnavailable("down")

    c, _ = setup(api_db, driver=DownDriver())
    assert c.get(URL).status_code == 503
