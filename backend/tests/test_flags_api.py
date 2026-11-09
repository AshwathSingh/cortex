"""T-28.3: the Pruning Agent endpoint -- authorisation, shape and failure modes.

The rules themselves are covered in ``test_pruning_rules.py`` against hand-built
items. These drive the endpoint with a fake graph, so what is under test is the
read, the authorisation and the serialisation -- not the thresholds again.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from neo4j.exceptions import ServiceUnavailable

from app.api.flags import get_neo4j
from app.main import app
from app.models import Role
from tests.authz import make_user, make_workspace, sign_in_with_role
from tests.payloads import TEST_WORKSPACE_ID

URL = f"/api/workspaces/{TEST_WORKSPACE_ID}/flags"
NOW = datetime.now(timezone.utc)


def record(
    node_id: int = 1,
    *,
    label: str = "Issue",
    title: str = "Login redirect is broken",
    state: str = "open",
    body: str = "x" * 80,
    updated_days_ago: int = 1,
    closed_days_ago: int | None = None,
    merged_days_ago: int | None = None,
    author_login: str | None = "ashwath",
    repo: str = "cortex/app",
) -> dict:
    def ago(days: int | None) -> str | None:
        return None if days is None else (NOW - timedelta(days=days)).isoformat()

    return {
        "labels": [label],
        "props": {
            "id": node_id,
            "number": node_id,
            "title": title,
            "state": state,
            "body": body,
            "repo": repo,
            "html_url": f"https://github.com/{repo}/issues/{node_id}",
            "created_at": ago(updated_days_ago),
            "updated_at": ago(updated_days_ago),
            "closed_at": ago(closed_days_ago),
            "merged_at": ago(merged_days_ago),
            "workspace_id": TEST_WORKSPACE_ID,
        },
        "author_login": author_login,
    }


class FakeTx:
    def __init__(self, records):
        self.records = list(records)
        self.params: dict = {}

    def run(self, cypher, **params):
        self.params = params
        return self.records


class FakeSession:
    def __init__(self, tx):
        self.tx = tx

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute_read(self, fn):
        return fn(self.tx)


class FakeDriver:
    def __init__(self, records=()):
        self.tx = FakeTx(records)
        self.opened = 0

    def session(self):
        self.opened += 1
        return FakeSession(self.tx)


class BrokenDriver:
    def __init__(self):
        self.opened = 0

    def session(self):
        self.opened += 1
        raise ServiceUnavailable("no graph")


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.pop(get_neo4j, None)


def setup(api_db, records=(), role=Role.OWNER, driver=None):
    client, sessions = api_db
    driver = driver if driver is not None else FakeDriver(records)
    app.dependency_overrides[get_neo4j] = lambda: driver
    if role is not None:
        sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, role)
    return client, driver


def flags_of(client, url: str = URL):
    return client.get(url).json()["flags"]


# --- authorisation ----------------------------------------------------------


def test_an_unauthenticated_request_never_reaches_the_graph(api_db):
    client, driver = setup(api_db, role=None)

    assert client.get(URL).status_code == 401
    assert driver.opened == 0


def test_a_non_member_never_reaches_the_graph(api_db):
    client, driver = setup(api_db, role=None)
    _, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, None)

    assert client.get(URL).status_code == 403
    assert driver.opened == 0


@pytest.mark.parametrize("role", [Role.OWNER, Role.EDITOR, Role.VIEWER])
def test_every_member_sees_the_same_flags(api_db, role):
    """AC3: a review queue only half the team can see is not a review queue."""
    client, _ = setup(api_db, [record(body="")], role=role)

    response = client.get(URL)

    assert response.status_code == 200
    assert len(response.json()["flags"]) == 1


# --- reading ----------------------------------------------------------------


def test_the_read_is_scoped_to_the_workspace(api_db):
    client, driver = setup(api_db, [record()])

    client.get(URL)

    assert driver.tx.params["workspace_id"] == TEST_WORKSPACE_ID


def test_a_workspace_with_nothing_wrong_has_an_empty_queue(api_db):
    client, _ = setup(api_db, [record()])

    body = client.get(URL).json()

    assert body["flags"] == []
    assert body["workspace_id"] == TEST_WORKSPACE_ID
    assert body["truncated"] is False
    assert body["generated_at"]


def test_an_empty_graph_has_an_empty_queue(api_db):
    client, _ = setup(api_db, [])

    assert flags_of(client) == []


def test_each_rule_reaches_the_endpoint(api_db):
    """AC1, end to end: out of date, contradicted and thinly supported."""
    client, _ = setup(api_db, [
        record(1, title="Fix login redirect", updated_days_ago=400, body=""),
        record(2, title="Fix login redirect", state="closed", closed_days_ago=3,
               updated_days_ago=3),
    ])

    rules = {flag["rule"] for flag in flags_of(client)}

    assert rules == {"STALE", "CONTRADICTED", "THIN"}


def test_a_flag_names_its_items_and_how_serious_it_is(api_db):
    """AC2."""
    client, _ = setup(api_db, [record(7, title="Dangling task", body="", author_login=None)])

    (flag,) = flags_of(client)

    assert flag["rule"] == "THIN"
    assert flag["label"] == "Thinly supported"
    assert flag["severity"] == "HIGH"
    assert "Dangling task" in flag["summary"]
    (target,) = flag["targets"]
    assert target == {
        "key": "Issue:7",
        "type": "Issue",
        "title": "Dangling task",
        "url": "https://github.com/cortex/app/issues/7",
    }


def test_a_flag_carries_the_evidence_behind_it(api_db):
    """AC4: the reader has to be able to judge whether the agent was right."""
    client, _ = setup(api_db, [record(updated_days_ago=400)])

    (flag,) = flags_of(client)

    evidence = {item["label"]: item["detail"] for item in flag["evidence"]}
    assert "Last activity" in evidence
    assert evidence["State"] == "open"
    assert evidence["Author"] == "ashwath"


def test_a_contradiction_names_both_items(api_db):
    client, _ = setup(api_db, [
        record(1, label="PullRequest", title="Fix login redirect", state="closed",
               closed_days_ago=2, merged_days_ago=2, updated_days_ago=2),
        record(2, title="fix the login redirect"),
    ])

    (flag,) = [f for f in flags_of(client) if f["rule"] == "CONTRADICTED"]

    assert {target["key"] for target in flag["targets"]} == {
        "PullRequest:1",
        "Issue:2",
    }
    assert flag["severity"] == "HIGH"


def test_the_queue_is_ordered_worst_first(api_db):
    client, _ = setup(api_db, [
        record(1, body=""),                          # LOW
        record(2, body="", author_login=None),       # HIGH
        record(3, author_login=None),                # MEDIUM
    ])

    severities = [flag["severity"] for flag in flags_of(client)]

    assert severities == ["HIGH", "MEDIUM", "LOW"]


def test_the_same_finding_keeps_its_id_across_runs(api_db):
    client, _ = setup(api_db, [record(body="")])

    first = flags_of(client)[0]["id"]
    second = flags_of(client)[0]["id"]

    assert first == second


def test_the_item_ceiling_is_reported(api_db):
    client, driver = setup(api_db, [record(1), record(2)])

    body = client.get(f"{URL}?item_limit=2").json()

    assert driver.tx.params["limit"] == 2
    assert body["truncated"] is True


@pytest.mark.parametrize("limit", ["0", "-1", "10001", "all"])
def test_an_impossible_item_limit_is_refused(api_db, limit):
    client, _ = setup(api_db, [record()])

    assert client.get(f"{URL}?item_limit={limit}").status_code == 422


# --- failure ----------------------------------------------------------------


def test_a_graph_outage_is_an_error_not_an_empty_queue(api_db):
    """"Nothing needs review" and "we could not look" are different answers,
    and the first is the dangerous one to fake."""
    client, driver = setup(api_db, driver=BrokenDriver())

    response = client.get(URL)

    assert response.status_code == 503
    assert response.json()["detail"] == "Graph database unavailable"
    assert driver.opened == 1


def test_another_workspace_is_a_403_not_an_empty_queue(api_db):
    client, _ = setup(api_db, [record(body="")])
    _, sessions = api_db
    with sessions() as session:
        make_workspace(session, "Other", "ccccccc0-0000-4000-8000-00000000c0df")
        make_user(session, "outsider@example.com")
        session.commit()

    other = "/api/workspaces/ccccccc0-0000-4000-8000-00000000c0df/flags"
    assert client.get(other).status_code == 403


def test_a_workspace_that_does_not_exist_is_a_403(api_db):
    client, _ = setup(api_db, [record()])

    assert client.get(f"/api/workspaces/{uuid.uuid4()}/flags").status_code == 403
