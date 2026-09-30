"""T-43.3: workspace loading and authorisation checks.

Covers the two US-41 endpoints:

    GET /api/workspaces         the Workspace Selector's list
    GET /api/workspaces/{id}    opening one workspace

No Docker and no network: the fixture runs the real queries against an
in-memory database, the same approach `test_auth_api.py` uses. `get_session`
is the only dependency overridden -- `get_current_user` is left alone, because
who may see which workspace is exactly what these tests check.

Callers authenticate the way the app really does, with a session cookie backed
by a `user_sessions` row, so an expired session or a deactivated account is
covered here too.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.base import Base
from app.db.postgres import get_session
from app.main import app
from app.models import Role, User, UserSession, Workspace, WorkspaceMembership
from app.security import hash_session_token, new_session_token
from app.services.workspaces import create_workspace

URL = "/api/workspaces"
PASSWORD = "a-secure-password-with-15-characters"

@pytest.fixture
def api() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
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
        with TestClient(app) as client:
            yield client, test_sessions
    finally:
        settings.secure_cookies = original_secure_cookies
        app.dependency_overrides.pop(get_session, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def db(api) -> sessionmaker[Session]:
    """US-2's tests need only the session factory; reuse the one `api` builds."""
    _, sessions = api
    return sessions        

# --------------------------------------------------------------------------
# Building a situation to test against
# --------------------------------------------------------------------------


def make_user(session: Session, email: str) -> User:
    user = User(email=email, password_hash=None, display_name=email.split("@")[0])
    session.add(user)
    session.flush()
    return user


def grant(session: Session, workspace: Workspace, user: User, role: Role) -> None:
    session.add(
        WorkspaceMembership(user_id=user.id, workspace_id=workspace.id, role=role)
    )


def authenticate(
    client: TestClient,
    sessions: sessionmaker[Session],
    user: User,
    *,
    expires_in: timedelta = timedelta(days=1),
) -> str:
    """Sign the caller in the way the app does: a real session row plus its cookie."""
    token = new_session_token()
    with sessions() as session:
        session.add(
            UserSession(
                user_id=user.id,
                token_hash=hash_session_token(token),
                expires_at=datetime.now(timezone.utc) + expires_in,
            )
        )
        session.commit()
    client.cookies.set(settings.session_cookie_name, token)
    return token


@dataclass
class Scenario:
    owner: User
    outsider: User
    apollo: Workspace  # owner holds OWNER
    cortex: Workspace  # owner holds OWNER
    shared: Workspace  # outsider owns, owner holds VIEWER
    private: Workspace  # outsider owns, owner holds nothing


@pytest.fixture
def scenario(api) -> Scenario:
    """Two users, four workspaces, five memberships.

    Mirrors `scripts/dev_workspace.py trial`, so the automated tests and the
    manual check exercise the same situation.
    """
    _, sessions = api
    with sessions() as session:
        owner = make_user(session, "owner@example.test")
        outsider = make_user(session, "outsider@example.test")

        apollo = create_workspace(session, name="Apollo", owner=owner)
        cortex = create_workspace(session, name="Cortex", owner=owner)
        shared = create_workspace(session, name="Shared", owner=outsider)
        private = create_workspace(session, name="Private Project", owner=outsider)
        session.flush()

        grant(session, shared, owner, Role.VIEWER)
        session.commit()

    return Scenario(owner, outsider, apollo, cortex, shared, private)


def names(payload: list[dict]) -> list[str]:
    return [w["name"] for w in payload]


def roles(payload: list[dict]) -> dict[str, str]:
    return {w["name"]: w["role"] for w in payload}


# --------------------------------------------------------------------------
# Loading the list
# --------------------------------------------------------------------------


def test_list_returns_every_workspace_the_user_holds_a_role_on(api, scenario):
    client, sessions = api
    authenticate(client, sessions, scenario.owner)

    response = client.get("/api/workspaces")

    assert response.status_code == 200
    assert names(response.json()) == ["Apollo", "Cortex", "Shared"]


def test_list_excludes_workspaces_the_user_has_no_role_on(api, scenario):
    """The core guarantee: you cannot see someone else's project."""
    client, sessions = api
    authenticate(client, sessions, scenario.owner)

    response = client.get("/api/workspaces")

    assert "Private Project" not in names(response.json())


def test_list_reports_the_callers_own_role_per_workspace(api, scenario):
    client, sessions = api
    authenticate(client, sessions, scenario.owner)

    response = client.get("/api/workspaces")

    assert roles(response.json()) == {
        "Apollo": "OWNER",
        "Cortex": "OWNER",
        "Shared": "VIEWER",  # held by the outsider, not by this caller
    }


def test_list_is_scoped_per_user(api, scenario):
    """The same endpoint returns a different set for a different caller."""
    client, sessions = api
    authenticate(client, sessions, scenario.outsider)

    response = client.get("/api/workspaces")

    assert names(response.json()) == ["Private Project", "Shared"]


def test_list_is_ordered_by_name(api, scenario):
    """Selector order must not depend on insertion or membership order."""
    client, sessions = api
    with sessions() as session:
        owner = session.get(User, scenario.owner.id)
        create_workspace(session, name="Zulu", owner=owner)
        create_workspace(session, name="Aardvark", owner=owner)
        session.commit()
    authenticate(client, sessions, scenario.owner)

    listed = names(client.get("/api/workspaces").json())

    assert listed == sorted(listed)
    assert listed[0] == "Aardvark"
    assert listed[-1] == "Zulu"


def test_list_is_empty_not_an_error_for_a_user_with_no_workspaces(api):
    """Belonging to nothing is a state the selector renders, not a failure."""
    client, sessions = api
    with sessions() as session:
        loner = make_user(session, "loner@example.test")
        session.commit()
    authenticate(client, sessions, loner)

    response = client.get("/api/workspaces")

    assert response.status_code == 200
    assert response.json() == []


def test_list_returns_the_fields_the_selector_needs(api, scenario):
    client, sessions = api
    authenticate(client, sessions, scenario.owner)

    entry = client.get("/api/workspaces").json()[0]

    assert set(entry) == {"id", "name", "description", "role", "created_at"}
    assert uuid.UUID(entry["id"])  # a parseable id to route with


# --------------------------------------------------------------------------
# Opening one workspace
# --------------------------------------------------------------------------


def test_owner_can_open_a_workspace_they_own(api, scenario):
    client, sessions = api
    authenticate(client, sessions, scenario.owner)

    response = client.get(f"/api/workspaces/{scenario.apollo.id}")

    assert response.status_code == 200
    assert response.json()["name"] == "Apollo"
    assert response.json()["role"] == "OWNER"


def test_viewer_can_open_a_workspace_they_do_not_own(api, scenario):
    """Authorisation is membership-based, not ownership-based."""
    client, sessions = api
    authenticate(client, sessions, scenario.owner)

    response = client.get(f"/api/workspaces/{scenario.shared.id}")

    assert response.status_code == 200
    assert response.json()["role"] == "VIEWER"


def test_editor_can_open_a_workspace_they_do_not_own(api, scenario):
    """Every role grants access, not just OWNER and VIEWER."""
    client, sessions = api
    with sessions() as session:
        grant(session, scenario.private, scenario.owner, Role.EDITOR)
        session.commit()
    authenticate(client, sessions, scenario.owner)

    response = client.get(f"/api/workspaces/{scenario.private.id}")

    assert response.status_code == 200
    assert response.json()["role"] == "EDITOR"


def test_opening_a_workspace_with_no_role_on_it_is_refused(api, scenario):
    """Hand-typing someone else's workspace id must not reveal it."""
    client, sessions = api
    authenticate(client, sessions, scenario.owner)

    response = client.get(f"/api/workspaces/{scenario.private.id}")

    assert response.status_code == 403
    assert response.json()["detail"] == "You do not have access to this workspace"


def test_a_workspace_that_does_not_exist_is_indistinguishable_from_a_forbidden_one(
    api, scenario
):
    """Differing responses would let anyone probe which workspace ids are real."""
    client, sessions = api
    authenticate(client, sessions, scenario.owner)

    forbidden = client.get(f"/api/workspaces/{scenario.private.id}")
    missing = client.get(f"/api/workspaces/{uuid.uuid4()}")

    assert missing.status_code == forbidden.status_code == 403
    assert missing.json() == forbidden.json()


def test_a_malformed_workspace_id_is_rejected_as_invalid(api, scenario):
    client, sessions = api
    authenticate(client, sessions, scenario.owner)

    response = client.get("/api/workspaces/not-a-uuid")

    assert response.status_code == 422


def test_revoking_a_membership_revokes_access(api, scenario):
    """Access follows the membership row, with nothing cached behind it."""
    client, sessions = api
    authenticate(client, sessions, scenario.owner)
    path = f"/api/workspaces/{scenario.shared.id}"
    assert client.get(path).status_code == 200

    with sessions() as session:
        membership = session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.user_id == scenario.owner.id,
                WorkspaceMembership.workspace_id == scenario.shared.id,
            )
        )
        session.delete(membership)
        session.commit()

    assert client.get(path).status_code == 403


# --------------------------------------------------------------------------
# Who the caller is
# --------------------------------------------------------------------------


def test_both_endpoints_require_a_signed_in_caller(api, scenario):
    client, _ = api

    for path in ("/api/workspaces", f"/api/workspaces/{scenario.apollo.id}"):
        response = client.get(path)

        assert response.status_code == 401, path
        assert response.json()["detail"] == "Not authenticated"


def test_an_unrecognised_session_token_is_not_authenticated(api, scenario):
    """A cookie that matches no session row must not be trusted."""
    client, _ = api
    client.cookies.set(settings.session_cookie_name, new_session_token())

    assert client.get("/api/workspaces").status_code == 401


def test_an_expired_session_cannot_load_workspaces(api, scenario):
    client, sessions = api
    authenticate(client, sessions, scenario.owner, expires_in=timedelta(seconds=-1))

    assert client.get("/api/workspaces").status_code == 401
    assert client.get(f"/api/workspaces/{scenario.apollo.id}").status_code == 401


def test_a_deactivated_user_cannot_load_workspaces(api, scenario):
    """Deactivating an account closes access even while its session is unexpired."""
    client, sessions = api
    authenticate(client, sessions, scenario.owner)
    assert client.get("/api/workspaces").status_code == 200

    with sessions() as session:
        user = session.get(User, scenario.owner.id)
        user.is_active = False
        session.commit()

    assert client.get("/api/workspaces").status_code == 401
    assert client.get(f"/api/workspaces/{scenario.apollo.id}").status_code == 401
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
