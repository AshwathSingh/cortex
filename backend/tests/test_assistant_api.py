"""Assistant API contract, authorization, validation, and failure handling."""

import asyncio

import pytest

from app.api.assistant import (
    assistant_rate_limiter,
    get_assistant_provider,
)
from app.config import settings
from app.main import app
from app.models import Role
from app.services.assistant import (
    AssistantAnswer,
    AssistantCitation,
    AssistantProviderError,
)
from tests.authz import sign_in_with_role
from tests.payloads import TEST_WORKSPACE_ID

URL = f"/api/workspaces/{TEST_WORKSPACE_ID}/assistant/query"


class RecordingProvider:
    def __init__(self):
        self.calls = []

    async def answer(self, **kwargs):
        self.calls.append(kwargs)
        return AssistantAnswer(
            answer="A grounded placeholder answer.",
            citations=(
                AssistantCitation(
                    id="workspace-graph",
                    kind="graph",
                    label="Graph explorer",
                    description="Inspect entities and relationships",
                ),
            ),
        )


class UnavailableProvider:
    async def answer(self, **kwargs):
        del kwargs
        raise AssistantProviderError("upstream secret must not reach the client")


class SlowProvider:
    async def answer(self, **kwargs):
        del kwargs
        await asyncio.sleep(1)
        raise AssertionError("timeout should cancel this provider")


@pytest.fixture(autouse=True)
def reset_assistant_dependencies():
    original_limit = assistant_rate_limiter.limit
    original_timeout = settings.assistant_timeout_seconds
    assistant_rate_limiter.reset()
    yield
    assistant_rate_limiter.limit = original_limit
    assistant_rate_limiter.reset()
    settings.assistant_timeout_seconds = original_timeout
    app.dependency_overrides.pop(get_assistant_provider, None)


def setup(api_db, *, role=Role.OWNER, provider=None):
    client, sessions = api_db
    provider = provider or RecordingProvider()
    app.dependency_overrides[get_assistant_provider] = lambda: provider
    if role is not None:
        sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, role)
    return client, sessions, provider


def test_unauthenticated_request_is_rejected_before_provider(api_db):
    client, _, provider = setup(api_db, role=None)
    response = client.post(URL, json={"question": "Why Neo4j?"})
    assert response.status_code == 401
    assert provider.calls == []


def test_non_member_cannot_query_or_discover_workspace(api_db):
    client, sessions, provider = setup(api_db, role=None)
    sign_in_with_role(client, sessions, TEST_WORKSPACE_ID, None)
    response = client.post(URL, json={"question": "Why Neo4j?"})
    assert response.status_code == 403
    assert response.json()["detail"] == "You do not have access to this workspace"
    assert provider.calls == []


@pytest.mark.parametrize("role", [Role.OWNER, Role.EDITOR, Role.VIEWER])
def test_every_workspace_member_can_query_assistant(api_db, role):
    client, _, provider = setup(api_db, role=role)
    response = client.post(
        URL,
        json={
            "question": "  Why Neo4j?  ",
            "history": [
                {"role": "user", "content": "What database do we use?"},
                {"role": "assistant", "content": "The project uses Neo4j."},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "answer": "A grounded placeholder answer.",
        "citations": [
            {
                "id": "workspace-graph",
                "kind": "graph",
                "label": "Graph explorer",
                "description": "Inspect entities and relationships",
            }
        ],
    }
    assert provider.calls[0]["question"] == "Why Neo4j?"
    assert [message.role for message in provider.calls[0]["history"]] == [
        "user",
        "assistant",
    ]


@pytest.mark.parametrize(
    "body",
    [
        {"question": "   "},
        {"question": "x" * 4_001},
        {
            "question": "valid",
            "history": [{"role": "user", "content": "x"}] * 21,
        },
        {
            "question": "valid",
            "history": [
                {"role": "user", "content": "x" * 4_000}
            ] * 5,
        },
    ],
)
def test_invalid_or_oversized_requests_never_reach_provider(api_db, body):
    client, _, provider = setup(api_db)
    response = client.post(URL, json=body)
    assert response.status_code == 422
    assert provider.calls == []


def test_provider_timeout_returns_safe_retryable_error(api_db):
    client, _, _ = setup(api_db, provider=SlowProvider())
    settings.assistant_timeout_seconds = 0.01
    response = client.post(URL, json={"question": "Why Neo4j?"})
    assert response.status_code == 504
    assert response.json()["detail"] == (
        "The assistant took too long to respond. Please try again."
    )


def test_provider_failure_does_not_leak_internal_details(api_db):
    client, _, _ = setup(api_db, provider=UnavailableProvider())
    response = client.post(URL, json={"question": "Why Neo4j?"})
    assert response.status_code == 503
    assert response.json()["detail"] == (
        "The assistant is temporarily unavailable. Please try again."
    )
    assert "secret" not in response.text


def test_rate_limit_is_scoped_to_authenticated_user_and_workspace(api_db):
    client, _, provider = setup(api_db)
    assistant_rate_limiter.limit = 1

    assert client.post(URL, json={"question": "First"}).status_code == 200
    response = client.post(URL, json={"question": "Second"})
    assert response.status_code == 429
    assert response.headers["retry-after"]
    assert len(provider.calls) == 1
