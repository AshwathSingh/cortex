# Removing an indexed source

Members with `sources.write` can remove a repository, uploaded document, Slack
workspace, Discord server, or a single indexed chat channel from Sources. The
confirmation names the target and explains content removal, shared-data
preservation, and provider access. Cancel receives initial focus. Pending work
cannot be submitted twice or dismissed; failures stay in the dialog for retry.

Run `alembic upgrade head` from `backend` before using this feature. Migration
`20261117_16` adds the cleanup journal; `20261126_17` backfills indexed target
tombstones and workspace revision/pending counters. Both upgrades preserve
existing pending retries. No raw source content is retained.

- `DELETE /api/workspaces/{id}/sources` accepts `kind`, `external_ref`, and an
  optional provider-prefixed `channel_id` (for example `slack/C123`).
- `GET /api/workspaces/{id}/sources/channels?kind=slack&external_ref=T123` lists
  indexed channels, including channels whose provider has been disconnected.

Deletion removes owned graph nodes, incident relationships and inline evidence,
plus PostgreSQL inventory entries, comments and read markers for removed targets.
Authors linked to surviving content remain. Review flags and their evidence are
computed on read, so removed content no longer contributes findings. Original
provider content and credentials are unaffected. Uploaded bytes are not retained
by the existing upload pipeline.

The journal commits affected target identifiers before graph cleanup. A failed
cleanup stays pending and is visible in the inventory for retry. A pending channel
removal marks only that channel and keeps its retry available after graph deletion. Do not manually
clear a pending journal: it blocks re-ingestion until cleanup finishes. Completed
journals retain a revision; removed identifiers live in an indexed target table.
Comment writes look up one target rather than loading historical journals.
Restored targets are pruned when used again; shared surviving targets are pruned
during cleanup. Completed journal JSON plans are cleared. A later explicit ingestion may add the source again.
Workspace row locks serialize cleanup with graph writes; provider and upload
pipelines check the revision before writing graph data or failure bookkeeping.

Successful removal refreshes inventory, graph, comment badges, failures and review
flags in mounted views, including other tabs on the same origin. Other users'
browsers receive fresh data on their next read; this is not a server push channel.

Validation uses reserved Neo4j test workspaces and disposable PostgreSQL databases:
`python -m pytest tests/test_source_removal.py`. The tests cover permissions,
shared authors, channel and workspace isolation, upload identity, partial-failure
retry, PostgreSQL writer locking, and removal during ingestion.

Connection Agent runs snapshot one workspace revision using one reusable session. Graph
writes hold a shared workspace lock and reject results from an older revision,
including when the same source is re-added with identical node ids. Model calls
hold no database lock. Successful removal queues fresh analysis for surviving
artifacts. Active, pending-review and rejected incident edges are removed with
the source, including their inline evidence and attached comments.

Each graph write rechecks one locked workspace row; checking only once per run
would allow a delayed model result to recreate deleted relationships. No
SourceRemoval history is queried by that guard.

Graph cleanup uses the shared mutation layer and emits `source.graph_removed`
after graph commit. SQL cleanup emits `source.removed` after relational commit,
with comment/read-marker/source counts. Both carry actor and operation id; empty
retries emit no duplicate graph event. These use the existing best-effort audit
hooks, not a durable cross-store event outbox.

The directed anonymous match in agent-edge retyping is intentional: Neo4j's
undirected form returns both orientations and can create two replacement edges.
Live graph regression coverage asserts that distinction. Surviving targets use
the same label-selection helper as graph node keys, including multi-label nodes.
