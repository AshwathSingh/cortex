from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.db.base import Base
from app.db.postgres import get_session
from app.main import app
from app.models import User, UserSession


@pytest.fixture
def auth_client() -> Iterator[tuple[TestClient, sessionmaker[Session]]]:
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
        with TestClient(app) as client:
            yield client, test_sessions
    finally:
        settings.secure_cookies = original_secure_cookies
        app.dependency_overrides.pop(get_session, None)
        Base.metadata.drop_all(engine)
        engine.dispose()


def signup(client: TestClient, email: str = "developer@example.com"):
    return client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "a-secure-password-with-15-characters",
            "display_name": "Developer",
        },
    )


def test_signup_creates_session_and_owner_workspace(auth_client):
    client, test_sessions = auth_client

    response = signup(client)

    assert response.status_code == 201
    assert response.json()["email"] == "developer@example.com"
    assert "HttpOnly" in response.headers["set-cookie"]
    assert client.get("/api/auth/me").status_code == 200

    workspaces = client.get("/api/workspaces")
    assert workspaces.status_code == 200
    assert workspaces.json()[0]["name"] == "Developer's Workspace"
    assert workspaces.json()[0]["role"] == "OWNER"

    raw_token = client.cookies.get(settings.session_cookie_name)
    with test_sessions() as session:
        user = session.scalar(select(User))
        stored_session = session.scalar(select(UserSession))
        assert user is not None
        assert user.password_hash != "a-secure-password-with-15-characters"
        assert stored_session is not None
        assert stored_session.token_hash != raw_token


def test_login_rejects_bad_password_and_logout_revokes_session(auth_client):
    client, _ = auth_client
    assert signup(client).status_code == 201
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401

    bad_login = client.post(
        "/api/auth/login",
        json={"email": "developer@example.com", "password": "wrong-password"},
    )
    assert bad_login.status_code == 401

    login = client.post(
        "/api/auth/login",
        json={
            "email": "DEVELOPER@example.com",
            "password": "a-secure-password-with-15-characters",
        },
    )
    assert login.status_code == 200
    assert client.get("/api/workspaces").status_code == 200


def test_signup_rejects_duplicate_email(auth_client):
    client, _ = auth_client
    assert signup(client).status_code == 201

    duplicate = signup(client, email="DEVELOPER@example.com")

    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "An account with this email already exists"}
