"""T-8.3: reading a Discord server's channels and message history.

Reads go through a **bot** token, not the installer's user token. Discord's HTTP
API will not return channel history for a user access token at all: the
``messages.read`` scope exists only for local RPC against the desktop client,
and ``GET /channels/{id}/messages`` requires a bot that is a member of the guild
with View Channel + Read Message History. That is why ``app.sources.chat_oauth``
discards what the exchange returns and the install flow exists only to add the
bot to a guild -- see ``app.models.source_credential``.

Pagination runs *backwards*. Discord has no cursor and no page links; it takes
``before=<message id>`` and returns up to 100 newer-to-older messages, so each
page is anchored on the oldest id of the one before it. Snowflake ids are
monotonic, which is what makes that safe.

One more trap worth knowing: ``content`` comes back empty for every message
unless the application has the Message Content Intent enabled in the Discord
developer portal. Nothing in the API says so -- the request succeeds and the
text is just blank.
"""

import time
import uuid
from collections.abc import Callable, Iterator
from typing import ClassVar

import httpx
from neo4j import Driver
from pydantic import BaseModel, ConfigDict, ValidationError

from app.sources.base import (
    KIND_DISCORD,
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

API_BASE = "https://discord.com/api/v10"
PAGE_LIMIT = 100
#: Channel types that hold readable text. 0 = guild text, 5 = announcements,
#: 11/12 = public and private threads.
TEXT_CHANNEL_TYPES = frozenset({0, 5, 11, 12})


class _Payload(BaseModel):
    model_config = ConfigDict(extra="ignore")


class DiscordChannelPayload(_Payload):
    id: str
    name: str = ""
    type: int = 0


class DiscordAuthorPayload(_Payload):
    id: str
    username: str = ""
    global_name: str | None = None

    @property
    def display(self) -> str:
        return self.global_name or self.username or self.id


class DiscordMessagePayload(_Payload):
    id: str
    content: str = ""
    timestamp: str
    author: DiscordAuthorPayload | None = None
    #: Set when this message is a reply; Discord nests the whole parent.
    referenced_message: "DiscordReferencePayload | None" = None


class DiscordReferencePayload(_Payload):
    id: str


DiscordMessagePayload.model_rebuild()


class DiscordClient:
    """Thin bot-token client over the handful of endpoints ingestion needs."""

    def __init__(
        self,
        token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 3,
        max_rate_limit_wait: float = 60,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._http = httpx.Client(
            base_url=API_BASE,
            headers={"Authorization": f"Bot {token}"},
            transport=transport,
            timeout=30,
        )
        self._max_retries = max_retries
        self._max_wait = max_rate_limit_wait
        self._sleep = sleep

    def close(self) -> None:
        self._http.close()

    def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            resp = self._http.get(path, params=params)
            if resp.status_code != 429:
                break
            # Discord sends the wait in seconds, as a float, in the body or the
            # header. Honouring it is not optional: ignoring a 429 escalates to
            # a temporary ban on the whole application.
            wait = _retry_after(resp)
            if wait > self._max_wait or attempt == self._max_retries:
                raise SourceRateLimited(wait)
            self._sleep(wait)
        if resp.status_code in (401, 403):
            # A revoked bot token and a bot that was kicked from the guild are
            # the same answer to the caller: re-authorise, do not retry.
            raise SourceUnauthorized(
                "Discord rejected the bot token, or the bot is no longer in this server"
            )
        if resp.status_code == 404:
            raise SourceNotFound(f"Discord returned 404 for {path}")
        if resp.status_code >= 400:
            raise SourceAPIError(f"Discord returned {resp.status_code} for {path}")
        return resp

    def _json(self, path: str, params: dict | None = None):
        try:
            return self._get(path, params).json()
        except ValueError as e:
            raise SourceAPIError("Discord returned a malformed response") from e

    def fetch_guild_name(self, guild_id: str) -> str:
        body = self._json(f"/guilds/{guild_id}")
        return str(body.get("name") or guild_id) if isinstance(body, dict) else guild_id

    def list_text_channels(self, guild_id: str) -> list[DiscordChannelPayload]:
        body = self._json(f"/guilds/{guild_id}/channels")
        if not isinstance(body, list):
            raise SourceAPIError("Discord returned a malformed channel list")
        try:
            channels = [DiscordChannelPayload.model_validate(c) for c in body]
        except ValidationError as e:
            raise SourceAPIError("Discord returned a malformed channel list") from e
        return [c for c in channels if c.type in TEXT_CHANNEL_TYPES]

    def iter_messages(
        self, channel_id: str, *, max_messages: int
    ) -> Iterator[DiscordMessagePayload]:
        """Newest first, walking backwards with ``before``."""
        before: str | None = None
        seen = 0
        while seen < max_messages:
            params = {"limit": min(PAGE_LIMIT, max_messages - seen)}
            if before is not None:
                params["before"] = before
            body = self._json(f"/channels/{channel_id}/messages", params)
            if not isinstance(body, list):
                raise SourceAPIError("Discord returned a malformed message page")
            if not body:
                return
            try:
                page = [DiscordMessagePayload.model_validate(m) for m in body]
            except ValidationError as e:
                raise SourceAPIError("Discord returned a malformed message") from e
            yield from page
            seen += len(page)
            before = page[-1].id
            if len(page) < PAGE_LIMIT:
                return


def _retry_after(resp: httpx.Response) -> float:
    try:
        body = resp.json()
    except ValueError:
        body = {}
    if isinstance(body, dict) and "retry_after" in body:
        try:
            return float(body["retry_after"])
        except (TypeError, ValueError):
            pass
    header = resp.headers.get("Retry-After")
    try:
        return float(header) if header is not None else 1.0
    except ValueError:
        return 1.0


def message_url(guild_id: str, channel_id: str, message_id: str) -> str:
    """The permalink Discord's own "Copy Message Link" produces (US-08 AC4)."""
    return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"


class DiscordAdapter(SourceAdapter):
    kind: ClassVar[str] = KIND_DISCORD

    #: Per channel, per sync. A busy server would otherwise pull an unbounded
    #: history into one synchronous request; the newest slice is what a team is
    #: looking for and a later sync picks up anything newer.
    MAX_MESSAGES_PER_CHANNEL = 500

    def __init__(
        self,
        client: DiscordClient,
        *,
        guild_id: str,
        guild_name: str,
        channel_ids: list[str],
    ):
        self._client = client
        self._guild_id = guild_id
        self._guild_name = guild_name
        self._channel_ids = channel_ids

    def fetch(self) -> FetchedSource:
        available = {c.id: c for c in self._client.list_text_channels(self._guild_id)}
        chosen = [cid for cid in self._channel_ids if cid in available]
        if not chosen:
            raise SourceNotFound(
                "none of the selected channels exist in this server, "
                "or the bot cannot see them"
            )

        channels: list[ChatChannel] = []
        messages: list[ChatMessage] = []
        authors: dict[str, ChatAuthor] = {}

        for channel_id in chosen:
            payload = available[channel_id]
            channels.append(
                ChatChannel(
                    id=qualify(self.kind, channel_id),
                    name=payload.name or channel_id,
                    url=f"https://discord.com/channels/{self._guild_id}/{channel_id}",
                )
            )
            for message in self._client.iter_messages(
                channel_id, max_messages=self.MAX_MESSAGES_PER_CHANNEL
            ):
                author_id = None
                if message.author is not None:
                    author_id = qualify(self.kind, message.author.id)
                    authors[author_id] = ChatAuthor(
                        id=author_id, login=message.author.display
                    )
                reply_to = (
                    qualify(self.kind, channel_id, message.referenced_message.id)
                    if message.referenced_message is not None
                    else None
                )
                messages.append(
                    ChatMessage(
                        id=qualify(self.kind, channel_id, message.id),
                        channel_id=qualify(self.kind, channel_id),
                        body=message.content,
                        url=message_url(self._guild_id, channel_id, message.id),
                        created_at=message.timestamp,
                        author_id=author_id,
                        reply_to_id=reply_to,
                    )
                )

        return FetchedSource(
            external_ref=self._guild_id,
            display_ref=self._guild_name,
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
            source_ref=self._guild_id,
            channels=fetched.payloads["channels"],
            authors=fetched.payloads["authors"],
            messages=fetched.payloads["messages"],
        )

    def describe(self, error: SourceError) -> str:
        if isinstance(error, SourceRateLimited):
            return "Discord rate limit reached"
        if isinstance(error, SourceUnauthorized):
            return (
                "Discord rejected the bot token, or the bot was removed from "
                f"{self._guild_name}. Reconnect the server."
            )
        if isinstance(error, SourceNotFound):
            return f"Could not read the selected channels in {self._guild_name}"
        return str(error)

    def close(self) -> None:
        self._client.close()
