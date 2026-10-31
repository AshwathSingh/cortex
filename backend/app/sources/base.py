"""T-8.1: the provider-independent contract every data source implements.

US-7 wired GitHub straight into ``POST /api/ingest/github``: the endpoint knew
GitHub's exception names, GitHub's pagination and GitHub's graph writer. Adding
Slack and Discord that way would have produced three endpoints each repeating
the same sync-record bookkeeping (US-10) with a different provider's error
taxonomy, and three chances to get the lease handling subtly different.

So the pipeline is split in two. An adapter knows one provider: how to read it
(``fetch``) and how its payloads become graph nodes (``write``). Everything that
is *not* provider-specific -- authorisation, the ``data_sources`` lease, which
HTTP status a failure maps to -- lives once, in ``app.sources.pipeline`` and
``app.api.ingest``.

The error classes here are that seam. ``app.github.client``'s own exceptions
subclass them, so US-7's error handling is unchanged while the endpoint stops
naming GitHub at all.
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

from neo4j import Driver

#: ``DataSource.kind`` values. Free-form in the column by design (see
#: ``app.models.data_source``), enumerated here so the API and the adapters
#: cannot disagree about the spelling.
KIND_GITHUB = "github"
KIND_SLACK = "slack"
KIND_DISCORD = "discord"


class SourceError(Exception):
    """Base for every failure an adapter reports to the pipeline."""


class InvalidSourceRef(SourceError, ValueError):
    """The caller's reference to the source is not one this provider can parse.

    Subclasses ``ValueError`` because US-7's ``InvalidRepoURL`` already did, and
    callers outside the API catch it that way.
    """


class SourceNotFound(SourceError):
    """The provider says the repository, channel or server does not exist, or
    the token cannot see it. The two are deliberately one case: distinguishing
    them would tell a caller which private resources exist."""


class SourceUnauthorized(SourceError):
    """The stored credential was rejected -- revoked, expired or never granted
    the scope this read needs. Re-authorising is the only fix, so this is not
    retried."""


class SourceRateLimited(SourceError):
    def __init__(self, wait_seconds: float):
        super().__init__(f"rate limited; would need to wait {wait_seconds:.0f}s")
        self.wait_seconds = wait_seconds


class SourceAPIError(SourceError):
    """The provider answered, but not with anything usable."""


@dataclass(frozen=True)
class FetchedSource:
    """What one adapter read, before any of it reaches the graph.

    ``external_ref`` is the ``data_sources`` key and must be stable for the life
    of the connection -- it is what a re-sync matches on, so it cannot be a
    display name a user can rename. ``counts`` is reported back to the caller
    verbatim, which is why it is a dict rather than fixed fields: a repository
    counts pull requests and issues, a Slack workspace counts channels and
    messages, and the endpoint should not need to know which.
    """

    external_ref: str
    display_ref: str
    counts: dict[str, int] = field(default_factory=dict)
    #: Raw provider payloads, grouped however the adapter's ``write`` wants them.
    #: Never serialised to a response.
    payloads: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


class SourceAdapter(ABC):
    """One provider's half of the ingestion pipeline.

    Instances are per-request and own their HTTP client, so ``close`` is part of
    the contract: the pipeline calls it on every exit path. Nothing here touches
    Postgres -- the sync record is the pipeline's job, and an adapter that wrote
    its own would make the lease unenforceable.
    """

    kind: ClassVar[str]

    @abstractmethod
    def fetch(self) -> FetchedSource:
        """Read everything this source currently holds.

        Raises one of the ``Source*`` errors above. Must not write to the graph:
        a provider failure half way through has to leave the previous ingestion's
        nodes untouched.
        """

    @abstractmethod
    def write(
        self,
        driver: Driver,
        fetched: FetchedSource,
        *,
        workspace_id: str | uuid.UUID,
    ) -> None:
        """Validate the payloads and write them in one transaction.

        All-or-nothing, like US-7's ``write_graph``: a failed ingestion must
        leave zero new nodes, because the ``data_sources`` row is then the only
        record that the attempt happened at all.
        """

    def describe(self, error: SourceError) -> str:
        """The user-facing wording for a failure of this provider.

        Whatever this returns is both the HTTP ``detail`` and the ``last_error``
        stored against the source, so the sentence on the Sources page is the one
        the request got back rather than a second, differently worded version of
        it. The default is the exception's own message, which is fine for
        anything already phrased for a reader.
        """
        return str(error)

    def close(self) -> None:
        """Release resources the adapter itself created. Safe to call twice.

        An HTTP client handed in by a FastAPI dependency is *not* one of them --
        the dependency owns its lifetime. Only an adapter that constructed its
        own client overrides this.
        """
