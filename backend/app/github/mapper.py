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
"""

import uuid
from collections.abc import Iterable
from typing import Any

from neo4j import Driver

from app.github.models import IssuePayload, PullRequestPayload

Statement = tuple[str, dict[str, Any]]

UPSERT_REPOSITORY = """
MERGE (r:Repository {repo: $repo, workspace_id: $workspace_id})
"""

UPSERT_AUTHORS = """
UNWIND $rows AS row
MERGE (a:Author {id: row.id, workspace_id: $workspace_id})
SET a.login = row.login, a.html_url = row.html_url
"""

UPSERT_PULL_REQUESTS = """
UNWIND $rows AS row
MERGE (p:PullRequest {id: row.props.id, workspace_id: $workspace_id})
SET p += row.props
WITH p, row
WHERE row.author_id IS NOT NULL
MATCH (a:Author {id: row.author_id, workspace_id: $workspace_id})
MERGE (a)-[:AUTHORED]->(p)
"""

UPSERT_ISSUES = """
UNWIND $rows AS row
MERGE (i:Issue {id: row.props.id, workspace_id: $workspace_id})
SET i += row.props
WITH i, row
WHERE row.author_id IS NOT NULL
MATCH (a:Author {id: row.author_id, workspace_id: $workspace_id})
MERGE (a)-[:AUTHORED]->(i)
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
) -> list[Statement]:
    """Validate raw payloads and return ordered (cypher, params) statements.

    ``repo`` is ``"owner/name"``. ``workspace_id`` is keyword-only on purpose:
    it and ``repo`` are both strings, so a positional swap would be silently
    wrong. Authors come first so the edge MATCHes succeed.
    """
    workspace = normalise_workspace_id(workspace_id)
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
        (UPSERT_REPOSITORY, {"repo": repo, "workspace_id": workspace})
    ]
    if authors:
        statements.append(
            (UPSERT_AUTHORS, {"rows": list(authors.values()), "workspace_id": workspace})
        )
    if prs:
        rows = [_item_row(p, repo, workspace, ("merged_at", "draft")) for p in prs]
        statements.append((UPSERT_PULL_REQUESTS, {"rows": rows, "workspace_id": workspace}))
    if iss:
        rows = [_item_row(i, repo, workspace) for i in iss]
        statements.append((UPSERT_ISSUES, {"rows": rows, "workspace_id": workspace}))
    return statements


def write_graph(
    driver: Driver,
    repo: str,
    pull_requests: Iterable[dict],
    issues: Iterable[dict],
    *,
    workspace_id: str | uuid.UUID,
) -> int:
    """Validate, then write everything in one transaction. Returns statements run."""
    statements = build_statements(
        repo, pull_requests, issues, workspace_id=workspace_id
    )

    def work(tx):
        for cypher, params in statements:
            tx.run(cypher, **params)

    with driver.session() as session:
        session.execute_write(work)
    return len(statements)
