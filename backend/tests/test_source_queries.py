"""Unit tests for workspace-scoped source summaries."""

from dataclasses import asdict

import pytest

from app.graph.queries import SOURCES_QUERY, fetch_source_summaries
from tests.test_graph_queries import FakeResult, FakeSession

WS = "ccccccc0-0000-4000-8000-00000000c0de"


class SourceTx:
    def __init__(self, records=()):
        self.records = list(records)
        self.calls: list[tuple[str, dict]] = []

    def run(self, cypher, **params):
        self.calls.append((cypher, params))
        return FakeResult(self.records)


class SourceDriver:
    def __init__(self, records=()):
        self.tx = SourceTx(records)
        self.opened = 0

    def session(self):
        self.opened += 1
        return FakeSession(self.tx)


def test_source_query_is_workspace_scoped_and_parameterised():
    driver = SourceDriver()
    fetch_source_summaries(driver, WS)

    cypher, params = driver.tx.calls[0]
    assert cypher is SOURCES_QUERY
    assert "n.workspace_id = $workspace_id" in cypher
    assert params == {"workspace_id": WS}
    assert WS not in cypher


def test_source_query_only_counts_repository_items_and_orders_results():
    assert "n:PullRequest OR n:Issue" in SOURCES_QUERY
    assert "ORDER BY toLower(repo), repo" in SOURCES_QUERY


def test_returns_typed_source_summaries():
    driver = SourceDriver(
        [
            {
                "repo": "cortex/app",
                "pull_requests": 8,
                "issues": 3,
                "total_items": 11,
            }
        ]
    )

    assert [asdict(source) for source in fetch_source_summaries(driver, WS)] == [
        {
            "repo": "cortex/app",
            "pull_requests": 8,
            "issues": 3,
            "total_items": 11,
        }
    ]


@pytest.mark.parametrize("bad", [None, "", "not-a-uuid"])
def test_bad_workspace_id_never_reaches_neo4j(bad):
    driver = SourceDriver()
    with pytest.raises(ValueError):
        fetch_source_summaries(driver, bad)
    assert driver.opened == 0
