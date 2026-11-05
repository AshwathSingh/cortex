# Comments on nodes and edges (US-27) — run and test

Run the backend as in [INVITES.md](INVITES.md), then apply the new migration: `alembic upgrade head`.

## Test

```bash
cd backend
python -m pytest tests/test_graph_comments_api.py -q
```

```bash
cd apps/web
npx vitest run src/components/graph/graph-comments.test.tsx \
  src/components/graph/graph-canvas-comments.test.tsx \
  src/lib/graph-comment-target.test.ts
```

## Try it

```bash
A=http://localhost:8000/api/workspaces/<WORKSPACE_ID>/graph/comments
# comment on a node
curl -s -b owner.jar -X POST $A -H 'content-type: application/json' \
  -d '{"target_kind":"node","target_key":"Issue:42","body":"Where is the evidence?"}' | jq
# read the thread
curl -s -b owner.jar "$A?target_kind=node&target_key=Issue:42" | jq
# what the canvas marks, for the signed-in caller
curl -s -b owner.jar $A/activity | jq
# mark it read
curl -s -b owner.jar -X POST $A/seen -H 'content-type: application/json' \
  -d '{"target_kind":"node","target_key":"Issue:42"}' | jq
```

## Rules

| Request | Does |
| --- | --- |
| `GET /graph/comments?target_kind=&target_key=` | one target's thread, oldest first |
| `POST /graph/comments` | add one; also marks the thread read for its author |
| `DELETE /graph/comments/{id}` | author, or anyone with `members.manage` |
| `GET /graph/comments/activity` | every commented-on target, with this reader's unseen count |
| `POST /graph/comments/seen` | record that this reader has read a target |

- Targets are the keys the canvas already uses: `Issue:42` for a node,
  `Author:7|AUTHORED|Issue:42` for an edge. A key of the wrong shape is a 422.
- Nothing checks the target exists. Graph nodes live in Neo4j, and a node pruned by
  a later ingestion must not take the discussion about it away.
- Any member may read and comment, a VIEWER included: the story is about discussing
  a suggestion *before* approving it, which a reader who cannot speak is shut out of.
- Comments are scoped to their workspace by id as well as by list, so one from
  another workspace is a 404 rather than a 403 (AC3).
- A comment outlives its author (`ON DELETE SET NULL`) and renders as
  "Former member"; removing someone must not rewrite a discussion others acted on.
- The canvas badge is filled for unseen and hollow for read — shape, not colour, so
  it survives greyscale and colour blindness. Your own comments are never unseen.
