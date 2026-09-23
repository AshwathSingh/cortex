"""Create the relational tables for users, workspaces and membership (US-41).

Usage: python -m scripts.init_postgres_schema

Metches ``init_graph_schema.py``, which is how this project already
bootstraps the graph store.
"""

from app.db.models import Base
from app.db.postgres import dispose_engine, get_engine


def main() -> None:
    engine = get_engine()
    with engine.connect() as connection:
        connection.close()  # fail fast with a clear error if Postgres is unreachable
    Base.metadata.create_all(engine)
    print("Postgres tables created: users, workspaces, workspace_memberships.")
    dispose_engine()


if __name__ == "__main__":
    main()
