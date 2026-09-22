import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.ingest import get_github_client, get_neo4j
from app.github.client import GitHubClient
from app.main import app

USER = {"id": 7, "login": "octocat"}
PR = {"id": 100, "number": 1, "title": "Add", "state": "open", "html_url": "u",
      "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-01T00:00:00Z", "user": USER}
ISSUE = {**PR, "id": 200, "number": 2}


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


def setup(handler, driver=None):
    driver = driver or FakeDriver()
    client = GitHubClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)
    app.dependency_overrides[get_github_client] = lambda: client
    app.dependency_overrides[get_neo4j] = lambda: driver
    return TestClient(app), driver


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def ok_handler(request):
    if request.url.path.endswith("/pulls"):
        return httpx.Response(200, json=[PR])
    return httpx.Response(200, json=[ISSUE, {**ISSUE, "id": 300, "pull_request": {}}])


def test_health():
    assert TestClient(app).get("/health").json() == {"status": "ok"}


def test_valid_repo_ingests():
    c, driver = setup(ok_handler)
    r = c.post("/api/ingest/github", json={"repo_url": "https://github.com/o/r"})
    assert r.status_code == 200
    assert r.json() == {"repo": "o/r", "pull_requests": 1, "issues": 1}
    assert len(driver.tx.calls) == 3


@pytest.mark.parametrize("url", ["", "not a url", "https://gitlab.com/a/b", "https://github.com/only"])
def test_invalid_url_422_and_nothing_touched(url):
    def boom(request):
        raise AssertionError("GitHub must not be called")

    c, driver = setup(boom)
    r = c.post("/api/ingest/github", json={"repo_url": url})
    assert r.status_code == 422
    assert driver.sessions == 0


def test_missing_body_field_422():
    c, _ = setup(ok_handler)
    assert c.post("/api/ingest/github", json={}).status_code == 422


def test_repo_not_found_404_no_writes():
    c, driver = setup(lambda r: httpx.Response(404))
    assert c.post("/api/ingest/github", json={"repo_url": "https://github.com/o/r"}).status_code == 404
    assert driver.sessions == 0


def test_rate_limit_429_with_retry_after():
    c, driver = setup(lambda r: httpx.Response(429, headers={"Retry-After": "5000"}))
    r = c.post("/api/ingest/github", json={"repo_url": "https://github.com/o/r"})
    assert r.status_code == 429 and r.headers["Retry-After"] == "5000"
    assert driver.sessions == 0


def test_github_server_error_502():
    c, driver = setup(lambda r: httpx.Response(500))
    assert c.post("/api/ingest/github", json={"repo_url": "https://github.com/o/r"}).status_code == 502
    assert driver.sessions == 0


def test_malformed_payload_502_no_writes():
    def handler(request):
        return httpx.Response(200, json=[{"id": "bad"}])

    c, driver = setup(handler)
    assert c.post("/api/ingest/github", json={"repo_url": "https://github.com/o/r"}).status_code == 502
    assert driver.sessions == 0


def test_neo4j_down_503():
    from neo4j.exceptions import ServiceUnavailable

    c, _ = setup(ok_handler, FakeDriver(error=ServiceUnavailable("down")))
    assert c.post("/api/ingest/github", json={"repo_url": "https://github.com/o/r"}).status_code == 503
