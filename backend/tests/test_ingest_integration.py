"""US-7 integration tests: mock GitHub payloads -> real API -> real Neo4j (T-7.7).

Only GitHub is mocked (httpx.MockTransport); FastAPI, the mapper and Neo4j are
real. The relational half runs in-memory so a caller can hold a real workspace
membership without needing Postgres. Skipped automatically when Neo4j isn't
running. Only reserved-workspace test data is touched.
"""

import httpx
import pytest
from neo4j.exceptions import ConstraintError

from app.api.ingest import get_github_client
from app.github.client import GitHubClient
from app.main import app
from app.models import Role
from tests.authz import authenticate, grant, make_user, make_workspace
from tests.payloads import (
    TEST_ID_BASE,
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


@pytest.fixture
def client(api_db):
    """A caller holding OWNER on both reserved test workspaces."""
    test_client, sessions = api_db
    with sessions() as session:
        owner = make_user(session, "owner@example.com")
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


def use_github(handler):
    github = GitHubClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)
    app.dependency_overrides[get_github_client] = lambda: github


def body(workspace_id: str = TEST_WORKSPACE_ID, repo_url: str = TEST_REPO_URL) -> dict:
    return {"repo_url": repo_url, "workspace_id": workspace_id}


def github_repo(prs, issues, pr_page_two=None):
    """Handler serving a repo. If pr_page_two is given, PRs are split over two pages."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        page = request.url.params.get("page", "1")
        if path.endswith("/pulls"):
            if pr_page_two is None:
                return httpx.Response(200, json=prs)
            if page == "1":
                nxt = f'<https://api.github.com{path}?page=2>; rel="next"'
                return httpx.Response(200, json=prs, headers={"Link": nxt})
            return httpx.Response(200, json=pr_page_two)
        if path.endswith("/issues"):
            return httpx.Response(200, json=issues)
        return httpx.Response(404)

    return handler


def test_valid_repo_fetches_history_and_builds_graph(graph, client):
    """AC: valid repo URL -> historical PRs and issues become graph nodes."""
    prs = [pull_request(1, ALICE), pull_request(2, BOB)]
    page_two = [pull_request(3, ALICE)]  # proves pagination reaches the graph
    issues = [
        issue(4, BOB),
        pull_request(5, ALICE) | {"pull_request": {"url": "x"}},  # PR echoed by issues API
    ]
    use_github(github_repo(prs, issues, pr_page_two=page_two))

    r = client.post(URL, json=body())

    assert r.status_code == 200
    assert r.json() == {"repo": TEST_REPO, "pull_requests": 3, "issues": 1}
    assert graph.counts() == {"Author": 2, "PullRequest": 3, "Issue": 1, "AUTHORED": 4}


def test_empty_repo_remains_visible_as_a_source(graph, client):
    use_github(github_repo([], []))

    response = client.post(URL, json=body())

    assert response.status_code == 200
    assert response.json() == {
        "repo": TEST_REPO,
        "pull_requests": 0,
        "issues": 0,
    }
    assert client.get(f"/api/workspaces/{TEST_WORKSPACE_ID}/sources").json() == [
        {
            "repo": TEST_REPO,
            "pull_requests": 0,
            "issues": 0,
            "total_items": 0,
        }
    ]


def test_node_properties_and_provenance(graph, client):
    pr = pull_request(1, ALICE)
    use_github(github_repo([pr], [issue(2, BOB)]))
    assert client.post(URL, json=body()).status_code == 200

    node = graph.node("PullRequest", pr["id"])
    assert node["html_url"] == f"{TEST_REPO_URL}/pull/1"  # link back to the source
    assert node["repo"] == TEST_REPO
    assert node["workspace_id"] == TEST_WORKSPACE_ID
    assert node["number"] == 1 and node["state"] == "closed"
    assert node["body"] == ""  # null normalized
    assert node["merged_at"] == "2024-01-02T00:00:00Z"
    assert "head" not in node  # unmodelled GitHub fields are not stored
    assert graph.author_of("PullRequest", pr["id"]) == ALICE["id"]
    assert graph.author_of("Issue", issue(2, BOB)["id"]) == BOB["id"]
    author = graph.node("Author", ALICE["id"])
    assert author["login"] == "alice" and "type" not in author
    assert author["workspace_id"] == TEST_WORKSPACE_ID


def test_reingest_is_idempotent(graph, client):
    use_github(github_repo([pull_request(1, ALICE)], [issue(2, ALICE)]))
    assert client.post(URL, json=body()).status_code == 200
    first = graph.counts()
    assert client.post(URL, json=body()).status_code == 200
    assert graph.counts() == first == {"Author": 1, "PullRequest": 1, "Issue": 1, "AUTHORED": 2}


def test_reingest_updates_changed_fields(graph, client):
    pr = pull_request(1, ALICE, state="open", closed_at=None, merged_at=None)
    use_github(github_repo([pr], []))
    client.post(URL, json=body())
    assert graph.node("PullRequest", pr["id"])["state"] == "open"

    use_github(github_repo([pull_request(1, ALICE)], []))  # now closed + merged
    client.post(URL, json=body())
    assert graph.node("PullRequest", pr["id"])["state"] == "closed"
    assert graph.counts()["PullRequest"] == 1


def test_deleted_author_creates_node_without_edge(graph, client):
    use_github(github_repo([], [issue(1, None)]))
    assert client.post(URL, json=body()).status_code == 200
    assert graph.counts() == {"Author": 0, "PullRequest": 0, "Issue": 1, "AUTHORED": 0}


@pytest.mark.parametrize(
    "bad_url", ["https://gitlab.com/a/b", "https://github.com/onlyowner", "not a url", ""]
)
def test_invalid_url_creates_zero_nodes(graph, client, bad_url):
    """AC: invalid repo URL -> error, zero Neo4j nodes created."""

    def boom(request):
        raise AssertionError("GitHub must not be called for an invalid URL")

    use_github(boom)
    assert client.post(URL, json=body(repo_url=bad_url)).status_code == 422
    assert graph.counts() == {"Author": 0, "PullRequest": 0, "Issue": 0, "AUTHORED": 0}


def test_repo_not_found_creates_zero_nodes(graph, client):
    use_github(lambda r: httpx.Response(404))
    assert client.post(URL, json=body()).status_code == 404
    assert sum(graph.counts().values()) == 0


def test_rate_limit_creates_zero_nodes(graph, client):
    use_github(lambda r: httpx.Response(429, headers={"Retry-After": "99999"}))
    r = client.post(URL, json=body())
    assert r.status_code == 429 and r.headers["Retry-After"] == "99999"
    assert sum(graph.counts().values()) == 0


def test_bad_payload_late_in_batch_writes_nothing(graph, client):
    """A valid PR plus one malformed issue must not leave the valid PR behind."""
    bad_issue = issue(2, BOB) | {"id": "not-an-int"}
    use_github(github_repo([pull_request(1, ALICE)], [bad_issue]))
    assert client.post(URL, json=body()).status_code == 502
    assert sum(graph.counts().values()) == 0


def test_failed_reingest_leaves_existing_graph_intact(graph, client):
    use_github(github_repo([pull_request(1, ALICE)], [issue(2, BOB)]))
    assert client.post(URL, json=body()).status_code == 200
    before = graph.counts()

    use_github(lambda r: httpx.Response(500))
    assert client.post(URL, json=body()).status_code == 502
    assert graph.counts() == before


# --------------------------------------------------------------------------
# Workspace scoping -- the behaviour US-14 filters on
# --------------------------------------------------------------------------


def test_same_repo_in_two_workspaces_stays_separate(graph, client):
    """The same GitHub ids ingested twice must produce two independent graphs."""
    use_github(github_repo([pull_request(1, ALICE)], [issue(2, ALICE)]))
    assert client.post(URL, json=body(TEST_WORKSPACE_ID)).status_code == 200
    assert client.post(URL, json=body(TEST_WORKSPACE_ID_B)).status_code == 200

    expected = {"Author": 1, "PullRequest": 1, "Issue": 1, "AUTHORED": 2}
    assert graph.counts(TEST_WORKSPACE_ID) == expected
    assert graph.counts(TEST_WORKSPACE_ID_B) == expected

    pr_id = pull_request(1, ALICE)["id"]
    assert graph.node("PullRequest", pr_id, TEST_WORKSPACE_ID)["workspace_id"] == (
        TEST_WORKSPACE_ID
    )
    assert graph.node("PullRequest", pr_id, TEST_WORKSPACE_ID_B)["workspace_id"] == (
        TEST_WORKSPACE_ID_B
    )


def test_one_workspace_ingest_leaves_the_other_empty(graph, client):
    """AC: opening a workspace shows only nodes associated with it."""
    use_github(github_repo([pull_request(1, ALICE)], [issue(2, BOB)]))
    assert client.post(URL, json=body(TEST_WORKSPACE_ID)).status_code == 200

    assert sum(graph.counts(TEST_WORKSPACE_ID).values()) > 0
    assert graph.counts(TEST_WORKSPACE_ID_B) == {
        "Author": 0, "PullRequest": 0, "Issue": 0, "AUTHORED": 0
    }


def test_authored_edges_never_cross_workspaces(graph, client):
    """An Author in workspace A must not gain edges to workspace B's nodes."""
    use_github(github_repo([pull_request(1, ALICE)], []))
    client.post(URL, json=body(TEST_WORKSPACE_ID))
    client.post(URL, json=body(TEST_WORKSPACE_ID_B))

    with graph.driver.session() as s:
        crossing = s.run(
            "MATCH (a:Author)-[:AUTHORED]->(n) "
            "WHERE a.workspace_id IN $ws AND a.workspace_id <> n.workspace_id "
            "RETURN count(*) AS c",
            ws=[TEST_WORKSPACE_ID, TEST_WORKSPACE_ID_B],
        ).single()["c"]
    assert crossing == 0


def test_schema_constraints_reject_duplicate_ids_within_a_workspace(graph):
    """Uniqueness is composite: same id + same workspace is rejected."""
    with graph.driver.session() as s:
        for label in ("Author", "PullRequest", "Issue"):
            nid = TEST_ID_BASE + 9000 + len(label)
            props = {"id": nid, "workspace_id": TEST_WORKSPACE_ID}
            s.run(f"CREATE (:{label} $p)", p=props).consume()
            with pytest.raises(ConstraintError):
                s.run(f"CREATE (:{label} $p)", p=props).consume()


def test_schema_constraints_allow_the_same_id_in_another_workspace(graph):
    """The whole point of the composite key: workspaces don't collide."""
    with graph.driver.session() as s:
        for label in ("Author", "PullRequest", "Issue"):
            nid = TEST_ID_BASE + 9500 + len(label)
            s.run(
                f"CREATE (:{label} $p)", p={"id": nid, "workspace_id": TEST_WORKSPACE_ID}
            ).consume()
            s.run(
                f"CREATE (:{label} $p)", p={"id": nid, "workspace_id": TEST_WORKSPACE_ID_B}
            ).consume()
            found = s.run(
                f"MATCH (n:{label} {{id: $id}}) RETURN count(n) AS c", id=nid
            ).single()["c"]
            assert found == 2


def test_repository_constraint_is_workspace_scoped(graph):
    props = {"repo": "cortex/empty", "workspace_id": TEST_WORKSPACE_ID}
    with graph.driver.session() as session:
        session.run("CREATE (:Repository $props)", props=props).consume()
        with pytest.raises(ConstraintError):
            session.run("CREATE (:Repository $props)", props=props).consume()

        session.run(
            "CREATE (:Repository $props)",
            props={"repo": "cortex/empty", "workspace_id": TEST_WORKSPACE_ID_B},
        ).consume()
