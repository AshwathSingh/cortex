"""Graph schema constraints for GitHub-derived nodes (PRs, Issues, Authors).

Locking these early so downstream consumers of the schema (node/edge detail
panels, canvas rendering) can build against stable node labels and id
properties.
"""

from neo4j import Driver

CONSTRAINTS = [
    "CREATE CONSTRAINT author_id_unique IF NOT EXISTS "
    "FOR (a:Author) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT pull_request_id_unique IF NOT EXISTS "
    "FOR (p:PullRequest) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT issue_id_unique IF NOT EXISTS "
    "FOR (i:Issue) REQUIRE i.id IS UNIQUE",
]


def apply_constraints(driver: Driver) -> None:
    with driver.session() as session:
        for statement in CONSTRAINTS:
            session.run(statement)
