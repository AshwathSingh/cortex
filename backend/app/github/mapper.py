"""Map raw GitHub JSON to Cypher for the T-7.2 graph schema.

Nodes:  (:Repository {repo, workspace_id}), (:Author {id, workspace_id}),
        (:PullRequest {...}), (:Issue {...})
Edges:  (:Author)-[:AUTHORED]->(:PullRequest | :Issue)

Every node is scoped to one workspace. ``workspace_id`` is part of the MERGE key
for all three labels, so two workspaces ingesting the same repo get separate
copies rather than fighting over one shared node, and the ``AUTHORED`` MATCH is
workspace-qualified so an edge can never bind to another workspace's author.

Payloads are validated with the Pydantic models first; if any payload is
invalid, ``ValidationError`` is raised before any statement is built or run, so
a bad batch creates zero nodes. All writes use MERGE on the composite key so
re-ingesting the same repo into the same workspace is idempotent.

T-12.3 -- reconciling a re-ingestion
------------------------------------
MERGE keeps a re-ingestion from creating a *second* copy of anything it writes.
It says nothing about what the re-ingestion no longer writes, and after a
failure has been fixed and the source re-synced, that is where duplicates come
from:

* an item deleted, transferred or made private upstream keeps its node forever,
  so the graph counts work that is gone and the Sources page over-reports
* an item whose author changed keeps the old ``AUTHORED`` edge *and* gains the
  new one, so one pull request shows two authors
* an author whose last item disappeared stays behind as a node with no edges

So every write stamps ``ingest_run`` with an id unique to this run, and the
statements that follow delete anything belonging to this repo that the run did
not touch. The whole sequence is one transaction (see ``write_graph``): a run
that fails part-way deletes nothing, which matters because a partial fetch would
otherwise look exactly like "these items were removed upstream".

Only nodes carrying this ``repo`` are pruned. Authors are shared across a
workspace's repositories, so they are removed on the weaker condition of having
no remaining authorship at all.
"""

import uuid
from collections.abc import Iterable
from typing import Any

from neo4j import Driver

from app.github.models import IssuePayload, PullRequestPayload

Statement = tuple[str, dict[str, Any]]

UPSERT_REPOSITORY = """
MERGE (r:Repository {repo: $repo, workspace_id: $workspace_id})
SET r.ingest_run = $run_id
"""

UPSERT_AUTHORS = """
UNWIND $rows AS row
MERGE (a:Author {id: row.id, workspace_id: $workspace_id})
SET a.login = row.login, a.html_url = row.html_url
"""

UPSERT_PULL_REQUESTS = """
UNWIND $rows AS row
MERGE (p:PullRequest {id: row.props.id, workspace_id: $workspace_id})
SET p += row.props, p.ingest_run = $run_id
WITH p, row
WHERE row.author_id IS NOT NULL
MATCH (a:Author {id: row.author_id, workspace_id: $workspace_id})
MERGE (a)-[:AUTHORED]->(p)
"""

UPSERT_ISSUES = """
UNWIND $rows AS row
MERGE (i:Issue {id: row.props.id, workspace_id: $workspace_id})
SET i += row.props, i.ingest_run = $run_id
WITH i, row
WHERE row.author_id IS NOT NULL
MATCH (a:Author {id: row.author_id, workspace_id: $workspace_id})
MERGE (a)-[:AUTHORED]->(i)
"""

# The labels these reconciliation statements are built for. Interpolated into
# Cypher, which is safe *only* because this is a module constant -- never take a
# label from a request (see the neo4j_function.py caveat in CLAUDE.md).
ITEM_LABELS: tuple[str, ...] = ("PullRequest", "Issue")


def _drop_stale_authorship(label: str) -> str:
    """Delete AUTHORED edges into these items from anyone but their current author.

    Runs *after* the upserts, so the edge this run merged is the one whose author
    id matches and the one that survives. A row whose ``author_id`` is null --
    GitHub returns no user for an item whose account is gone -- loses every
    incoming edge, which is correct: nobody owns it any more.
    """
    return f"""
UNWIND $rows AS row
MATCH (a:Author)-[r:AUTHORED]->(n:{label} {{id: row.props.id, workspace_id: $workspace_id}})
WHERE row.author_id IS NULL OR a.id <> row.author_id
DELETE r
"""


def _prune_vanished(label: str) -> str:
    """Delete this repo's items that the current run did not write.

    ``coalesce`` is what makes nodes written before ``ingest_run`` existed
    prunable: without it the comparison against a null property is null, which
    is not true, and a pre-upgrade node could never be collected. The first
    re-ingestion after this change therefore cleans up whatever is already stale.
    """
    return f"""
MATCH (n:{label} {{repo: $repo, workspace_id: $workspace_id}})
WHERE coalesce(n.ingest_run, '') <> $run_id
DETACH DELETE n
"""


PRUNE_ORPHAN_AUTHORS = """
MATCH (a:Author {workspace_id: $workspace_id})
WHERE NOT (a)-[:AUTHORED]->()
DETACH DELETE a
"""


def normalise_workspace_id(workspace_id: str | uuid.UUID | None) -> str:
    """Return the canonical string form of a workspace UUID, or raise.

    Guards the one failure that is invisible once written: a missing, blank or
    malformed ``workspace_id`` produces nodes that no workspace-scoped query can
    ever return, and Neo4j Community cannot reject them itself (no existence
    constraints). Canonicalising also keeps MERGE stable -- two spellings of the
    same UUID would otherwise create two separate copies of every node.
    """
    if workspace_id is None:
        raise ValueError("workspace_id is required; refusing to write unscoped graph nodes")
    text = str(workspace_id).strip()
    if not text:
        raise ValueError("workspace_id is required; refusing to write unscoped graph nodes")
    try:
        return str(uuid.UUID(text))
    except ValueError as exc:
        raise ValueError(f"workspace_id must be a UUID, got {text!r}") from exc


def _item_row(
    item, repo: str, workspace_id: str, extra_fields: tuple[str, ...] = ()
) -> dict[str, Any]:
    data = item.model_dump(mode="json")  # datetimes -> ISO-8601 strings
    keys = ("id", "number", "title", "state", "body", "html_url",
            "created_at", "updated_at", "closed_at", *extra_fields)
    props = {k: data[k] for k in keys}
    props["repo"] = repo
    props["workspace_id"] = workspace_id
    return {"props": props, "author_id": item.user.id if item.user else None}


def build_statements(
    repo: str,
    pull_requests: Iterable[dict],
    issues: Iterable[dict],
    *,
    workspace_id: str | uuid.UUID,
    run_id: str | None = None,
) -> list[Statement]:
    """Validate raw payloads and return ordered (cypher, params) statements.

    ``repo`` is ``"owner/name"``. ``workspace_id`` is keyword-only on purpose:
    it and ``repo`` are both strings, so a positional swap would be silently
    wrong. Authors come first so the edge MATCHes succeed, and the T-12.3
    reconciliation comes last so it only ever considers what this run wrote.

    ``run_id`` defaults to a fresh uuid. It is a parameter so a test can assert
    on a known marker; nothing in the application should pass one, and reusing a
    run id across two ingestions would make the second one prune nothing.
    """
    workspace = normalise_workspace_id(workspace_id)
    run = run_id or str(uuid.uuid4())
    prs = [PullRequestPayload.model_validate(p) for p in pull_requests]
    iss = [IssuePayload.model_validate(i) for i in issues]

    authors: dict[int, dict[str, Any]] = {}
    for item in (*prs, *iss):
        if item.user:
            authors[item.user.id] = item.user.model_dump(mode="json")

    # The repository node records a successful connection even when GitHub
    # returns no pull requests or issues. It is intentionally excluded from the
    # Graph Explorer's drawable labels and exists only as source metadata.
    statements: list[Statement] = [
        (UPSERT_REPOSITORY, {"repo": repo, "workspace_id": workspace, "run_id": run})
    ]
    if authors:
        statements.append(
            (UPSERT_AUTHORS, {"rows": list(authors.values()), "workspace_id": workspace})
        )

    rows_by_label: dict[str, list[dict[str, Any]]] = {
        "PullRequest": [
            _item_row(p, repo, workspace, ("merged_at", "draft")) for p in prs
        ],
        "Issue": [_item_row(i, repo, workspace) for i in iss],
    }
    upsert_by_label = {
        "PullRequest": UPSERT_PULL_REQUESTS,
        "Issue": UPSERT_ISSUES,
    }
    for label in ITEM_LABELS:
        rows = rows_by_label[label]
        if not rows:
            continue
        params = {"rows": rows, "workspace_id": workspace, "run_id": run}
        statements.append((upsert_by_label[label], params))
        statements.append(
            (_drop_stale_authorship(label), {"rows": rows, "workspace_id": workspace})
        )

    # Unconditional, including when GitHub returned nothing: a repository whose
    # every item was deleted upstream has to end up with no items, and "the
    # fetch came back empty" is exactly that case.
    for label in ITEM_LABELS:
        statements.append(
            (
                _prune_vanished(label),
                {"repo": repo, "workspace_id": workspace, "run_id": run},
            )
        )
    statements.append((PRUNE_ORPHAN_AUTHORS, {"workspace_id": workspace}))
    return statements


def write_graph(
    driver: Driver,
    repo: str,
    pull_requests: Iterable[dict],
    issues: Iterable[dict],
    *,
    workspace_id: str | uuid.UUID,
    run_id: str | None = None,
) -> int:
    """Validate, then write everything in one transaction. Returns statements run.

    One transaction covers the upserts *and* the T-12.3 reconciliation, so a run
    that dies half way deletes nothing. A partial fetch is indistinguishable
    from items being removed upstream, and pruning on the strength of one would
    delete live data.
    """
    statements = build_statements(
        repo, pull_requests, issues, workspace_id=workspace_id, run_id=run_id
    )

    def work(tx):
        for cypher, params in statements:
            tx.run(cypher, **params)

    with driver.session() as session:
        session.execute_write(work)
    return len(statements)
