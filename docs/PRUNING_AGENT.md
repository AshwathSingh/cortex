# Pruning Agent (US-28) — run and test

Run the backend as in [INVITES.md](INVITES.md). No migration: the rules read the
graph and nothing is stored.

## Test

```bash
cd backend
python -m pytest tests/test_pruning_rules.py -q        # the rules, no database
python -m pytest tests/test_flags_api.py -q            # the endpoint
python -m pytest tests/test_pruning_integration.py -q  # real Neo4j
```

```bash
cd apps/web
npx vitest run src/components/review/review-queue.test.tsx src/lib/use-workspace-flags.test.tsx
```

## Try it

```bash
A=http://localhost:8000/api
curl -s -b owner.jar $A/workspaces/<WORKSPACE_ID>/flags | jq '.flags[] | {rule, severity, summary}'
# just the worst ones
curl -s -b owner.jar $A/workspaces/<WORKSPACE_ID>/flags \
  | jq '[.flags[] | select(.severity=="HIGH")]'
```

The page is **Review queue** in the workspace sidebar.

## Rules

`GET /api/workspaces/{id}/flags` → the findings, most serious first. Any member may
read it: a review queue only half the team can see is not a review queue (AC3).

| Rule | Fires when | Severity |
| --- | --- | --- |
| `STALE` | an item is still open and untouched for 90+ days | 90d low, 180d medium, 365d high |
| `CONTRADICTED` | two items in one repo share a subject, one resolved and one still open | high if the resolved one was merged, else medium |
| `THIN` | an open or merged item has under 40 characters of description, or no recorded author | both missing is high, no author medium, no description low |

Two items "share a subject" when their titles are identical once case,
punctuation, status prefixes (`fix:`, `[WIP]`) , filler words and word order are
dropped. Action verbs are kept on purpose — without them "Add rate limiting" and
"Remove rate limiting" would collapse into one subject, and flagging two opposite
items as duplicates is worse than missing a real duplicate.

Every flag carries:

- `summary` — one sentence naming the items and what is wrong (AC2)
- `severity` — how serious (AC2)
- `targets` — the canvas keys, titles and GitHub links of the items concerned
- `evidence` — the facts that produced it, so the reader can decide whether the
  agent was right (AC4)

## Design

The detection runs **on the read**, not on a schedule into a table. A stored flag
goes stale the moment the thing it describes changes, so a queue built from a table
keeps showing findings that have already been fixed; and the rules are a linear
pass over one Cypher read, so there is nothing to amortise. Fixing an item and
re-syncing clears its flag with no bookkeeping.

Flag ids are derived from the rule plus the items it concerns, so the same finding
keeps the same id across runs even though nothing is persisted.

## Not yet built

- **Dismissing a flag.** There is nowhere to put the dismissal. This is the first
  thing to add if the queue grows past the point where re-reading it is enough;
  flag ids are already stable enough for that table to reference.
- **Flags on edges.** The only edge in the graph is `AUTHORED`, which the ingestion
  derives mechanically — there is nothing to doubt about it. Edge flagging becomes
  meaningful when the Connection Agent starts inferring links.
- **A sidebar count.** The `reviewCount` badge is still unwired: filling it would
  put a full graph scan on every workspace page load.
