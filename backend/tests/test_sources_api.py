"""Authorisation and payload tests for the source inventory endpoint."""

import pytest

from app.api.graph import get_neo4j
from app.main import app
from app.models import Role
from tests.authz import sign_in_with_role
from tests.payloads import TEST_WORKSPACE_ID
from tests.test_source_queries import SourceDriver

URL = f"/api/workspaces/{TEST_WORKSPACE_ID}/sources"


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.pop(get_neo4j, None)


def setup(api_db, records=(), role=Role.OWNER, driver=None):
    client, sessions = api_db
    driver = driver if driver is not None else SourceDriver(records)
    app.dependency_overrides[get_neo4j] = lambda: driver
    if role is not None:
        sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, role)
    return client, driver


def test_unauthenticated_request_does_not_read_neo4j(api_db):
    client, driver = setup(api_db, role=None)
    assert client.get(URL).status_code == 401
    assert driver.opened == 0


def test_non_member_request_does_not_read_neo4j(api_db):
    client, driver = setup(api_db, role=None)
    _, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, None)
    assert client.get(URL).status_code == 403
    assert driver.opened == 0


@pytest.mark.parametrize("role", [Role.OWNER, Role.EDITOR, Role.VIEWER])
def test_every_workspace_role_can_list_sources(api_db, role):
    client, _ = setup(api_db, role=role)
    assert client.get(URL).status_code == 200


def test_returns_source_counts(api_db):
    records = [
        {
            "repo": "cortex/app",
            "pull_requests": 8,
            "issues": 3,
            "total_items": 11,
        }
    ]
    client, _ = setup(api_db, records=records)
    assert client.get(URL).json() == records


def test_empty_workspace_returns_an_empty_list(api_db):
    client, _ = setup(api_db)
    assert client.get(URL).json() == []


def test_neo4j_failure_returns_503(api_db):
    from neo4j.exceptions import ServiceUnavailable

    class DownDriver:
        opened = 0

        def session(self):
            self.opened += 1
            raise ServiceUnavailable("down")

    client, _ = setup(api_db, driver=DownDriver())
    assert client.get(URL).status_code == 503
