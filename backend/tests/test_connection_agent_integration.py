"""US-23 integration tests against real Neo4j. Jev is faked; nothing is paid for.

Flow: write PR/Issue nodes -> run the agent -> edges in Neo4j with provenance ->
graph endpoint shows only active edges -> review actions -> tombstones.
"""

import uuid

import pytest

from app.agent.service import ConnectionAgent
from app.agent.store import Neo4jStore
from app.db.neo4j_driver import get_driver
from app.github.mapper import write_graph
from app.jev.testing import FakeJev
from app.models import Role
from tests.authz import sign_in_with_role
from tests.payloads import TEST_REPO, TEST_WORKSPACE_ID, TEST_WORKSPACE_ID_B, issue, pull_request, user

pytestmark = pytest.mark.integration

WS = TEST_WORKSPACE_ID
ALICE = user(1, "alice")
PR_KEY = lambda n: f"PullRequest:{pull_request(n, None)['id']}"  # noqa: E731
ISSUE_KEY = lambda n: f"Issue:{issue(n, None)['id']}"  # noqa: E731


def sign_in_as(client, sessions, role, email):
    """Sign in a fresh user holding ``role`` on the (possibly already created) workspace."""
    from sqlalchemy import select
    from app.models import Workspace
    from tests.authz import authenticate, grant, make_user, make_workspace

    with sessions() as session:
        workspace = session.scalar(select(Workspace).where(Workspace.id == uuid.UUID(WS))) or make_workspace(session, "W", WS)
        member = make_user(session, email)
        grant(session, workspace, member, role)
        session.commit()
        session.refresh(member)
    client.cookies.clear()
    authenticate(client, sessions, member)


def seed(driver, ws=WS):
    write_graph(
        driver, TEST_REPO,
        [pull_request(1, ALICE, title="Fix login crash", body="Closes #2, the login crash on submit")],
        [issue(2, ALICE, title="Login crash on submit", body="users see a crash on login submit")],
        workspace_id=ws,
    )


def agent(driver, p, **kw):
    fake = FakeJev(lambda state, q: {"IMPLEMENTS:ab": p, "IMPLEMENTS:ba": p / 2})
    return ConnectionAgent(Neo4jStore(driver), fake, driver, threshold=0.7, review_floor=0.4,
                           max_candidates=10, **kw), fake


def agent_edges(graph, ws=WS):
    with graph.driver.session() as s:
        return [dict(r["p"]) for r in s.run(
            "MATCH ()-[r:AGENT_RELATIONSHIP {workspace_id: $ws}]->() RETURN properties(r) AS p", ws=ws)]


def test_active_edge_has_full_provenance_and_is_not_duplicated(graph):
    seed(graph.driver)
    a, fake = agent(graph.driver, 0.9)
    a.run(WS)
    a.run(WS)
    (edge,) = agent_edges(graph)
    for field in ("id", "workspace_id", "relationship_type", "origin", "source_agent", "model_version",
                  "status", "confidence", "evidence", "dedup_key", "created_at", "updated_at"):
        assert edge[field] is not None, field
    assert (edge["origin"], edge["source_agent"], edge["status"]) == ("agent", "connection_agent", "active")
    assert len(fake.calls) == 1
    with graph.driver.session() as s:
        statuses = {r["k"]: r["s"] for r in s.run(
            "MATCH (n {workspace_id: $ws}) WHERE n:Issue OR n:PullRequest RETURN n.id AS k, n.analysis_status AS s", ws=WS)}
    assert set(statuses.values()) == {"done"}


def test_mid_confidence_is_pending_and_hidden_from_graph_queries(graph, api_db):
    client, sessions = api_db
    seed(graph.driver)
    agent(graph.driver, 0.5)[0].run(WS)
    assert [e["status"] for e in agent_edges(graph)] == ["pending_review"]
    sign_in_with_role(client, sessions, WS, Role.VIEWER)
    body = client.get(f"/api/workspaces/{WS}/graph").json()
    assert [e for e in body["edges"] if e["type"] == "AGENT_RELATIONSHIP"] == []
    pending = client.get(f"/api/workspaces/{WS}/connections/suggestions").json()
    assert len(pending) == 1 and pending[0]["confidence"] == 0.5


def test_viewer_cannot_review_editor_can_approve_and_edge_goes_live(graph, api_db):
    client, sessions = api_db
    seed(graph.driver)
    agent(graph.driver, 0.5)[0].run(WS)
    edge_id = agent_edges(graph)[0]["id"]
    sign_in_as(client, sessions, Role.VIEWER, "v@example.com")
    base = f"/api/workspaces/{WS}/connections/suggestions/{edge_id}"
    assert client.post(f"{base}/approve").status_code == 403
    assert client.post(f"{base}/reject").status_code == 403

    sign_in_as(client, sessions, Role.EDITOR, "ed@example.com")
    assert client.post(f"{base}/approve").json() == {"status": "active"}
    edge = agent_edges(graph)[0]
    assert edge["status"] == "active" and edge["reviewed_by"] and edge["reviewed_at"]
    live = [e for e in client.get(f"/api/workspaces/{WS}/graph").json()["edges"] if e["type"] == "AGENT_RELATIONSHIP"]
    assert len(live) == 1 and live[0]["origin"] == "agent" and live[0]["confidence"] == 0.5
    assert client.post(f"{base}/approve").status_code == 404  # already reviewed


def test_rejected_pair_is_never_resuggested(graph, api_db):
    client, sessions = api_db
    seed(graph.driver)
    agent(graph.driver, 0.5)[0].run(WS)
    edge_id = agent_edges(graph)[0]["id"]
    sign_in_with_role(client, sessions, WS, Role.EDITOR)
    assert client.post(f"/api/workspaces/{WS}/connections/suggestions/{edge_id}/reject").status_code == 200
    a, fake = agent(graph.driver, 0.99)
    with graph.driver.session() as s:  # force re-analysis
        s.run("MATCH (n {workspace_id: $ws}) REMOVE n.analysis_hash", ws=WS).consume()
    a.run(WS)
    assert fake.calls == [] and [e["status"] for e in agent_edges(graph)] == ["rejected"]


def test_user_removing_an_agent_edge_leaves_a_tombstone(graph, api_db):
    client, sessions = api_db
    seed(graph.driver)
    agent(graph.driver, 0.9)[0].run(WS)
    sign_in_with_role(client, sessions, WS, Role.EDITOR)
    edge = agent_edges(graph)[0]
    with graph.driver.session() as s:
        src, tgt = s.run("MATCH (a)-[r:AGENT_RELATIONSHIP {id: $id}]->(b) RETURN labels(a)[0] + ':' + toString(a.id) AS a, labels(b)[0] + ':' + toString(b.id) AS b", id=edge["id"]).single().values()
    resp = client.request("DELETE", f"/api/workspaces/{WS}/graph/edges", json={
        "source_key": src, "target_key": tgt, "edge_type": "AGENT_RELATIONSHIP"})
    assert resp.status_code == 200
    assert agent_edges(graph)[0]["status"] == "rejected"
    graph_edges = client.get(f"/api/workspaces/{WS}/graph").json()["edges"]
    assert [e for e in graph_edges if e["type"] == "AGENT_RELATIONSHIP"] == []


def test_workspaces_are_isolated(graph):
    seed(graph.driver, WS)
    seed(graph.driver, TEST_WORKSPACE_ID_B)
    agent(graph.driver, 0.9)[0].run(WS)
    assert len(agent_edges(graph, WS)) == 1 and agent_edges(graph, TEST_WORKSPACE_ID_B) == []


def test_manual_edge_blocks_the_agent(graph):
    seed(graph.driver)
    with graph.driver.session() as s:
        s.run("MATCH (a:PullRequest {workspace_id: $ws}), (b:Issue {workspace_id: $ws}) "
              "CREATE (a)-[:MANUAL_RELATIONSHIP {workspace_id: $ws, relationship_type: 'RELATED_TO'}]->(b)",
              ws=WS).consume()
    a, fake = agent(graph.driver, 0.99)
    a.run(WS)
    assert fake.calls == [] and agent_edges(graph) == []
