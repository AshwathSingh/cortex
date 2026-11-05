"""T-8.4: reading a Slack workspace's channels, history and thread replies.

Reads use the bot token the install exchange returned, scoped to that team (see
``app.sources.chat_oauth``). Three things about Slack's API shape the code:

*Every* call answers HTTP 200. Success and failure are both ``{"ok": …}`` in the
body, so the status code tells you nothing and ``_call`` has to branch on
``ok``. A missing scope, a revoked token and a channel the bot was never
invited to all arrive as 200.

Pagination is cursor-based: ``response_metadata.next_cursor`` is a string that
is *absent or empty* on the last page, never null-and-present, so the loop
tests for truthiness rather than for the key.

Thread replies do not appear in ``conversations.history`` -- it returns only
thread parents, each carrying ``thread_ts`` and ``reply_count``. Pulling the
replies means one ``conversations.replies`` call per thread, which is why only
parents with replies are followed. ``conversations.replies`` echoes the parent
back as the first element, so it is skipped to avoid writing it twice.

A message timestamp (``ts``) is unique only within a channel, which is why
``app.sources.chat_graph`` builds message ids as ``slack/<channel>/<ts>``.
"""

import time
import uuid
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from typing import Any, ClassVar

import httpx
from neo4j import Driver
from pydantic import BaseModel, ConfigDict, ValidationError

from app.sources.base import (
    KIND_SLACK,
    FetchedSource,
    SourceAdapter,
    SourceAPIError,
    SourceError,
    SourceNotFound,
    SourceRateLimited,
    SourceUnauthorized,
)
from app.sources.chat_graph import (
    ChatAuthor,
    ChatChannel,
    ChatMessage,
    qualify,
    write_chat_graph,
)

API_BASE = "https://slack.com/api"
PAGE_LIMIT = 200

#: Slack errors that mean the credential will never work again, so the answer is
#: to re-authorise rather than to retry. ``missing_scope`` is included
#: deliberately: the installed token is permanently short of what reading needs,
#: and only a fresh install with the right scopes fixes it.
AUTH_ERRORS = frozenset(
    {
        "invalid_auth",
        "account_inactive",
        "token_revoked",
        "token_expired",
        "not_authed",
        "missing_scope",
        "no_permission",
    }
)

#: Errors that mean "this channel, not your token".
NOT_FOUND_ERRORS = frozenset(
    {"channel_not_found", "not_in_channel", "is_archived"}
)


class _Payload(BaseModel):
    model_config = ConfigDict(extra="ignore")


class SlackChannelPayload(_Payload):
    id: str
    name: str = ""
    is_archived: bool = False


class SlackMessagePayload(_Payload):
    #: Slack's per-channel message timestamp, e.g. "1730000000.123456".
    ts: str
    text: str = ""
    user: str | None = None
    #: Present on every message in a thread, including the parent, where it
    #: equals ``ts``.
    thread_ts: str | None = None
    reply_count: int = 0
    #: Joins, leaves, channel topic changes and the like. Not authored content.
    subtype: str | None = None


class SlackUserPayload(_Payload):
    id: str
    name: str = ""
    real_name: str | None = None
    profile: dict[str, Any] = {}

    @property
    def display(self) -> str:
        display = self.profile.get("display_name") if self.profile else None
        return display or self.real_name or self.name or self.id


class SlackClient:
    def __init__(
        self,
        token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 3,
        max_rate_limit_wait: float = 120,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._http = httpx.Client(
            base_url=API_BASE,
            headers={"Authorization": f"Bearer {token}"},
            transport=transport,
            timeout=30,
        )
        self._max_retries = max_retries
        self._max_wait = max_rate_limit_wait
        self._sleep = sleep

    def close(self) -> None:
        self._http.close()

    def _call(self, method: str, params: dict | None = None) -> dict:
        for attempt in range(self._max_retries + 1):
            resp = self._http.get(f"/{method}", params=params)
            if resp.status_code == 429:
                wait = _retry_after(resp)
                if wait > self._max_wait or attempt == self._max_retries:
                    raise SourceRateLimited(wait)
                self._sleep(wait)
                continue
            if resp.status_code >= 400:
                raise SourceAPIError(
                    f"Slack returned {resp.status_code} for {method}"
                )
            break
        else:  # pragma: no cover - the loop always breaks or raises
            raise SourceAPIError(f"Slack did not answer {method}")

        try:
            body = resp.json()
        except ValueError as e:
            raise SourceAPIError(f"Slack returned a malformed response for {method}") from e
        if not isinstance(body, dict):
            raise SourceAPIError(f"Slack returned a malformed response for {method}")
        if body.get("ok"):
            return body

        # Slack reports every failure as HTTP 200 with ok=false.
        error = str(body.get("error", "unknown_error"))
        if error == "ratelimited":
            raise SourceRateLimited(_retry_after(resp))
        if error in AUTH_ERRORS:
            raise SourceUnauthorized(f"Slack rejected the request: {error}")
        if error in NOT_FOUND_ERRORS:
            raise SourceNotFound(f"Slack says: {error}")
        raise SourceAPIError(f"Slack returned an error: {error}")

    def _paginate(self, method: str, params: dict, key: str) -> Iterator[dict]:
        cursor: str | None = None
        while True:
            page = dict(params, limit=PAGE_LIMIT)
            if cursor:
                page["cursor"] = cursor
            body = self._call(method, page)
            items = body.get(key) or []
            if not isinstance(items, list):
                raise SourceAPIError(f"Slack returned a malformed {key} page")
            yield from items
            # Absent or empty on the last page, never null-and-present.
            cursor = (body.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                return

    def list_channels(self) -> list[SlackChannelPayload]:
        """Public and private channels the bot can read."""
        raw = self._paginate(
            "conversations.list",
            {"types": "public_channel,private_channel", "exclude_archived": "true"},
            "channels",
        )
        try:
            channels = [SlackChannelPayload.model_validate(c) for c in raw]
        except ValidationError as e:
            raise SourceAPIError("Slack returned a malformed channel list") from e
        return [c for c in channels if not c.is_archived]

    def iter_history(
        self, channel_id: str, *, max_messages: int
    ) -> Iterator[SlackMessagePayload]:
        seen = 0
        for raw in self._paginate(
            "conversations.history", {"channel": channel_id}, "messages"
        ):
            if seen >= max_messages:
                return
            try:
                message = SlackMessagePayload.model_validate(raw)
            except ValidationError as e:
                raise SourceAPIError("Slack returned a malformed message") from e
            seen += 1
            yield message

    def iter_replies(
        self, channel_id: str, thread_ts: str
    ) -> Iterator[SlackMessagePayload]:
        for raw in self._paginate(
            "conversations.replies", {"channel": channel_id, "ts": thread_ts}, "messages"
        ):
            try:
                message = SlackMessagePayload.model_validate(raw)
            except ValidationError as e:
                raise SourceAPIError("Slack returned a malformed reply") from e
            # The endpoint echoes the parent back as the first element.
            if message.ts == thread_ts:
                continue
            yield message

    def fetch_users(self) -> dict[str, SlackUserPayload]:
        """Every user in the team, keyed by id.

        One call for the whole team rather than ``users.info`` per author: a
        busy channel has far more messages than posters, and Slack's per-method
        rate limits are tight.
        """
        users: dict[str, SlackUserPayload] = {}
        for raw in self._paginate("users.list", {}, "members"):
            try:
                user = SlackUserPayload.model_validate(raw)
            except ValidationError:
                # A malformed member is not worth failing a whole ingestion for;
                # the message still lands, just without a resolved author name.
                continue
            users[user.id] = user
        return users


def _retry_after(resp: httpx.Response) -> float:
    header = resp.headers.get("Retry-After")
    try:
        return float(header) if header is not None else 1.0
    except ValueError:
        return 1.0


def message_url(channel_id: str, ts: str) -> str:
    """A link that opens the message in Slack (US-08 AC4).

    ``app_redirect`` rather than the ``/archives/`` permalink: the archive form
    needs the team's own subdomain, which the OAuth exchange does not return and
    which would cost an extra scope (``team:read``) to look up.
    """
    return f"https://slack.com/app_redirect?channel={channel_id}&message_ts={ts}"


class SlackAdapter(SourceAdapter):
    kind: ClassVar[str] = KIND_SLACK

    #: Per channel, per sync -- the newest slice. See DiscordAdapter.
    MAX_MESSAGES_PER_CHANNEL = 500
    #: Threads followed per channel, newest first. Each costs its own API call.
    MAX_THREADS_PER_CHANNEL = 50

    def __init__(
        self,
        client: SlackClient,
        *,
        team_id: str,
        team_name: str,
        channel_ids: list[str],
    ):
        self._client = client
        self._team_id = team_id
        self._team_name = team_name
        self._channel_ids = channel_ids

    def fetch(self) -> FetchedSource:
        available = {c.id: c for c in self._client.list_channels()}
        chosen = [cid for cid in self._channel_ids if cid in available]
        if not chosen:
            raise SourceNotFound(
                "none of the selected channels exist in this workspace, "
                "or Cortex has not been invited to them"
            )

        users = self._client.fetch_users()
        channels: list[ChatChannel] = []
        messages: list[ChatMessage] = []
        authors: dict[str, ChatAuthor] = {}

        def record(channel_id: str, payload: SlackMessagePayload) -> None:
            author_id = None
            if payload.user:
                author_id = qualify(self.kind, payload.user)
                user = users.get(payload.user)
                authors[author_id] = ChatAuthor(
                    id=author_id,
                    login=user.display if user else payload.user,
                )
            parent = payload.thread_ts
            reply_to = (
                qualify(self.kind, channel_id, parent)
                if parent and parent != payload.ts
                else None
            )
            messages.append(
                ChatMessage(
                    id=qualify(self.kind, channel_id, payload.ts),
                    channel_id=qualify(self.kind, channel_id),
                    body=payload.text,
                    url=message_url(channel_id, payload.ts),
                    created_at=_iso(payload.ts),
                    author_id=author_id,
                    reply_to_id=reply_to,
                )
            )

        for channel_id in chosen:
            payload = available[channel_id]
            channels.append(
                ChatChannel(
                    id=qualify(self.kind, channel_id),
                    name=payload.name or channel_id,
                    url=f"https://slack.com/app_redirect?channel={channel_id}",
                )
            )
            threads: list[str] = []
            for message in self._client.iter_history(
                channel_id, max_messages=self.MAX_MESSAGES_PER_CHANNEL
            ):
                # Joins, leaves and topic changes are channel noise, not content.
                if message.subtype is not None:
                    continue
                record(channel_id, message)
                if message.reply_count and len(threads) < self.MAX_THREADS_PER_CHANNEL:
                    threads.append(message.thread_ts or message.ts)

            for thread_ts in threads:
                for reply in self._client.iter_replies(channel_id, thread_ts):
                    if reply.subtype is not None:
                        continue
                    record(channel_id, reply)

        return FetchedSource(
            external_ref=self._team_id,
            display_ref=self._team_name,
            counts={"channels": len(channels), "messages": len(messages)},
            payloads={
                "channels": channels,
                "authors": list(authors.values()),
                "messages": messages,
            },
        )

    def write(
        self,
        driver: Driver,
        fetched: FetchedSource,
        *,
        workspace_id: str | uuid.UUID,
    ) -> None:
        write_chat_graph(
            driver,
            workspace_id=workspace_id,
            kind=self.kind,
            source_ref=self._team_id,
            channels=fetched.payloads["channels"],
            authors=fetched.payloads["authors"],
            messages=fetched.payloads["messages"],
        )

    def describe(self, error: SourceError) -> str:
        if isinstance(error, SourceRateLimited):
            return "Slack rate limit reached"
        if isinstance(error, SourceUnauthorized):
            return (
                f"Slack rejected Cortex's access to {self._team_name}. "
                "Reconnect the Slack workspace."
            )
        if isinstance(error, SourceNotFound):
            return f"Could not read the selected channels in {self._team_name}"
        return str(error)

    def close(self) -> None:
        self._client.close()


def _iso(ts: str) -> str:
    """Slack's epoch-seconds timestamp as ISO-8601, to match every other node."""
    try:
        seconds = float(ts)
    except ValueError:
        return ts
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
