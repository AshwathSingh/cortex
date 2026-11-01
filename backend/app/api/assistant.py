"""Authenticated, workspace-scoped Graph-Aware Assistant endpoint."""

import asyncio
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator

from app.api.deps import CurrentUser, DbSession, load_workspace_for_user
from app.api.rate_limit import RateLimiter
from app.config import settings
from app.services.assistant import (
    AssistantMessage,
    AssistantProvider,
    AssistantProviderError,
    PlaceholderAssistantProvider,
)

MAX_QUESTION_CHARS = 4_000
MAX_HISTORY_MESSAGES = 20
MAX_HISTORY_CHARS = 16_000

router = APIRouter(prefix="/api/workspaces", tags=["assistant"])
assistant_rate_limiter = RateLimiter(settings.assistant_rate_limit_per_minute)
_placeholder_provider = PlaceholderAssistantProvider()


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message content must not be blank")
        return value


class AssistantQueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    history: list[HistoryMessage] = Field(
        default_factory=list,
        max_length=MAX_HISTORY_MESSAGES,
    )

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be blank")
        return value

    @model_validator(mode="after")
    def history_must_fit_context_budget(self):
        if sum(len(message.content) for message in self.history) > MAX_HISTORY_CHARS:
            raise ValueError("conversation history is too large")
        return self


class AssistantCitationResponse(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    kind: Literal["graph", "sources"]
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=500)


class AssistantQueryResponse(BaseModel):
    answer: str = Field(min_length=1, max_length=40_000)
    citations: list[AssistantCitationResponse] = Field(max_length=20)


def get_assistant_provider() -> AssistantProvider:
    return _placeholder_provider


@router.post(
    "/{workspace_id}/assistant/query",
    response_model=AssistantQueryResponse,
)
async def query_assistant(
    workspace_id: uuid.UUID,
    body: AssistantQueryRequest,
    user: CurrentUser,
    session: DbSession,
    provider: Annotated[AssistantProvider, Depends(get_assistant_provider)],
) -> AssistantQueryResponse:
    load_workspace_for_user(session, user, workspace_id)
    assistant_rate_limiter.check(
        f"{user.id}:{workspace_id}",
        detail="Too many assistant requests. Please wait and try again.",
    )

    history = tuple(
        AssistantMessage(role=message.role, content=message.content)
        for message in body.history
    )
    try:
        result = await asyncio.wait_for(
            provider.answer(
                workspace_id=workspace_id,
                question=body.question,
                history=history,
            ),
            timeout=settings.assistant_timeout_seconds,
        )
    except TimeoutError as error:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="The assistant took too long to respond. Please try again.",
        ) from error
    except AssistantProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The assistant is temporarily unavailable. Please try again.",
        ) from error

    return AssistantQueryResponse(
        answer=result.answer,
        citations=[
            AssistantCitationResponse(
                id=citation.id,
                kind=citation.kind,
                label=citation.label,
                description=citation.description,
            )
            for citation in result.citations
        ],
    )
