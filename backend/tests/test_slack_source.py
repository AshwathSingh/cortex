"""T-8.4: the Slack client and adapter.

Slack is faked with an httpx MockTransport. Three of its habits drive most of
this file: every call answers HTTP 200 and reports failure in the body, pages
are walked with an opaque cursor, and thread replies live behind a second
endpoint rather than in the channel history.
"""

import httpx
import pytest

from app.sources.base import (
    SourceAPIError,
    SourceNotFound,
    SourceRateLimited,
    SourceUnauthorized,
)
from app.sources.slack import SlackAdapter, SlackClient, message_url

TEAM = "T0ACME"

CHANNELS = [
    {"id": "C1", "name": "general", "is_archived": False},
    {"id": "C2", "name": "design", "is_archived": False},
    {"id": "C9", "name": "old", "is_archived": True},  # filtered out
]
USERS = [
    {"id": "U1", "name": "ada", "real_name": "Ada Lovelace", "profile": {"display_name": "ada.l"}},
    {"id": "U2", "name": "bob", "real_name": "Bob", "profile": {}},
]


def ok(**body) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, **body})


def msg(ts="1730000000.000100", *, text="hello", user="U1", **over) -> dict:
    return {"ts": ts, "text": text, "user": user, **over}


def client(handler, **over) -> SlackClient:
    return SlackClient(
        "xoxb-token",
        transport=httpx.MockTransport(handler),
        sleep=lambda s: None,
        **over,
    )


def adapter(handler, channel_ids=("C1",), **over) -> SlackAdapter:
    return SlackAdapter(
        client(handler, **over),
        team_id=TEAM,
        team_name="Acme",
        channel_ids=list(channel_ids),
    )


def routed(history: dict[str, list[dict]], replies: dict[str, list[dict]] | None = None):
    """A handler serving conversations.list / users.list / history / replies."""
    replies = replies or {}

    def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "conversations.list":
            return ok(channels=CHANNELS)
        if method == "users.list":
            return ok(members=USERS)
        if method == "conversations.history":
            channel = request.url.params["channel"]
            return ok(messages=history.get(channel, []))
        if method == "conversations.replies":
            return ok(messages=replies.get(request.url.params["ts"], []))
        raise AssertionError(f"unexpected call to {method}")

    return handler


# -- The client ----------------------------------------------------------------


def test_requests_carry_the_bot_token():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["Authorization"]
        return ok(channels=[])

    client(handler).list_channels()

    assert seen["auth"] == "Bearer xoxb-token"


def test_archived_channels_are_not_offered():
    channels = client(lambda r: ok(channels=CHANNELS)).list_channels()

    assert [c.id for c in channels] == ["C1", "C2"]


def test_pages_are_walked_with_the_cursor_until_it_is_empty():
    """`next_cursor` is absent or empty on the last page, never null-and-present."""
    cursors: list[str | None] = []

    def handler(request):
        cursor = request.url.params.get("cursor")
        cursors.append(cursor)
        if cursor is None:
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "channels": [CHANNELS[0]],
                    "response_metadata": {"next_cursor": "page2"},
                },
            )
        return httpx.Response(
            200,
            json={
                "ok": True,
                "channels": [CHANNELS[1]],
                "response_metadata": {"next_cursor": ""},
            },
        )

    channels = client(handler).list_channels()

    assert cursors == [None, "page2"]
    assert [c.id for c in channels] == ["C1", "C2"]


@pytest.mark.parametrize(
    "error", ["invalid_auth", "token_revoked", "missing_scope", "account_inactive"]
)
def test_a_credential_failure_is_unauthorised_not_a_retry(error):
    """Reported as HTTP 200 with ok=false, so the status code says nothing."""
    with pytest.raises(SourceUnauthorized):
        client(lambda r: httpx.Response(200, json={"ok": False, "error": error})).list_channels()


@pytest.mark.parametrize("error", ["channel_not_found", "not_in_channel", "is_archived"])
def test_a_channel_failure_is_not_found(error):
    with pytest.raises(SourceNotFound):
        client(lambda r: httpx.Response(200, json={"ok": False, "error": error})).list_channels()


def test_an_unrecognised_error_is_a_provider_error():
    with pytest.raises(SourceAPIError, match="fatal_error"):
        client(
            lambda r: httpx.Response(200, json={"ok": False, "error": "fatal_error"})
        ).list_channels()


def test_a_429_is_waited_out_then_retried():
    responses = [
        httpx.Response(429, headers={"Retry-After": "2"}),
        ok(channels=CHANNELS),
    ]
    waited: list[float] = []

    channels = SlackClient(
        "t",
        transport=httpx.MockTransport(lambda r: responses.pop(0)),
        sleep=waited.append,
    ).list_channels()

    assert waited == [2.0]
    assert len(channels) == 2


def test_a_rate_limit_longer_than_the_ceiling_is_raised():
    with pytest.raises(SourceRateLimited):
        client(
            lambda r: httpx.Response(429, headers={"Retry-After": "900"}),
            max_rate_limit_wait=60,
        ).list_channels()


def test_a_ratelimited_body_is_also_a_rate_limit():
    with pytest.raises(SourceRateLimited):
        client(
            lambda r: httpx.Response(200, json={"ok": False, "error": "ratelimited"})
        ).list_channels()


def test_replies_skip_the_parent_slack_echoes_back():
    parent = msg("1.1")
    handler = routed({}, {"1.1": [parent, msg("1.2")]})

    replies = list(client(handler).iter_replies("C1", "1.1"))

    assert [r.ts for r in replies] == ["1.2"]


# -- The adapter ---------------------------------------------------------------


def test_fetch_reports_what_it_read():
    fetched = adapter(routed({"C1": [msg("1.1"), msg("1.2")]})).fetch()

    assert fetched.external_ref == TEAM
    assert fetched.display_ref == "Acme"
    assert fetched.counts == {"channels": 1, "messages": 2}


def test_ids_are_prefixed_and_messages_carry_their_channel():
    """A Slack timestamp is unique only within a channel, so the id includes it."""
    fetched = adapter(routed({"C1": [msg("1730000000.000100")]})).fetch()

    (channel,) = fetched.payloads["channels"]
    (author,) = fetched.payloads["authors"]
    (message,) = fetched.payloads["messages"]
    assert channel.id == "slack/C1"
    assert author.id == "slack/U1"
    assert message.id == "slack/C1/1730000000.000100"
    assert message.channel_id == "slack/C1"


def test_a_message_carries_a_link_back_to_slack():
    """US-08 AC4. app_redirect, because the archive permalink needs the team's
    own subdomain, which the OAuth exchange never returns."""
    fetched = adapter(routed({"C1": [msg("1730000000.000100")]})).fetch()

    (message,) = fetched.payloads["messages"]
    assert message.url == message_url("C1", "1730000000.000100")
    assert message.url.startswith("https://slack.com/app_redirect?channel=C1")


def test_timestamps_become_iso_8601_like_every_other_node():
    fetched = adapter(routed({"C1": [msg("1730000000.000100")]})).fetch()

    (message,) = fetched.payloads["messages"]
    assert message.created_at.startswith("2024-10-27T")


def test_authors_are_named_from_the_user_list():
    fetched = adapter(
        routed({"C1": [msg("1.1", user="U1"), msg("1.2", user="U2")]})
    ).fetch()

    names = sorted(a.login for a in fetched.payloads["authors"])
    assert names == ["Bob", "ada.l"]


def test_joins_and_topic_changes_are_not_content():
    fetched = adapter(
        routed({"C1": [msg("1.1"), msg("1.2", subtype="channel_join")]})
    ).fetch()

    assert [m.id for m in fetched.payloads["messages"]] == ["slack/C1/1.1"]


def test_thread_replies_are_pulled_and_linked_to_their_parent():
    """conversations.history returns only parents, so replies need a second call."""
    parent = msg("1.1", reply_count=2, thread_ts="1.1")
    handler = routed(
        {"C1": [parent]},
        {"1.1": [parent, msg("1.2", thread_ts="1.1"), msg("1.3", thread_ts="1.1")]},
    )

    fetched = adapter(handler).fetch()

    links = {m.id: m.reply_to_id for m in fetched.payloads["messages"]}
    assert links == {
        "slack/C1/1.1": None,
        "slack/C1/1.2": "slack/C1/1.1",
        "slack/C1/1.3": "slack/C1/1.1",
    }


def test_a_thread_with_no_replies_costs_no_extra_call():
    calls: list[str] = []

    def handler(request):
        method = request.url.path.rsplit("/", 1)[-1]
        calls.append(method)
        if method == "conversations.list":
            return ok(channels=CHANNELS)
        if method == "users.list":
            return ok(members=USERS)
        return ok(messages=[msg("1.1", reply_count=0)])

    adapter(handler).fetch()

    assert "conversations.replies" not in calls


def test_only_the_selected_channels_are_read():
    fetched = adapter(
        routed({"C1": [msg("1.1")], "C2": [msg("2.1")]}), channel_ids=("C2",)
    ).fetch()

    (channel,) = fetched.payloads["channels"]
    assert channel.id == "slack/C2"


def test_a_channel_cortex_was_never_invited_to_is_not_found():
    with pytest.raises(SourceNotFound):
        adapter(routed({}), channel_ids=("CNOPE",)).fetch()


def test_the_adapter_closes_its_own_client():
    built = adapter(routed({"C1": []}))
    built.fetch()

    built.close()

    with pytest.raises(RuntimeError):
        built._client._http.get("/anything")


def test_failures_are_described_for_the_sources_page():
    built = adapter(routed({"C1": []}))

    assert built.describe(SourceRateLimited(5)) == "Slack rate limit reached"
    assert "Acme" in built.describe(SourceUnauthorized("nope"))
    assert "Acme" in built.describe(SourceNotFound("nope"))
