"""US-15/16 unit tests for workspace-scoped graph detail and provenance reads."""

import pytest

from app.api.graph import get_neo4j
from app.graph.queries import EDGE_DETAILS_QUERY, NODE_DETAILS_QUERY, fetch_edge_details, fetch_node_details
from app.main import app
from app.models import Role
from tests.authz import sign_in_with_role
from tests.payloads import TEST_WORKSPACE_ID


AUTHOR = {
    "labels": ["Author"],
    "props": {"id": 1, "login": "alice", "html_url": "https://github.com/alice", "workspace_id": TEST_WORKSPACE_ID},
}
PULL_REQUEST = {
    "labels": ["PullRequest"],
    "props": {
        "id": 20, "number": 3, "title": "Add graph details", "body": "The full body",
        "html_url": "https://github.com/acme/repo/pull/3", "state": "open",
        "repo": "acme/repo", "workspace_id": TEST_WORKSPACE_ID,
    },
}


class Result:
    def __init__(self, record):
        self.record = record

    def single(self):
        return self.record


class Tx:
    def __init__(self, record=None):
        self.record = record
        self.calls = []

    def run(self, query, **params):
        self.calls.append((query, params))
        return Result(self.record)


class Session:
    def __init__(self, tx):
        self.tx = tx

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute_read(self, callback):
        return callback(self.tx)


class Driver:
    def __init__(self, record=None):
        self.tx = Tx(record)
        self.opened = 0

    def session(self):
        self.opened += 1
        return Session(self.tx)


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.pop(get_neo4j, None)


def test_node_query_traverses_edges_both_directions_and_is_workspace_scoped():
    assert "OPTIONAL MATCH (n)-[r]-(related)" in NODE_DETAILS_QUERY
    assert "related.workspace_id = $workspace_id" in NODE_DETAILS_QUERY
    assert "n.workspace_id = $workspace_id" in NODE_DETAILS_QUERY

    record = {
        "labels": PULL_REQUEST["labels"],
        "props": PULL_REQUEST["props"],
        "connected": [{
            "labels": AUTHOR["labels"], "props": AUTHOR["props"],
            "relationship": "AUTHORED", "direction": "incoming",
        }],
    }
    driver = Driver(record)
    details = fetch_node_details(driver, TEST_WORKSPACE_ID, "PullRequest", 20)

    assert driver.tx.calls[0][1] == {
        "workspace_id": TEST_WORKSPACE_ID, "node_type": "PullRequest", "node_id": 20,
    }
    assert details["title"] == "#3 Add graph details"
    assert details["content"] == "The full body"
    assert "workspace_id" not in details["attributes"]
    assert details["origins"] == [
        {"key": "PullRequest:20", "type": "PullRequest", "title": "#3 Add graph details", "url": PULL_REQUEST["props"]["html_url"]},
        {"key": "Author:1", "type": "Author", "title": "alice", "url": AUTHOR["props"]["html_url"], "relationship": "AUTHORED", "direction": "incoming"},
    ]


def test_edge_query_fetches_both_workspace_endpoints_and_provenance():
    assert "source.workspace_id = $workspace_id" in EDGE_DETAILS_QUERY
    assert "target.workspace_id = $workspace_id" in EDGE_DETAILS_QUERY
    record = {
        "source_labels": AUTHOR["labels"], "source_props": AUTHOR["props"],
        "target_labels": PULL_REQUEST["labels"], "target_props": PULL_REQUEST["props"],
        "type": "AUTHORED", "props": {},
    }
    driver = Driver(record)
    details = fetch_edge_details(
        driver, TEST_WORKSPACE_ID, "Author:1", "PullRequest:20", "AUTHORED"
    )

    params = driver.tx.calls[0][1]
    assert params == {
        "workspace_id": TEST_WORKSPACE_ID,
        "source_type": "Author", "source_id": 1,
        "target_type": "PullRequest", "target_id": 20,
        "edge_type": "AUTHORED",
    }
    assert details["source"]["key"] == "Author:1"
    assert details["target"]["key"] == "PullRequest:20"
    assert details["origins"][0]["url"] == AUTHOR["props"]["html_url"]
    assert details["origins"][1]["url"] == PULL_REQUEST["props"]["html_url"]
    assert details["content"]


def test_invalid_edge_key_is_rejected_before_database_read():
    driver = Driver()
    with pytest.raises(ValueError):
        fetch_edge_details(driver, TEST_WORKSPACE_ID, "Other:1", "Issue:2", "LINKS")
    assert driver.opened == 0


def test_detail_endpoints_require_workspace_membership(api_db):
    client, sessions = api_db
    driver = Driver()
    app.dependency_overrides[get_neo4j] = lambda: driver
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, None)
    response = client.get(
        f"/api/workspaces/{TEST_WORKSPACE_ID}/graph/nodes/PullRequest/20"
    )
    assert response.status_code == 403
    assert driver.opened == 0


def test_node_detail_endpoint_returns_content_and_origin_links(api_db):
    client, sessions = api_db
    record = {
        "labels": PULL_REQUEST["labels"], "props": PULL_REQUEST["props"],
        "connected": [{
            "labels": AUTHOR["labels"], "props": AUTHOR["props"],
            "relationship": "AUTHORED", "direction": "incoming",
        }],
    }
    driver = Driver(record)
    app.dependency_overrides[get_neo4j] = lambda: driver
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.VIEWER)

    response = client.get(
        f"/api/workspaces/{TEST_WORKSPACE_ID}/graph/nodes/PullRequest/20"
    )
    assert response.status_code == 200
    assert response.json()["content"] == "The full body"
    assert response.json()["origins"][1]["direction"] == "incoming"


def test_edge_detail_endpoint_returns_relationship_evidence_and_sources(api_db):
    client, sessions = api_db
    driver = Driver({
        "source_labels": AUTHOR["labels"], "source_props": AUTHOR["props"],
        "target_labels": PULL_REQUEST["labels"], "target_props": PULL_REQUEST["props"],
        "type": "AUTHORED", "props": {"evidence": "Alice authored this pull request."},
    })
    app.dependency_overrides[get_neo4j] = lambda: driver
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.VIEWER)

    response = client.get(
        f"/api/workspaces/{TEST_WORKSPACE_ID}/graph/edges",
        params={"source_key": "Author:1", "target_key": "PullRequest:20", "edge_type": "AUTHORED"},
    )
    assert response.status_code == 200
    assert response.json()["content"] == "Alice authored this pull request."
    assert [origin["key"] for origin in response.json()["origins"]] == [
        "Author:1", "PullRequest:20",
    ]
