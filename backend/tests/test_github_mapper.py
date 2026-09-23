import pytest
from pydantic import ValidationError

from app.github.mapper import (
    UPSERT_AUTHORS,
    UPSERT_ISSUES,
    UPSERT_PULL_REQUESTS,
    build_statements,
    write_graph,
)

USER = {"id": 7, "login": "octocat", "html_url": "https://github.com/octocat", "type": "User"}


def pr(**over):
    base = {
        "id": 100, "number": 1, "title": "Add thing", "state": "closed", "body": None,
        "html_url": "https://github.com/o/r/pull/1",
        "created_at": "2024-01-01T00:00:00Z", "updated_at": "2024-01-02T00:00:00Z",
        "closed_at": "2024-01-02T00:00:00Z", "merged_at": "2024-01-02T00:00:00Z",
        "draft": False, "user": USER, "head": {"ref": "x"},
    }
    return {**base, **over}


def issue(**over):
    base = {
        "id": 200, "number": 2, "title": "Bug", "state": "open", "body": "broken",
        "html_url": "https://github.com/o/r/issues/2",
        "created_at": "2024-01-03T00:00:00Z", "updated_at": "2024-01-03T00:00:00Z",
        "user": USER,
    }
    return {**base, **over}


def test_statement_order_and_shape():
    stmts = build_statements("o/r", [pr()], [issue()])
    assert [s[0] for s in stmts] == [UPSERT_AUTHORS, UPSERT_PULL_REQUESTS, UPSERT_ISSUES]
    assert stmts[0][1]["rows"] == [
        {"id": 7, "login": "octocat", "html_url": "https://github.com/octocat"}
    ]


def test_pr_props_normalized():
    props = build_statements("o/r", [pr()], [])[1][1]["rows"][0]["props"]
    assert props["id"] == 100 and props["repo"] == "o/r"
    assert props["body"] == ""  # null body normalized
    assert props["merged_at"].startswith("2024-01-02")
    assert "head" not in props  # unknown fields dropped


def test_authors_deduplicated():
    stmts = build_statements("o/r", [pr(), pr(id=101, number=3)], [issue()])
    assert len(stmts[0][1]["rows"]) == 1


def test_deleted_user_has_no_author_edge():
    stmts = build_statements("o/r", [], [issue(user=None)])
    assert len(stmts) == 1  # no author statement
    assert stmts[0][1]["rows"][0]["author_id"] is None


def test_empty_input_no_statements():
    assert build_statements("o/r", [], []) == []


@pytest.mark.parametrize("bad", [{"id": "x"}, {"title": None}, {"state": "weird"}])
def test_invalid_payload_raises(bad):
    with pytest.raises(ValidationError):
        build_statements("o/r", [pr(**bad)], [])


class FakeTx:
    def __init__(self):
        self.calls = []

    def run(self, cypher, **params):
        self.calls.append((cypher, params))


class FakeSession:
    def __init__(self, tx):
        self.tx = tx

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute_write(self, fn):
        fn(self.tx)


class FakeDriver:
    def __init__(self):
        self.tx = FakeTx()
        self.opened = 0

    def session(self):
        self.opened += 1
        return FakeSession(self.tx)


def test_write_graph_runs_all_statements_in_one_transaction():
    d = FakeDriver()
    assert write_graph(d, "o/r", [pr()], [issue()]) == 3
    assert len(d.tx.calls) == 3 and d.opened == 1


def test_invalid_payload_touches_no_database():
    d = FakeDriver()
    with pytest.raises(ValidationError):
        write_graph(d, "o/r", [pr()], [issue(id="bad")])
    assert d.opened == 0
