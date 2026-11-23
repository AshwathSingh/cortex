# Removing an indexed source

Members with `sources.write` can remove a repository, uploaded document, Slack
workspace, Discord server, or a single indexed chat channel from Sources. The
confirmation names the target and explains content removal, shared-data
preservation, and provider access. Cancel receives initial focus. Pending work
cannot be submitted twice or dismissed; failures stay in the dialog for retry.

Run `alembic upgrade head` from `backend` before using this feature. Migration
`20261117_16` adds `source_removals`, a cleanup journal with no raw source content.

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
cleanup stays pending and is visible in the inventory for retry. Do not manually
clear a pending journal: it blocks re-ingestion until cleanup finishes. Completed
journals retain identifiers and a revision to reject stale comment submissions
and fence older fetches. A later explicit ingestion may add the source again.
Workspace row locks serialize cleanup with graph writes; provider and upload
pipelines check the revision before writing graph data or failure bookkeeping.

Successful removal refreshes inventory, graph, comment badges, failures and review
flags in mounted views, including other tabs on the same origin. Other users'
browsers receive fresh data on their next read; this is not a server push channel.

Validation uses reserved Neo4j test workspaces and disposable PostgreSQL databases:
`python -m pytest tests/test_source_removal.py`. The tests cover permissions,
shared authors, channel and workspace isolation, upload identity, partial-failure
retry, PostgreSQL writer locking, and removal during ingestion.
