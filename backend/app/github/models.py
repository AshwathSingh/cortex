"""Pydantic models that validate and normalize raw GitHub PR/issue payloads.

Only the fields Cortex stores are kept; everything else GitHub sends is ignored.
A payload missing a required field raises ``pydantic.ValidationError`` so bad
data is rejected before anything is written to the graph.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class _Payload(BaseModel):
    model_config = ConfigDict(extra="ignore")


class GitHubUser(_Payload):
    id: int
    login: str
    html_url: str | None = None


class _Item(_Payload):
    id: int
    number: int
    title: str
    state: Literal["open", "closed"]
    body: str = ""
    html_url: str  # provenance link back to the source
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None
    user: GitHubUser | None = None  # GitHub returns null for deleted accounts

    @field_validator("body", mode="before")
    @classmethod
    def _null_body_to_empty(cls, v):
        return "" if v is None else v


class PullRequestPayload(_Item):
    merged_at: datetime | None = None
    draft: bool = False


class IssuePayload(_Item):
    pass
