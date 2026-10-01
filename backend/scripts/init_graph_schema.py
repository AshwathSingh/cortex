"""Apply Neo4j schema constraints. Idempotent -- safe to re-run.

Usage: python -m scripts.init_graph_schema

Also drops the pre-workspace constraints (single-property uniqueness on ``id``),
which must go for the composite ``(id, workspace_id)`` ones to mean anything.
Nodes ingested before workspace scoping carry no ``workspace_id`` and cannot be
backfilled -- nothing records which workspace a repo belonged to -- so wipe the
graph and re-ingest: ``docker compose down -v``, or
``MATCH (n) DETACH DELETE n`` in cypher-shell.
"""

from app.db.neo4j_driver import close_driver, get_driver, verify_connectivity
from app.db.schema import CONSTRAINTS, LEGACY_CONSTRAINTS, apply_constraints


def main() -> None:
    verify_connectivity()
    apply_constraints(get_driver())
    print(
        f"Neo4j schema: dropped {len(LEGACY_CONSTRAINTS)} pre-workspace constraint(s) "
        f"if present, applied {len(CONSTRAINTS)} composite (id, workspace_id) constraint(s)."
    )
    close_driver()


if __name__ == "__main__":
    main()
