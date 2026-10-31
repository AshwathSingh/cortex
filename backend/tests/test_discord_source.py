"""T-8.3: the Discord client and adapter.

Discord is faked with an httpx MockTransport, the approach `test_github_client`
uses. What matters here is the pagination (backwards, anchored on message ids),
the error mapping, and that reads go through a *bot* token -- a user token
cannot read channel history at all, which is the whole reason this provider
works differently from Slack.
"""

import httpx
import pytest

from app.sources.base import (
    SourceAPIError,
    SourceNotFound,
    SourceRateLimited,
    SourceUnauthorized,
)
from app.sources.discord import (
    PAGE_LIMIT,
    DiscordAdapter,
    DiscordClient,
    message_url,
)

WS = "ccccccc0-0000-4000-8000-00000000c0de"
GUILD = "912340000000000000"

CHANNELS = [
    {"id": "100", "name": "general", "type": 0},
    {"id": "101", "name": "announcements", "type": 5},
    {"id": "102", "name": "Voice", "type": 2},  # not text; must be filtered out
]


def msg(mid: str, *, content="hello", author="7001", reply_to=None) -> dict:
    payload = {
        "id": mid,
        "content": content,
        "timestamp": "2026-10-31T09:00:00+00:00",
        "author": {"id": author, "username": "ada", "global_name": "Ada L"},
    }
    if reply_to is not None:
        payload["referenced_message"] = {"id": reply_to}
    return payload


def client(handler, **over) -> DiscordClient:
    return DiscordClient(
        "bot-token",
        transport=httpx.MockTransport(handler),
        sleep=lambda s: None,
        **over,
    )


def adapter(handler, channel_ids=("100",), **over) -> DiscordAdapter:
    return DiscordAdapter(
        client(handler, **over),
        guild_id=GUILD,
        guild_name="Acme Guild",
        channel_ids=list(channel_ids),
    )


def routed(messages: dict[str, list[dict]]):
    """A handler serving the channel list plus per-channel message pages."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith(f"/guilds/{GUILD}/channels"):
            return httpx.Response(200, json=CHANNELS)
        for channel_id, pages in messages.items():
            if path.endswith(f"/channels/{channel_id}/messages"):
                before = request.url.params.get("before")
                if before is None:
                    return httpx.Response(200, json=pages)
                return httpx.Response(200, json=[])
        raise AssertionError(f"unexpected request to {path}")

    return handler


# -- The client ----------------------------------------------------------------


def test_reads_are_authorised_as_a_bot_not_a_user():
    """Discord will not return channel history for a user token at all."""
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json=CHANNELS)

    client(handler).list_text_channels(GUILD)

    assert seen["auth"] == "Bot bot-token"


def test_only_text_channels_are_offered():
    channels = client(lambda r: httpx.Response(200, json=CHANNELS)).list_text_channels(
        GUILD
    )

    assert [c.id for c in channels] == ["100", "101"]


def test_history_pages_backwards_anchored_on_the_oldest_id():
    """Discord has no cursor: each page is anchored on the previous page's
    oldest message, which snowflake ordering makes safe."""
    requests: list[str | None] = []
    first = [msg(str(900 - i)) for i in range(PAGE_LIMIT)]

    def handler(request):
        before = request.url.params.get("before")
        requests.append(before)
        return httpx.Response(200, json=first if before is None else [msg("800")])

    messages = list(client(handler).iter_messages("100", max_messages=PAGE_LIMIT + 1))

    assert requests == [None, first[-1]["id"]]
    assert len(messages) == PAGE_LIMIT + 1


def test_a_short_page_ends_the_walk():
    calls = []

    def handler(request):
        calls.append(request.url.params.get("before"))
        return httpx.Response(200, json=[msg("900")])

    list(client(handler).iter_messages("100", max_messages=500))

    assert calls == [None]


def test_a_revoked_token_or_a_kicked_bot_is_unauthorised(monkeypatch):
    for status in (401, 403):
        with pytest.raises(SourceUnauthorized):
            client(lambda r: httpx.Response(status)).list_text_channels(GUILD)


def test_a_missing_guild_is_not_found():
    with pytest.raises(SourceNotFound):
        client(lambda r: httpx.Response(404)).list_text_channels(GUILD)


def test_a_server_error_is_a_provider_error():
    with pytest.raises(SourceAPIError):
        client(lambda r: httpx.Response(500)).list_text_channels(GUILD)


def test_a_rate_limit_is_waited_out_then_retried():
    responses = [
        httpx.Response(429, json={"retry_after": 0.2}),
        httpx.Response(200, json=CHANNELS),
    ]
    waited: list[float] = []

    channels = DiscordClient(
        "t",
        transport=httpx.MockTransport(lambda r: responses.pop(0)),
        sleep=waited.append,
    ).list_text_channels(GUILD)

    assert waited == [0.2]
    assert len(channels) == 2


def test_a_rate_limit_longer_than_the_ceiling_is_raised_not_slept_off():
    with pytest.raises(SourceRateLimited) as raised:
        client(
            lambda r: httpx.Response(429, json={"retry_after": 99}),
            max_rate_limit_wait=10,
        ).list_text_channels(GUILD)

    assert raised.value.wait_seconds == 99


def test_a_malformed_channel_list_is_a_provider_error():
    with pytest.raises(SourceAPIError):
        client(lambda r: httpx.Response(200, json={"not": "a list"})).list_text_channels(
            GUILD
        )


# -- The adapter ---------------------------------------------------------------


def test_fetch_reports_what_it_read():
    fetched = adapter(routed({"100": [msg("900"), msg("901")]})).fetch()

    assert fetched.external_ref == GUILD
    assert fetched.display_ref == "Acme Guild"
    assert fetched.counts == {"channels": 1, "messages": 2}


def test_ids_are_provider_prefixed_so_they_cannot_collide_with_github():
    """A Discord user id is a numeric string; without the prefix it could not be
    told apart from an integer GitHub author id."""
    fetched = adapter(routed({"100": [msg("900")]})).fetch()

    (channel,) = fetched.payloads["channels"]
    (author,) = fetched.payloads["authors"]
    (message,) = fetched.payloads["messages"]
    assert channel.id == "discord/100"
    assert author.id == "discord/7001"
    assert message.id == "discord/100/900"
    assert message.channel_id == "discord/100"


def test_a_message_carries_a_link_back_to_discord():
    """US-08 AC4: opening a message's details offers the original."""
    fetched = adapter(routed({"100": [msg("900")]})).fetch()

    (message,) = fetched.payloads["messages"]
    assert message.url == f"https://discord.com/channels/{GUILD}/100/900"
    assert message_url("g", "c", "m") == "https://discord.com/channels/g/c/m"


def test_an_author_is_named_by_their_display_name():
    fetched = adapter(routed({"100": [msg("900")]})).fetch()

    (author,) = fetched.payloads["authors"]
    assert author.login == "Ada L"


def test_an_author_posting_twice_is_one_node():
    fetched = adapter(routed({"100": [msg("900"), msg("901")]})).fetch()

    assert len(fetched.payloads["authors"]) == 1


def test_a_reply_points_at_its_parent_in_the_same_channel():
    fetched = adapter(
        routed({"100": [msg("901", reply_to="900"), msg("900")]})
    ).fetch()

    replies = {m.id: m.reply_to_id for m in fetched.payloads["messages"]}
    assert replies["discord/100/901"] == "discord/100/900"
    assert replies["discord/100/900"] is None


def test_only_the_selected_channels_are_read():
    fetched = adapter(
        routed({"100": [msg("900")], "101": [msg("910")]}), channel_ids=("101",)
    ).fetch()

    (channel,) = fetched.payloads["channels"]
    assert channel.id == "discord/101"


def test_a_channel_the_bot_cannot_see_is_not_found():
    """Picked from a stale list, or the bot lost access since. Either way there
    is nothing to read, and the sync should say so rather than succeed empty."""
    with pytest.raises(SourceNotFound):
        adapter(routed({}), channel_ids=("999",)).fetch()


def test_the_adapter_closes_its_own_client():
    """Unlike GitHub's, this client is built in the handler, so the adapter owns it."""
    built = adapter(routed({"100": []}))
    built.fetch()

    built.close()

    with pytest.raises(RuntimeError):
        built._client._http.get("/anything")


def test_failures_are_described_for_the_sources_page():
    built = adapter(routed({"100": []}))

    assert built.describe(SourceRateLimited(5)) == "Discord rate limit reached"
    assert "Acme Guild" in built.describe(SourceUnauthorized("nope"))
    assert "Acme Guild" in built.describe(SourceNotFound("nope"))
