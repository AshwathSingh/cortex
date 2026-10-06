"""Graph schema constraints for GitHub-derived nodes and connected repositories.

Locking these early so downstream consumers of the schema (node/edge detail
panels, canvas rendering) can build against stable node labels and id
properties.

Every node is scoped to one workspace by a ``workspace_id`` property. Graph
items use ``(id, workspace_id)`` for uniqueness; repository metadata uses
``(repo, workspace_id)``. Two workspaces can therefore connect the same repo
without sharing nodes.

Neo4j Community has no existence constraints (and ``IS NODE KEY`` is Enterprise
only), so "every node carries a workspace_id" is enforced in
``app.github.mapper``, not by the database.
"""

from neo4j import Driver

# Pre-workspace constraints (T-7.2) made a GitHub id globally unique, which
# collapses two workspaces' copies of the same node into one -- the second
# ingestion would overwrite the first workspace's tag and empty its graph.
# Dropping them is what makes the composite constraints below meaningful.
LEGACY_CONSTRAINTS = [
    "DROP CONSTRAINT author_id_unique IF EXISTS",
    "DROP CONSTRAINT pull_request_id_unique IF EXISTS",
    "DROP CONSTRAINT issue_id_unique IF EXISTS",
]

CONSTRAINTS = [
    "CREATE CONSTRAINT repository_workspace_unique IF NOT EXISTS "
    "FOR (r:Repository) REQUIRE (r.repo, r.workspace_id) IS UNIQUE",
    "CREATE CONSTRAINT author_workspace_unique IF NOT EXISTS "
    "FOR (a:Author) REQUIRE (a.id, a.workspace_id) IS UNIQUE",
    "CREATE CONSTRAINT pull_request_workspace_unique IF NOT EXISTS "
    "FOR (p:PullRequest) REQUIRE (p.id, p.workspace_id) IS UNIQUE",
    "CREATE CONSTRAINT issue_workspace_unique IF NOT EXISTS "
    "FOR (i:Issue) REQUIRE (i.id, i.workspace_id) IS UNIQUE",
]


def apply_constraints(driver: Driver) -> None:
    """Drop the pre-workspace constraints, then apply the composite ones.

    Idempotent: every statement is ``IF EXISTS`` / ``IF NOT EXISTS``. The drops
    run first because the old single-property constraints would otherwise keep
    enforcing global id uniqueness alongside the new ones.
    """
    with driver.session() as session:
        for statement in (*LEGACY_CONSTRAINTS, *CONSTRAINTS):
            session.run(statement)
