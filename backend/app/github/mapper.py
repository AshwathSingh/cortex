"""Map raw GitHub JSON to Cypher for the T-7.2 graph schema.

Nodes:  (:Author {id}), (:PullRequest {id}), (:Issue {id})  -- id is GitHub's id
Edges:  (:Author)-[:AUTHORED]->(:PullRequest | :Issue)

Payloads are validated with the Pydantic models first; if any payload is
invalid, ``ValidationError`` is raised before any statement is built or run, so
a bad batch creates zero nodes. All writes use MERGE on ``id`` so re-ingesting
the same repo is idempotent.
"""

from collections.abc import Iterable
from typing import Any

from neo4j import Driver

from app.github.models import IssuePayload, PullRequestPayload

Statement = tuple[str, dict[str, Any]]

UPSERT_AUTHORS = """
UNWIND $rows AS row
MERGE (a:Author {id: row.id})
SET a.login = row.login, a.html_url = row.html_url
"""

UPSERT_PULL_REQUESTS = """
UNWIND $rows AS row
MERGE (p:PullRequest {id: row.props.id})
SET p += row.props
WITH p, row
WHERE row.author_id IS NOT NULL
MATCH (a:Author {id: row.author_id})
MERGE (a)-[:AUTHORED]->(p)
"""

UPSERT_ISSUES = """
UNWIND $rows AS row
MERGE (i:Issue {id: row.props.id})
SET i += row.props
WITH i, row
WHERE row.author_id IS NOT NULL
MATCH (a:Author {id: row.author_id})
MERGE (a)-[:AUTHORED]->(i)
"""


def _item_row(item, repo: str, extra_fields: tuple[str, ...] = ()) -> dict[str, Any]:
    data = item.model_dump(mode="json")  # datetimes -> ISO-8601 strings
    keys = ("id", "number", "title", "state", "body", "html_url",
            "created_at", "updated_at", "closed_at", *extra_fields)
    props = {k: data[k] for k in keys}
    props["repo"] = repo
    return {"props": props, "author_id": item.user.id if item.user else None}


def build_statements(
    repo: str, pull_requests: Iterable[dict], issues: Iterable[dict]
) -> list[Statement]:
    """Validate raw payloads and return ordered (cypher, params) statements.

    ``repo`` is ``"owner/name"``. Authors come first so the edge MATCHes succeed.
    """
    prs = [PullRequestPayload.model_validate(p) for p in pull_requests]
    iss = [IssuePayload.model_validate(i) for i in issues]

    authors: dict[int, dict[str, Any]] = {}
    for item in (*prs, *iss):
        if item.user:
            authors[item.user.id] = item.user.model_dump(mode="json")

    statements: list[Statement] = []
    if authors:
        statements.append((UPSERT_AUTHORS, {"rows": list(authors.values())}))
    if prs:
        rows = [_item_row(p, repo, ("merged_at", "draft")) for p in prs]
        statements.append((UPSERT_PULL_REQUESTS, {"rows": rows}))
    if iss:
        rows = [_item_row(i, repo) for i in iss]
        statements.append((UPSERT_ISSUES, {"rows": rows}))
    return statements


def write_graph(
    driver: Driver, repo: str, pull_requests: Iterable[dict], issues: Iterable[dict]
) -> int:
    """Validate, then write everything in one transaction. Returns statements run."""
    statements = build_statements(repo, pull_requests, issues)

    def work(tx):
        for cypher, params in statements:
            tx.run(cypher, **params)

    with driver.session() as session:
        session.execute_write(work)
    return len(statements)
