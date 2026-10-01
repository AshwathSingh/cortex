import pytest
from pydantic import ValidationError

from app.github.mapper import (
    UPSERT_AUTHORS,
    UPSERT_ISSUES,
    UPSERT_PULL_REQUESTS,
    build_statements,
    normalise_workspace_id,
    write_graph,
)

USER = {"id": 7, "login": "octocat", "html_url": "https://github.com/octocat", "type": "User"}
WS = "ccccccc0-0000-4000-8000-00000000c0de"


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


def build(prs, issues, workspace_id=WS):
    return build_statements("o/r", prs, issues, workspace_id=workspace_id)


def test_statement_order_and_shape():
    stmts = build([pr()], [issue()])
    assert [s[0] for s in stmts] == [UPSERT_AUTHORS, UPSERT_PULL_REQUESTS, UPSERT_ISSUES]
    assert stmts[0][1]["rows"] == [
        {"id": 7, "login": "octocat", "html_url": "https://github.com/octocat"}
    ]


def test_pr_props_normalized():
    props = build([pr()], [])[1][1]["rows"][0]["props"]
    assert props["id"] == 100 and props["repo"] == "o/r"
    assert props["body"] == ""  # null body normalized
    assert props["merged_at"].startswith("2024-01-02")
    assert "head" not in props  # unknown fields dropped


def test_authors_deduplicated():
    stmts = build([pr(), pr(id=101, number=3)], [issue()])
    assert len(stmts[0][1]["rows"]) == 1


def test_deleted_user_has_no_author_edge():
    stmts = build([], [issue(user=None)])
    assert len(stmts) == 1  # no author statement
    assert stmts[0][1]["rows"][0]["author_id"] is None


def test_empty_input_no_statements():
    assert build([], []) == []


@pytest.mark.parametrize("bad", [{"id": "x"}, {"title": None}, {"state": "weird"}])
def test_invalid_payload_raises(bad):
    with pytest.raises(ValidationError):
        build([pr(**bad)], [])


# --------------------------------------------------------------------------
# Workspace scoping (US-7 / US-14)
# --------------------------------------------------------------------------


def test_every_statement_carries_the_workspace_id():
    for _, params in build([pr()], [issue()]):
        assert params["workspace_id"] == WS


def test_workspace_id_is_stamped_on_node_props():
    stmts = build([pr()], [issue()])
    pr_props = stmts[1][1]["rows"][0]["props"]
    issue_props = stmts[2][1]["rows"][0]["props"]
    assert pr_props["workspace_id"] == WS
    assert issue_props["workspace_id"] == WS


def test_workspace_id_is_part_of_every_merge_key():
    """Without this, two workspaces ingesting one repo would share nodes."""
    for cypher in (UPSERT_AUTHORS, UPSERT_PULL_REQUESTS, UPSERT_ISSUES):
        assert "workspace_id: $workspace_id" in cypher


def test_author_edges_are_workspace_qualified():
    """An AUTHORED edge must not bind to another workspace's Author node."""
    for cypher in (UPSERT_PULL_REQUESTS, UPSERT_ISSUES):
        assert "MATCH (a:Author {id: row.author_id, workspace_id: $workspace_id})" in cypher


@pytest.mark.parametrize("missing", [None, "", "   "])
def test_missing_workspace_id_refused(missing):
    """Unscoped nodes are invisible to every workspace query, so refuse to write them."""
    with pytest.raises(ValueError, match="workspace_id is required"):
        build([pr()], [issue()], workspace_id=missing)


@pytest.mark.parametrize("bad", ["not-a-uuid", "12345", "o/r", "null", "None"])
def test_non_uuid_workspace_id_refused(bad):
    with pytest.raises(ValueError, match="must be a UUID"):
        build([pr()], [issue()], workspace_id=bad)


def test_workspace_id_canonicalised():
    """Two spellings of one UUID must not create two copies of every node."""
    upper = WS.upper()
    assert normalise_workspace_id(upper) == WS
    assert build([pr()], [], workspace_id=upper)[0][1]["workspace_id"] == WS


def test_bad_workspace_id_is_checked_before_payload_validation():
    """The guard must fire even when the payloads would also have failed."""
    with pytest.raises(ValueError, match="workspace_id is required"):
        build([pr(id="not-an-int")], [], workspace_id=None)


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
    assert write_graph(d, "o/r", [pr()], [issue()], workspace_id=WS) == 3
    assert len(d.tx.calls) == 3 and d.opened == 1


def test_invalid_payload_touches_no_database():
    d = FakeDriver()
    with pytest.raises(ValidationError):
        write_graph(d, "o/r", [pr()], [issue(id="bad")], workspace_id=WS)
    assert d.opened == 0


@pytest.mark.parametrize("bad", [None, "", "not-a-uuid"])
def test_write_graph_with_bad_workspace_id_touches_no_database(bad):
    d = FakeDriver()
    with pytest.raises(ValueError):
        write_graph(d, "o/r", [pr()], [issue()], workspace_id=bad)
    assert d.opened == 0


def test_workspace_id_must_be_passed_by_keyword():
    """repo and workspace_id are both strings; a positional swap must not compile."""
    with pytest.raises(TypeError):
        build_statements("o/r", [pr()], [issue()], WS)  # type: ignore[misc]
