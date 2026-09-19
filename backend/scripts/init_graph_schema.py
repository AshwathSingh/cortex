"""Run once against a fresh Neo4j instance to apply schema constraints.

Usage: python -m scripts.init_graph_schema
"""

from app.db.neo4j_driver import close_driver, get_driver, verify_connectivity
from app.db.schema import apply_constraints


def main() -> None:
    verify_connectivity()
    apply_constraints(get_driver())
    print("Neo4j schema constraints applied.")
    close_driver()


if __name__ == "__main__":
    main()
