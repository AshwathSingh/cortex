# Data sources (US-08)

Every provider Cortex reads from implements one contract. This is what the
ingestion endpoints talk to, and the only place a provider's quirks live.

## Layout

| Module | What it is |
| --- | --- |
| `base.py` | `SourceAdapter`, the `Source*` error taxonomy, the `KIND_*` constants |
| `pipeline.py` | `run_ingestion` — the sequence every provider shares |
| `github.py` | US-7's GitHub client/mapper behind the adapter |
| `slack.py` | Slack client + adapter (T-8.4) |
| `discord.py` | Discord client + adapter (T-8.3) |
| `chat_graph.py` | Normalised chat messages → Cypher, shared by Slack and Discord |
| `chat_oauth.py` | The two authorisation exchanges (T-8.2) |

## Adding a provider

1. Subclass `SourceAdapter`: `fetch()` reads the provider, `write()` puts it in
   the graph, `describe()` words its failures for the Sources page. Raise the
   `Source*` errors from `base.py` — `app.api.ingest.ERROR_STATUS` is what turns
   those into HTTP statuses, and it is the only place that mapping exists.
2. Add the `kind` string to `base.py`. `DataSource.kind` is a free-form column
   on purpose, so no migration is needed.
3. If the provider needs credentials, store them with
   `app.services.chat_credentials` rather than a new table.
4. New node labels mean a uniqueness constraint in `app.db.schema`, an entry in
   `GRAPH_LABELS`, the `Literal` on the node-details route, and `GraphNodeType`
   in `apps/web/src/lib/api-types.ts`. Re-run `scripts.init_graph_schema`.

Nothing in an adapter touches Postgres. The `data_sources` row — the lease, the
`PENDING` window, the final status — belongs to the pipeline, and an adapter
that wrote its own would make the lease unenforceable.

## Why the two chat providers work differently

**Slack** is a token flow. A member with `sources.write` installs Cortex into a
Slack team and the exchange returns a bot token scoped to that team, encrypted
per workspace in `source_credentials`.

**Discord** is an installation flow. Its HTTP API will not return channel
history for a user access token at all: `GET /channels/{id}/messages` requires a
**bot** token, the bot must be a member of the guild, and Message Content Intent
must be enabled on the application or `content` comes back empty with no error.
The `messages.read` scope exists only for local RPC against the desktop client.
So the install flow exists only to add the bot to a guild and learn which guild
it is; reads use the application-wide `DISCORD_BOT_TOKEN`, and
`source_credentials.access_token` is NULL for Discord.

## Provider habits worth knowing

- **Slack answers HTTP 200 for everything.** Success and failure are both
  `{"ok": …}` in the body, so the status code tells you nothing. A missing
  scope, a revoked token and a channel the bot was never invited to all arrive
  as 200.
- **Slack thread replies are a second endpoint.** `conversations.history`
  returns only thread parents, each carrying `reply_count`;
  `conversations.replies` echoes the parent back as its first element.
- **Discord paginates backwards.** No cursor: each page is anchored on the
  previous page's oldest message id via `before=`. Snowflake ids are monotonic,
  which is what makes that safe.
- **Ignoring a Discord 429 escalates to a ban** on the whole application, so the
  wait is honoured rather than retried blind.

## Graph ids

GitHub ids are integers in the graph. Chat ids are provider-prefixed strings —
`slack/U1`, `discord/912…`, `slack/C0ABC/1730000000.123456` — and the prefix is
load-bearing:

- `Author` is shared with GitHub. A Discord user id is a numeric string, so
  without the prefix it could not be told apart from an integer GitHub id.
- A Slack message timestamp is unique only *within a channel*, so a message id
  carries its channel.
- `app.graph.queries.coerce_node_id` recovers the type by trying `int()` first.
  Every prefixed id contains a `/`, so that always fails for chat and always
  succeeds for GitHub.

The node-details route uses a `:path` converter for the same reason: a chat id's
slashes would otherwise be split across path segments.

## Not yet built

- **Re-syncing a chat source from the Sources page.** A repository re-syncs from
  its row because the repo is the whole reference; a chat source needs channels
  chosen again, so it goes back through the picker.
- **Incremental sync.** Each run reads the newest
  `MAX_MESSAGES_PER_CHANNEL` (500) rather than everything since the last sync.
  Older history is reachable, but only by raising that ceiling.
- **Slack permalinks in canonical form.** `app_redirect` links are used because
  the `/archives/` form needs the team's own subdomain, which the OAuth exchange
  does not return and which would cost a `team:read` scope to look up.
