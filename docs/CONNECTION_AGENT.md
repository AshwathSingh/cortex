# Connection Agent (US-23)

After an ingestion commits (GitHub, Slack, Discord, uploads), `emit_artifact_ingested(workspace_id)`
queues a background run (`app/agent/events.py`); ingestion never waits for it or fails because of it.

**Run** (`app/agent/service.py`): find artifacts (PullRequest, Issue, DocumentSection) whose content hash
differs from the last analysed one -> pre-filter candidates in the same workspace
(`candidates.py`: explicit refs, shared keywords, author, time; top N) -> one Jev request per pair with
one Noul question per relationship type (`relationships.py`, all wording there) -> the best type wins
(a specific type beats a vaguer one within 0.05) -> route by probability -> upsert via
`app/graph/mutations.py` (the audit-log hook: `add_mutation_listener`).

| probability | result |
|---|---|
| `>= CONNECTION_AGENT_CONFIDENCE_THRESHOLD` (0.7) | `AGENT_RELATIONSHIP` edge, `status=active` |
| `>= CONNECTION_AGENT_REVIEW_FLOOR` (0.4) | `status=pending_review`, shown in "Suggested connections" |
| below | discarded |

Edge properties are snake_case like the manual edges: `id, workspace_id, relationship_type, origin,
source_agent, model_version, status, confidence, evidence, dedup_key, reviewed_by, reviewed_at,
created_at, updated_at`. Manual edges (`MANUAL_RELATIONSHIP`) count as `origin=manual, status=active`.

**For teammates:** every edge read must use `active_edge("r")` from `app/graph/queries.py`
(excludes `pending_review` and `rejected`). A user-removed agent edge is kept as `rejected` (tombstone),
so the pair is never re-suggested; a manual edge between two artifacts also stops the agent.

**Failure:** a Jev failure marks that artifact `analysis_status=failed` (retried with backoff first),
logs without content/secrets, and the next run or `POST .../connections/retry` picks it up again.

**API:** `GET .../connections/summary|suggestions`, `POST .../connections/suggestions/{id}/approve|reject`
(editors, 403 for viewers), `POST .../connections/retry` (editors).
