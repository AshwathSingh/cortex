"""T-14.2 unit tests: the Cypher is workspace-scoped and the payload is well-formed.

No database. A fake session records the queries and replays canned records, so
these assert the *shape* of what gets sent and returned; `test_graph_integration`
proves it against real Neo4j.
"""

import pytest

from app.graph.queries import (
    EDGES_QUERY,
    GRAPH_LABELS,
    NODES_QUERY,
    fetch_graph,
    node_key,
)

WS = "ccccccc0-0000-4000-8000-00000000c0de"


def author(node_id: int, login: str = "alice") -> dict:
    return {
        "labels": ["Author"],
        "props": {"id": node_id, "login": login, "html_url": "https://gh/u", "workspace_id": WS},
    }


def pull_request(node_id: int, number: int = 1) -> dict:
    return {
        "labels": ["PullRequest"],
        "props": {
            "id": node_id, "number": number, "title": "Add thing", "state": "open",
            "html_url": "https://gh/pr", "repo": "o/r", "workspace_id": WS,
        },
    }


def issue(node_id: int, number: int = 2) -> dict:
    return {
        "labels": ["Issue"],
        "props": {
            "id": node_id, "number": number, "title": "Bug", "state": "open",
            "html_url": "https://gh/i", "repo": "o/r", "workspace_id": WS,
        },
    }


def edge(src: dict, dst: dict, rel: str = "AUTHORED") -> dict:
    return {
        "source_labels": src["labels"], "source_id": src["props"]["id"],
        "target_labels": dst["labels"], "target_id": dst["props"]["id"],
        "type": rel,
    }


class FakeResult:
    def __init__(self, records):
        self._records = records

    def __iter__(self):
        return iter(self._records)


class FakeTx:
    def __init__(self, nodes, edges):
        self.nodes, self.edges = nodes, edges
        self.calls: list[tuple[str, dict]] = []

    def run(self, cypher, **params):
        self.calls.append((cypher, params))
        return FakeResult(self.edges if cypher is EDGES_QUERY else self.nodes)


class FakeSession:
    def __init__(self, tx):
        self.tx = tx

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute_read(self, fn):
        return fn(self.tx)


class FakeDriver:
    def __init__(self, nodes=(), edges=()):
        self.tx = FakeTx(list(nodes), list(edges))
        self.opened = 0

    def session(self):
        self.opened += 1
        return FakeSession(self.tx)


# --------------------------------------------------------------------------
# Scoping -- the acceptance criterion this endpoint exists to satisfy
# --------------------------------------------------------------------------


def test_both_queries_filter_on_workspace_id():
    assert "n.workspace_id = $workspace_id" in NODES_QUERY
    assert "a.workspace_id = $workspace_id" in EDGES_QUERY
    assert "b.workspace_id = $workspace_id" in EDGES_QUERY


def test_edges_require_both_endpoints_in_the_workspace():
    """Guards against an edge dragging in a node from another workspace."""
    where = EDGES_QUERY.split("WHERE", 1)[1]
    assert where.count("workspace_id = $workspace_id") == 2


def test_both_queries_order_before_limiting():
    """An unordered LIMIT slices an arbitrary subset.

    Two requests against an unchanged workspace would then return different
    nodes, and the canvas would reshuffle on reload for no reason.
    """
    for query in (NODES_QUERY, EDGES_QUERY):
        assert "ORDER BY" in query, query
        assert query.index("ORDER BY") < query.index("LIMIT"), query


def test_ordering_matches_the_node_key_the_client_builds():
    # node_key() is "{label}:{id}", so ordering by label then id keeps the
    # truncated set aligned with how the client identifies nodes.
    assert "ORDER BY head(labels(n)), n.id" in NODES_QUERY


def test_queries_are_restricted_to_known_labels():
    for label in GRAPH_LABELS:
        assert f"n:{label}" in NODES_QUERY
        assert f"a:{label}" in EDGES_QUERY
        assert f"b:{label}" in EDGES_QUERY


def test_workspace_id_is_passed_as_a_parameter_not_interpolated():
    d = FakeDriver(nodes=[author(1)])
    fetch_graph(d, WS)
    for cypher, params in d.tx.calls:
        assert params["workspace_id"] == WS
        assert WS not in cypher


def test_canonicalises_the_workspace_id():
    """Read and write must agree on UUID form or filtering silently returns nothing."""
    d = FakeDriver(nodes=[author(1)])
    payload = fetch_graph(d, WS.upper())
    assert payload.workspace_id == WS
    assert d.tx.calls[0][1]["workspace_id"] == WS


@pytest.mark.parametrize("bad", [None, "", "   ", "not-a-uuid"])
def test_bad_workspace_id_never_reaches_the_database(bad):
    d = FakeDriver(nodes=[author(1)])
    with pytest.raises(ValueError):
        fetch_graph(d, bad)
    assert d.opened == 0


# --------------------------------------------------------------------------
# Payload shape
# --------------------------------------------------------------------------


def test_one_read_transaction_for_both_queries():
    d = FakeDriver(nodes=[author(1)], edges=[])
    fetch_graph(d, WS)
    assert d.opened == 1 and len(d.tx.calls) == 2


def test_node_keys_are_label_qualified():
    """An Author id and an Issue id can collide numerically; keys must not."""
    a, i = author(500), issue(500)
    payload = fetch_graph(FakeDriver(nodes=[a, i]), WS)
    keys = [n["key"] for n in payload.nodes]
    assert keys == ["Author:500", "Issue:500"]
    assert len(set(keys)) == 2


def test_edges_reference_node_keys():
    a, pr = author(1), pull_request(100)
    payload = fetch_graph(FakeDriver(nodes=[a, pr], edges=[edge(a, pr)]), WS)
    assert payload.edges == [
        {"source": "Author:1", "target": "PullRequest:100", "type": "AUTHORED"}
    ]


def test_node_payload_fields():
    payload = fetch_graph(FakeDriver(nodes=[pull_request(100, number=7)]), WS)
    node = payload.nodes[0]
    assert node["type"] == "PullRequest"
    assert node["title"] == "#7 Add thing"
    assert node["url"] == "https://gh/pr"
    assert node["state"] == "open" and node["repo"] == "o/r" and node["number"] == 7


def test_author_title_uses_login():
    payload = fetch_graph(FakeDriver(nodes=[author(1, "octocat")]), WS)
    assert payload.nodes[0]["title"] == "octocat"


def test_isolated_nodes_are_returned():
    """An Issue whose author was deleted has no edge but still belongs on the canvas."""
    payload = fetch_graph(FakeDriver(nodes=[issue(200)], edges=[]), WS)
    assert len(payload.nodes) == 1 and payload.edges == []


def test_empty_workspace_is_not_an_error():
    payload = fetch_graph(FakeDriver(), WS)
    assert payload.nodes == [] and payload.edges == [] and payload.truncated is False


# --------------------------------------------------------------------------
# Truncation
# --------------------------------------------------------------------------


def test_limits_are_passed_through():
    d = FakeDriver(nodes=[author(1)])
    fetch_graph(d, WS, node_limit=11, edge_limit=22)
    assert d.tx.calls[0][1]["limit"] == 11
    assert d.tx.calls[1][1]["limit"] == 22


def test_edges_with_a_dropped_endpoint_are_discarded():
    """Never hand the client a dangling endpoint when node_limit cut the graph."""
    a, pr = author(1), pull_request(100)
    d = FakeDriver(nodes=[a], edges=[edge(a, pr)])  # pr missing from the node set
    payload = fetch_graph(d, WS)
    assert payload.edges == []
    assert payload.truncated is True


def test_hitting_the_node_limit_flags_truncated():
    d = FakeDriver(nodes=[author(1), author(2)])
    assert fetch_graph(d, WS, node_limit=2).truncated is True


def test_under_the_limit_is_not_truncated():
    d = FakeDriver(nodes=[author(1)], edges=[])
    assert fetch_graph(d, WS, node_limit=50).truncated is False


def test_node_key_helper_handles_unknown_labels():
    assert node_key(["Something"], 3) == "Something:3"
    assert node_key([], 3) == "Unknown:3"
