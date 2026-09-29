from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from neo4j.exceptions import DriverError, Neo4jError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.base import Base
from app.db.neo4j_driver import get_driver
from app.db.postgres import get_session
from app.db.schema import apply_constraints
from app.main import app
from tests.payloads import TEST_WORKSPACE_ID, TEST_WORKSPACE_IDS

# Every node a test writes carries workspace_id, so one predicate finds all of it
# -- including Author nodes, which the old repo-prefix cleanup could not match.
_CLEANUP = "MATCH (n) WHERE n.workspace_id IN $workspaces DETACH DELETE n"


def _wipe_test_data(driver) -> None:
    with driver.session() as s:
        s.run(_CLEANUP, workspaces=list(TEST_WORKSPACE_IDS)).consume()


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
    """Test graph: only ever creates/deletes reserved-workspace data."""
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

    def counts(self, workspace_id: str = TEST_WORKSPACE_ID) -> dict:
        p = {"ws": workspace_id}
        return {
            "Author": self._one(
                "MATCH (a:Author {workspace_id: $ws}) RETURN count(a)", **p
            ),
            "PullRequest": self._one(
                "MATCH (n:PullRequest {workspace_id: $ws}) RETURN count(n)", **p
            ),
            "Issue": self._one(
                "MATCH (n:Issue {workspace_id: $ws}) RETURN count(n)", **p
            ),
            "AUTHORED": self._one(
                "MATCH (a:Author {workspace_id: $ws})-[r:AUTHORED]->() RETURN count(r)", **p
            ),
        }

    def node(
        self, label: str, node_id: int, workspace_id: str = TEST_WORKSPACE_ID
    ) -> dict | None:
        with self.driver.session() as s:
            rec = s.run(
                f"MATCH (n:{label} {{id: $id, workspace_id: $ws}}) RETURN n",
                id=node_id,
                ws=workspace_id,
            ).single()
        return dict(rec["n"]) if rec else None

    def author_of(
        self, label: str, node_id: int, workspace_id: str = TEST_WORKSPACE_ID
    ) -> int | None:
        with self.driver.session() as s:
            rec = s.run(
                f"MATCH (a:Author)-[:AUTHORED]->(n:{label} {{id: $id, workspace_id: $ws}}) "
                "RETURN a.id AS id",
                id=node_id,
                ws=workspace_id,
            ).single()
        return rec["id"] if rec else None


@pytest.fixture
def api_db() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
    """TestClient plus a relational database, for endpoints behind auth.

    An in-memory SQLite stands in for Postgres, the approach `test_auth_api.py`
    and `test_workspaces_api.py` use: the real queries and the real
    `get_current_user` run, so authorisation is genuinely exercised.
    """
    engine = create_engine(
        "sqlite://",
        # One shared connection: the TestClient calls from another thread, and a
        # second connection would open a different (empty) in-memory database.
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_sessions = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_session() -> Iterator[Session]:
        with test_sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    original_secure_cookies = settings.secure_cookies
    settings.secure_cookies = False  # TestClient does not send cookies over TLS
    try:
        # Deliberately not `with TestClient(app)`: that runs the app lifespan, whose
        # shutdown calls close_driver() and would close the Neo4j driver shared with
        # the session-scoped `neo4j_driver` fixture, breaking every later graph test.
        yield TestClient(app), test_sessions
    finally:
        settings.secure_cookies = original_secure_cookies
        app.dependency_overrides.pop(get_session, None)
        Base.metadata.drop_all(engine)
        engine.dispose()
