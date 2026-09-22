"""US-7 integration tests: mock GitHub payloads -> real API -> real Neo4j (T-7.7).

Only GitHub is mocked (httpx.MockTransport); FastAPI, the mapper and Neo4j are real.
Skipped automatically when Neo4j isn't running. Only reserved-id test data is touched.
"""

import httpx
import pytest
from fastapi.testclient import TestClient
from neo4j.exceptions import ConstraintError

from app.api.ingest import get_github_client
from app.github.client import GitHubClient
from app.main import app
from tests.payloads import TEST_ID_BASE, TEST_REPO, TEST_REPO_URL, issue, pull_request, user

pytestmark = pytest.mark.integration

ALICE, BOB = user(1, "alice"), user(2, "bob")
URL = "/api/ingest/github"


def use_github(handler):
    client = GitHubClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)
    app.dependency_overrides[get_github_client] = lambda: client
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    app.dependency_overrides.clear()


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


def test_valid_repo_fetches_history_and_builds_graph(graph):
    """AC: valid repo URL -> historical PRs and issues become graph nodes."""
    prs = [pull_request(1, ALICE), pull_request(2, BOB)]
    page_two = [pull_request(3, ALICE)]  # proves pagination reaches the graph
    issues = [
        issue(4, BOB),
        pull_request(5, ALICE) | {"pull_request": {"url": "x"}},  # PR echoed by issues API
    ]
    c = use_github(github_repo(prs, issues, pr_page_two=page_two))

    r = c.post(URL, json={"repo_url": TEST_REPO_URL})

    assert r.status_code == 200
    assert r.json() == {"repo": TEST_REPO, "pull_requests": 3, "issues": 1}
    assert graph.counts() == {"Author": 2, "PullRequest": 3, "Issue": 1, "AUTHORED": 4}


def test_node_properties_and_provenance(graph):
    pr = pull_request(1, ALICE)
    c = use_github(github_repo([pr], [issue(2, BOB)]))
    assert c.post(URL, json={"repo_url": TEST_REPO_URL}).status_code == 200

    node = graph.node("PullRequest", pr["id"])
    assert node["html_url"] == f"{TEST_REPO_URL}/pull/1"  # link back to the source
    assert node["repo"] == TEST_REPO
    assert node["number"] == 1 and node["state"] == "closed"
    assert node["body"] == ""  # null normalized
    assert node["merged_at"] == "2024-01-02T00:00:00Z"
    assert "head" not in node  # unmodelled GitHub fields are not stored
    assert graph.author_of("PullRequest", pr["id"]) == ALICE["id"]
    assert graph.author_of("Issue", issue(2, BOB)["id"]) == BOB["id"]
    author = graph.node("Author", ALICE["id"])
    assert author["login"] == "alice" and "type" not in author


def test_reingest_is_idempotent(graph):
    c = use_github(github_repo([pull_request(1, ALICE)], [issue(2, ALICE)]))
    body = {"repo_url": TEST_REPO_URL}
    assert c.post(URL, json=body).status_code == 200
    first = graph.counts()
    assert c.post(URL, json=body).status_code == 200
    assert graph.counts() == first == {"Author": 1, "PullRequest": 1, "Issue": 1, "AUTHORED": 2}


def test_reingest_updates_changed_fields(graph):
    pr = pull_request(1, ALICE, state="open", closed_at=None, merged_at=None)
    use_github(github_repo([pr], [])).post(URL, json={"repo_url": TEST_REPO_URL})
    assert graph.node("PullRequest", pr["id"])["state"] == "open"

    merged = pull_request(1, ALICE)  # now closed + merged
    use_github(github_repo([merged], [])).post(URL, json={"repo_url": TEST_REPO_URL})
    assert graph.node("PullRequest", pr["id"])["state"] == "closed"
    assert graph.counts()["PullRequest"] == 1


def test_deleted_author_creates_node_without_edge(graph):
    c = use_github(github_repo([], [issue(1, None)]))
    assert c.post(URL, json={"repo_url": TEST_REPO_URL}).status_code == 200
    assert graph.counts() == {"Author": 0, "PullRequest": 0, "Issue": 1, "AUTHORED": 0}


@pytest.mark.parametrize(
    "bad_url", ["https://gitlab.com/a/b", "https://github.com/onlyowner", "not a url", ""]
)
def test_invalid_url_creates_zero_nodes(graph, bad_url):
    """AC: invalid repo URL -> error, zero Neo4j nodes created."""

    def boom(request):
        raise AssertionError("GitHub must not be called for an invalid URL")

    c = use_github(boom)
    assert c.post(URL, json={"repo_url": bad_url}).status_code == 422
    assert graph.counts() == {"Author": 0, "PullRequest": 0, "Issue": 0, "AUTHORED": 0}


def test_repo_not_found_creates_zero_nodes(graph):
    c = use_github(lambda r: httpx.Response(404))
    assert c.post(URL, json={"repo_url": TEST_REPO_URL}).status_code == 404
    assert sum(graph.counts().values()) == 0


def test_rate_limit_creates_zero_nodes(graph):
    c = use_github(lambda r: httpx.Response(429, headers={"Retry-After": "99999"}))
    r = c.post(URL, json={"repo_url": TEST_REPO_URL})
    assert r.status_code == 429 and r.headers["Retry-After"] == "99999"
    assert sum(graph.counts().values()) == 0


def test_bad_payload_late_in_batch_writes_nothing(graph):
    """A valid PR plus one malformed issue must not leave the valid PR behind."""
    bad_issue = issue(2, BOB) | {"id": "not-an-int"}
    c = use_github(github_repo([pull_request(1, ALICE)], [bad_issue]))
    assert c.post(URL, json={"repo_url": TEST_REPO_URL}).status_code == 502
    assert sum(graph.counts().values()) == 0


def test_failed_reingest_leaves_existing_graph_intact(graph):
    ok = use_github(github_repo([pull_request(1, ALICE)], [issue(2, BOB)]))
    assert ok.post(URL, json={"repo_url": TEST_REPO_URL}).status_code == 200
    before = graph.counts()

    down = use_github(lambda r: httpx.Response(500))
    assert down.post(URL, json={"repo_url": TEST_REPO_URL}).status_code == 502
    assert graph.counts() == before


def test_schema_constraints_reject_duplicate_ids(graph):
    """T-7.2: uniqueness constraints are active on Author/PullRequest/Issue ids."""
    with graph.driver.session() as s:
        for label in ("Author", "PullRequest", "Issue"):
            nid = TEST_ID_BASE + 9000 + len(label)
            props = {"id": nid, "repo": TEST_REPO} if label != "Author" else {"id": nid}
            s.run(f"CREATE (:{label} $p)", p=props).consume()
            with pytest.raises(ConstraintError):
                s.run(f"CREATE (:{label} $p)", p=props).consume()
