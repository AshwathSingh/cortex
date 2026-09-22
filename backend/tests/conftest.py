import pytest
from neo4j.exceptions import DriverError, Neo4jError

from app.db.neo4j_driver import get_driver
from app.db.schema import apply_constraints
from tests.payloads import TEST_ID_BASE, TEST_REPO_PREFIX

_CLEANUP = [
    "MATCH (n) WHERE (n:PullRequest OR n:Issue) AND n.repo STARTS WITH $prefix DETACH DELETE n",
    "MATCH (a:Author) WHERE a.id >= $base DETACH DELETE a",
]


def _wipe_test_data(driver) -> None:
    with driver.session() as s:
        for q in _CLEANUP:
            s.run(q, prefix=TEST_REPO_PREFIX, base=TEST_ID_BASE).consume()


@pytest.fixture(scope="session")
def neo4j_driver():
    """Real Neo4j driver; skips the test if the database isn't reachable."""
    try:
        driver = get_driver()
        driver.verify_connectivity()
        apply_constraints(driver)
    except (DriverError, Neo4jError, OSError) as e:
        pytest.skip(f"Neo4j not available (docker compose up -d neo4j): {e}")
    return driver


@pytest.fixture
def graph(neo4j_driver):
    """Test graph: only ever creates/deletes reserved-id data, never other nodes."""
    _wipe_test_data(neo4j_driver)
    yield TestGraph(neo4j_driver)
    _wipe_test_data(neo4j_driver)


class TestGraph:
    __test__ = False  # not a pytest test class

    def __init__(self, driver):
        self.driver = driver

    def _one(self, query: str, **params):
        with self.driver.session() as s:
            return s.run(query, **params).single()[0]

    def counts(self) -> dict:
        p = {"prefix": TEST_REPO_PREFIX, "base": TEST_ID_BASE}
        return {
            "Author": self._one("MATCH (a:Author) WHERE a.id >= $base RETURN count(a)", **p),
            "PullRequest": self._one(
                "MATCH (n:PullRequest) WHERE n.repo STARTS WITH $prefix RETURN count(n)", **p
            ),
            "Issue": self._one(
                "MATCH (n:Issue) WHERE n.repo STARTS WITH $prefix RETURN count(n)", **p
            ),
            "AUTHORED": self._one(
                "MATCH (a:Author)-[r:AUTHORED]->() WHERE a.id >= $base RETURN count(r)", **p
            ),
        }

    def node(self, label: str, node_id: int) -> dict | None:
        with self.driver.session() as s:
            rec = s.run(f"MATCH (n:{label} {{id: $id}}) RETURN n", id=node_id).single()
        return dict(rec["n"]) if rec else None

    def author_of(self, label: str, node_id: int) -> int | None:
        with self.driver.session() as s:
            rec = s.run(
                f"MATCH (a:Author)-[:AUTHORED]->(n:{label} {{id: $id}}) RETURN a.id AS id",
                id=node_id,
            ).single()
        return rec["id"] if rec else None
