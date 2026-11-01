"""Typed boundary between the assistant API and an answer provider.

The placeholder provider keeps US-34 deterministic. A hosted model adapter can
implement ``AssistantProvider`` later without changing the API or frontend.
Provider adapters must validate model output before constructing these types.
"""

import uuid
from dataclasses import dataclass
from typing import Literal, Protocol


CitationKind = Literal["graph", "sources"]
MessageRole = Literal["user", "assistant"]


@dataclass(frozen=True)
class AssistantMessage:
    role: MessageRole
    content: str


@dataclass(frozen=True)
class AssistantCitation:
    id: str
    kind: CitationKind
    label: str
    description: str


@dataclass(frozen=True)
class AssistantAnswer:
    answer: str
    citations: tuple[AssistantCitation, ...]


class AssistantProviderError(RuntimeError):
    """A safe, expected failure from an external assistant provider."""


class AssistantProvider(Protocol):
    async def answer(
        self,
        *,
        workspace_id: uuid.UUID,
        question: str,
        history: tuple[AssistantMessage, ...],
    ) -> AssistantAnswer: ...


class PlaceholderAssistantProvider:
    """Deterministic provider used until retrieval and an LLM are connected."""

    async def answer(
        self,
        *,
        workspace_id: uuid.UUID,
        question: str,
        history: tuple[AssistantMessage, ...],
    ) -> AssistantAnswer:
        del workspace_id, question, history
        return AssistantAnswer(
            answer=(
                "This placeholder demonstrates how Cortex will present a concise, "
                "evidence-backed answer. Once the assistant service is connected, "
                "each claim will be grounded in the project graph and its indexed "
                "sources."
            ),
            citations=(
                AssistantCitation(
                    id="workspace-graph",
                    kind="graph",
                    label="Graph explorer",
                    description="Inspect entities and relationships",
                ),
                AssistantCitation(
                    id="workspace-sources",
                    kind="sources",
                    label="Project sources",
                    description="Review the indexed source material",
                ),
            ),
        )
