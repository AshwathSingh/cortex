"""US-2 (T-2.4): POST /api/workspaces against its acceptance criteria.

Runs on in-memory SQLite like ``test_auth_api.py``; no Postgres needed.
"""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.base import Base
from app.db.postgres import get_session
from app.main import app
from app.models import Role, User, Workspace, WorkspaceMembership

URL = "/api/workspaces"
PASSWORD = "a-secure-password-with-15-characters"


@pytest.fixture
def db() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
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
    settings.secure_cookies = False
    try:
        yield test_sessions
    finally:
        settings.secure_cookies = original_secure_cookies
        app.dependency_overrides.pop(get_session, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def signed_in(email: str = "developer@example.com") -> TestClient:
    """A client holding a session cookie. Signup also creates one default workspace."""
    client = TestClient(app)
    response = client.post(
        "/api/auth/signup",
        json={"email": email, "password": PASSWORD, "display_name": "Developer"},
    )
    assert response.status_code == 201
    return client


def workspace_count(db: sessionmaker[Session]) -> int:
    with db() as session:
        return session.scalar(select(func.count()).select_from(Workspace))


def test_valid_submission_creates_owned_workspace(db):
    """AC: valid name submission creates a new workspace entry."""
    client = signed_in()

    response = client.post(URL, json={"name": "Apollo", "description": "Launch plans"})

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Apollo"
    assert body["description"] == "Launch plans"
    assert body["role"] == "OWNER"
    assert body["created_at"]

    with db() as session:
        membership = session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == Workspace.id,
                Workspace.name == "Apollo",
            )
        )
        assert membership is not None and membership.role is Role.OWNER


def test_created_workspace_opens_as_its_dashboard(db):
    """AC: the redirect target, GET /api/workspaces/{id}, serves the new workspace."""
    client = signed_in()
    created = client.post(URL, json={"name": "Apollo"}).json()

    opened = client.get(f"{URL}/{created['id']}")
    assert opened.status_code == 200
    assert opened.json() == created

    names = [w["name"] for w in client.get(URL).json()]
    assert "Apollo" in names


def test_description_is_optional_and_whitespace_is_trimmed(db):
    client = signed_in()

    no_description = client.post(URL, json={"name": "  Apollo  "})
    blank_description = client.post(URL, json={"name": "Hermes", "description": "   "})

    assert no_description.status_code == 201
    assert no_description.json()["name"] == "Apollo"
    assert no_description.json()["description"] is None
    assert blank_description.status_code == 201
    assert blank_description.json()["description"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 101},
        {"name": "Apollo", "description": "x" * 1001},
        {"name": None},
    ],
    ids=["missing", "empty", "whitespace", "long-name", "long-description", "null"],
)
def test_invalid_data_is_rejected_and_nothing_is_created(db, payload):
    """AC: invalid data returns an error and writes no workspace."""
    client = signed_in()
    before = workspace_count(db)

    assert client.post(URL, json=payload).status_code == 422
    assert workspace_count(db) == before


@pytest.mark.parametrize("duplicate", ["Apollo", "apollo", "  APOLLO "])
def test_duplicate_name_for_same_owner_is_409(db, duplicate):
    """AC: duplicate data returns a readable error and writes no workspace."""
    client = signed_in()
    assert client.post(URL, json={"name": "Apollo"}).status_code == 201
    before = workspace_count(db)

    response = client.post(URL, json={"name": duplicate})

    assert response.status_code == 409
    assert "already have a workspace named" in response.json()["detail"]
    assert workspace_count(db) == before


def test_other_users_can_reuse_a_name(db):
    assert signed_in("a@example.com").post(URL, json={"name": "Apollo"}).status_code == 201
    assert signed_in("b@example.com").post(URL, json={"name": "Apollo"}).status_code == 201


def test_workspace_shared_with_caller_does_not_block_the_name(db):
    """Only workspaces the caller OWNS count as duplicates, not ones they can view."""
    owner = signed_in("owner@example.com")
    shared_id = uuid.UUID(owner.post(URL, json={"name": "Apollo"}).json()["id"])

    viewer = signed_in("viewer@example.com")
    with db() as session:
        viewer_id = session.scalar(
            select(User.id).where(User.email == "viewer@example.com")
        )
        session.add(
            WorkspaceMembership(
                user_id=viewer_id, workspace_id=shared_id, role=Role.VIEWER
            )
        )
        session.commit()

    assert viewer.post(URL, json={"name": "Apollo"}).status_code == 201


def test_unauthenticated_request_is_401_and_creates_nothing(db):
    before = workspace_count(db)
    assert TestClient(app).post(URL, json={"name": "Apollo"}).status_code == 401
    assert workspace_count(db) == before


def test_list_and_detail_include_description(db):
    client = signed_in()
    created = client.post(URL, json={"name": "Apollo", "description": "Launch plans"})

    listed = {w["name"]: w for w in client.get(URL).json()}
    assert listed["Apollo"]["description"] == "Launch plans"
    # Signup's default workspace predates descriptions and has none.
    assert listed["Developer's Workspace"]["description"] is None
    assert client.get(f"{URL}/{created.json()['id']}").json()["description"] == "Launch plans"
