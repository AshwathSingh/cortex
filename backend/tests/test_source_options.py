import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from app.config import settings
from app.models import Role
from tests.authz import sign_in_with_role
from tests.payloads import TEST_WORKSPACE_ID

URL = f"/api/workspaces/{TEST_WORKSPACE_ID}/sources/options"


@pytest.mark.parametrize("role, expected", [(None, 401), ("nonmember", 403)])
def test_source_availability_requires_workspace_membership(api_db, role, expected):
    client, sessions = api_db
    if role:
        sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, None)
    assert client.get(URL).status_code == expected


@pytest.mark.parametrize(
    "role, may_manage", [(Role.OWNER, True), (Role.EDITOR, True), (Role.VIEWER, False)]
)
def test_source_options_explain_availability_and_permission(
    api_db, monkeypatch, role, may_manage
):
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, role)
    monkeypatch.setattr(settings, "slack_client_id", None)
    monkeypatch.setattr(settings, "discord_bot_token", None)
    monkeypatch.setattr(settings, "github_token", None)
    data = client.get(URL).json()
    assert data["can_manage_sources"] is may_manage
    providers = {item["kind"]: item for item in data["providers"]}
    assert set(providers) == {"github", "upload", "slack", "discord"}
    assert providers["github"]["available"] and providers["upload"]["available"]
    assert not providers["slack"]["available"] and not providers["discord"]["available"]
    assert "not configured" in providers["slack"]["reason"]


def test_configured_providers_are_available_without_exposing_credentials(
    api_db, monkeypatch
):
    client, sessions = api_db
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, Role.EDITOR)
    monkeypatch.setattr(
        settings, "token_encryption_key", SecretStr(Fernet.generate_key().decode())
    )
    monkeypatch.setattr(settings, "slack_client_id", "private-slack-client")
    monkeypatch.setattr(
        settings, "slack_client_secret", SecretStr("private-slack-secret")
    )
    monkeypatch.setattr(settings, "discord_client_id", "private-discord-client")
    monkeypatch.setattr(
        settings, "discord_client_secret", SecretStr("private-discord-secret")
    )
    monkeypatch.setattr(settings, "discord_bot_token", SecretStr("private-discord-bot"))
    response = client.get(URL)
    assert response.status_code == 200
    assert all(
        item["available"] and item["reason"] is None
        for item in response.json()["providers"]
    )
    assert "private-" not in response.text
